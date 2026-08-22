import asyncio
import time
from contextlib import asynccontextmanager

import httpx
import paramiko
from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.tasks import celery_app
from app.config import settings
from app.metrics.parser import parse_value, parse_value_text
from app.collectors.base import MetricResult


@asynccontextmanager
async def _get_session():
    engine = create_async_engine(
        settings.database_url, echo=False, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.collect_device")
def collect_device(device_id: str):
    """Collect all due metrics for a device using shared connections."""
    asyncio.run(_collect_device(device_id))


async def _collect_device(device_id: str):
    from datetime import datetime, timezone
    from sqlalchemy import select, func
    from app.models.device import Device, DeviceStatus
    from app.models.metric import MetricDefinition, MetricData

    async with _get_session() as session:
        device = (await session.execute(
            select(Device).where(Device.id == device_id, Device.collect_enabled == True)
        )).scalar_one_or_none()
        if not device:
            return

        metrics = (await session.execute(
            select(MetricDefinition).where(MetricDefinition.enabled == True)
        )).scalars().all()
        if not metrics:
            return

        api_metrics = [m for m in metrics if m.collector == 'panos_api']
        ssh_metrics = [m for m in metrics if m.collector == 'panos_ssh']
        report_metrics_all = [m for m in metrics if m.collector == 'panos_report']
        report_metrics = []
        for m in report_metrics_all:
            last = (await session.execute(
                select(func.max(MetricData.timestamp)).where(
                    MetricData.device_id == device_id,
                    MetricData.metric_name == m.name,
                )
            )).scalar()
            if last is None or (datetime.now(timezone.utc) - last).total_seconds() >= m.interval:
                report_metrics.append(m)

        has_success = False
        has_attempt = False

        if api_metrics and device.api_key_encrypted:
            has_attempt = True
            results = await _collect_api_batch(device, api_metrics)
            for result in results:
                if result.success:
                    has_success = True
                    stored_name = result.metric_name
                    if result.labels and result.labels.get("instance"):
                        stored_name = f"{result.metric_name}::{result.labels['instance']}"
                    session.add(MetricData(
                        timestamp=result.timestamp,
                        device_id=result.device_id,
                        metric_name=stored_name,
                        value=result.value,
                        labels=result.labels or None,
                    ))

        if ssh_metrics and device.ssh_username:
            has_attempt = True
            results = await _collect_ssh_batch(device, ssh_metrics)
            for result in results:
                if result.success:
                    has_success = True
                    stored_name = result.metric_name
                    if result.labels and result.labels.get("instance"):
                        stored_name = f"{result.metric_name}::{result.labels['instance']}"
                    session.add(MetricData(
                        timestamp=result.timestamp,
                        device_id=result.device_id,
                        metric_name=stored_name,
                        value=result.value,
                        labels=result.labels or None,
                    ))

        if report_metrics and device.api_key_encrypted:
            has_attempt = True
            results = await _collect_report_batch(device, report_metrics)
            for result in results:
                if result.success:
                    has_success = True
                    session.add(MetricData(
                        timestamp=result.timestamp,
                        device_id=result.device_id,
                        metric_name=result.metric_name,
                        value=result.value,
                        labels=result.labels or None,
                    ))

        if has_success:
            device.status = DeviceStatus.online
            device.last_seen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif has_attempt:
            device.status = DeviceStatus.offline

        await session.commit()


async def _collect_api_batch(device, metrics) -> list[MetricResult]:
    """Collect multiple API metrics using a single HTTPS connection."""
    results = []
    try:
        url = f"https://{device.hostname}/api/"
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            for metric_def in metrics:
                try:
                    params = {
                        "type": "op",
                        "cmd": metric_def.command,
                        "key": device.api_key_decrypted,
                    }
                    response = await client.get(url, params=params)
                    response.raise_for_status()

                    root = etree.fromstring(response.content)
                    if root.get("status") != "success":
                        results.append(MetricResult.failure(device.id, metric_def.name, f"API status: {root.get('status')}"))
                        continue

                    parsed = parse_value(root, metric_def.parser, device.id, metric_def.name)
                    results.extend(parsed)
                except Exception as e:
                    results.append(MetricResult.failure(device.id, metric_def.name, str(e)))
    except Exception as e:
        for metric_def in metrics:
            results.append(MetricResult.failure(device.id, metric_def.name, f"Connection failed: {e}"))
    return results


async def _collect_report_batch(device, metrics) -> list[MetricResult]:
    """Collect Report API metrics (ACC data) using a single HTTPS connection."""
    from app.collectors.registry import collector_registry
    collector = collector_registry.get("panos_report")
    if not collector:
        return [MetricResult.failure(device.id, m.name, "panos_report collector not found") for m in metrics]
    results = []
    for metric_def in metrics:
        try:
            batch = await collector.collect(device, metric_def)
            results.extend(batch)
        except Exception as e:
            results.append(MetricResult.failure(device.id, metric_def.name, str(e)))
    return results


async def _collect_ssh_batch(device, metrics) -> list[MetricResult]:
    """Collect multiple SSH metrics using a single SSH session."""
    results = []
    try:
        output_map = await asyncio.to_thread(_ssh_execute_batch, device, metrics)
        for metric_def in metrics:
            output = output_map.get(metric_def.name)
            if output is None:
                results.append(MetricResult.failure(device.id, metric_def.name, "No output"))
                continue
            try:
                parsed = parse_value_text(output, metric_def.parser, device.id, metric_def.name)
                results.extend(parsed)
            except Exception as e:
                results.append(MetricResult.failure(device.id, metric_def.name, str(e)))
    except Exception as e:
        for metric_def in metrics:
            results.append(MetricResult.failure(device.id, metric_def.name, f"SSH failed: {e}"))
    return results


def _ssh_execute_batch(device, metrics) -> dict[str, str]:
    """Execute multiple commands over a single SSH session. Returns {metric_name: output}."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    output_map = {}
    try:
        client.connect(
            hostname=device.hostname,
            username=device.ssh_username,
            password=device.ssh_password_decrypted,
            timeout=30,
            look_for_keys=False,
            allow_agent=False,
        )
        channel = client.invoke_shell()
        time.sleep(1)
        channel.recv(65535)

        channel.send("set cli pager off\n")
        time.sleep(1)
        channel.recv(65535)

        for metric_def in metrics:
            channel.send(f"{metric_def.command}\n")
            time.sleep(4)

            output = b""
            deadline = time.time() + 8
            while time.time() < deadline:
                if channel.recv_ready():
                    output += channel.recv(65535)
                else:
                    time.sleep(0.3)
                    if not channel.recv_ready():
                        break

            output_map[metric_def.name] = output.decode("utf-8", errors="ignore")

    finally:
        client.close()

    return output_map


@celery_app.task(name="tasks.collect_metric")
def collect_metric(device_id: str, metric_name: str):
    """Legacy single-metric task — kept for backward compatibility."""
    asyncio.run(_collect_device(device_id))


@celery_app.task(name="tasks.sync_device_info")
def sync_device_info(device_id: str):
    """Fetch system info from device and update model/serial/version/HA fields."""
    asyncio.run(_sync_device_info(device_id))


async def _sync_device_info(device_id: str):
    from sqlalchemy import select
    from app.models.device import Device
    from lxml import etree

    async with _get_session() as session:
        device = (await session.execute(
            select(Device).where(Device.id == device_id)
        )).scalar_one_or_none()
        if not device or not device.api_key_encrypted:
            return

        try:
            url = f"https://{device.hostname}/api/"
            async with httpx.AsyncClient(verify=False, timeout=15) as client:
                resp = await client.get(url, params={
                    "type": "op",
                    "cmd": "<show><system><info></info></system></show>",
                    "key": device.api_key_decrypted,
                })
                root = etree.fromstring(resp.content)
                if root.get("status") == "success":
                    sys_el = root.find(".//system")
                    if sys_el is not None:
                        model = sys_el.findtext("model")
                        serial = sys_el.findtext("serial")
                        version = sys_el.findtext("sw-version")
                        if model:
                            device.model = model
                        if serial:
                            device.serial = serial
                        if version:
                            device.panos_version = version

                resp = await client.get(url, params={
                    "type": "op",
                    "cmd": "<show><high-availability><all></all></high-availability></show>",
                    "key": device.api_key_decrypted,
                })
                root = etree.fromstring(resp.content)
                if root.get("status") == "success":
                    state_el = root.find(".//group/local-info/state")
                    if state_el is not None and state_el.text:
                        device.ha_state = state_el.text
                    else:
                        device.ha_state = "standalone"

            await session.commit()
        except Exception:
            pass


@celery_app.task(name="tasks.schedule_collections")
def schedule_collections():
    """Periodic task to dispatch per-device collection tasks."""
    asyncio.run(_schedule_collections())


async def _schedule_collections():
    from sqlalchemy import select
    from app.models.device import Device

    async with _get_session() as session:
        devices = (await session.execute(
            select(Device).where(Device.collect_enabled == True)
        )).scalars().all()

    for device in devices:
        if not device.model or not device.panos_version:
            sync_device_info.delay(device.id)
        collect_device.delay(device.id)
