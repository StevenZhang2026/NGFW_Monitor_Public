import asyncio
import time
from contextlib import asynccontextmanager

import httpx
import paramiko
from lxml import etree
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.tasks import celery_app
from app.config import settings
from app.metrics.parser import parse_value, parse_value_text
from app.collectors.base import MetricResult
from app.collectors.panos_report import bucket_marker_name, target_bucket
from app.tasks.locks import device_collect_lock

# Beat fires every 60s, and a metric's newest point is stamped part-way into the
# task, so the measured gap between two consecutive ticks is always a little
# under 60s. Requiring the full interval to have elapsed would make a 60s metric
# collect every *other* tick. Allowing half a tick of slack makes each interval
# land on the nearest tick without drifting long.
SCHEDULE_TOLERANCE = 30

# Floor for the "when was this last collected" lookback. Anything older than the
# window counts as due anyway, so the window only has to comfortably exceed the
# longest configured interval.
MIN_DUE_WINDOW = 3600


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


@celery_app.task(
    name="tasks.collect_device",
    soft_time_limit=settings.collect_soft_time_limit,
    time_limit=settings.collect_time_limit,
)
def collect_device(device_id: str):
    """Collect all due metrics for a device using shared connections.

    Serialised per device: a device still being collected when the next beat
    tick fires is skipped rather than collected twice concurrently. See
    app.tasks.locks for why overlapping collections amplify instead of degrade.
    """
    with device_collect_lock(device_id) as acquired:
        if not acquired:
            return
        asyncio.run(_collect_device(device_id))


async def _due_metrics(session, device_id: str, metrics: list, now) -> list:
    """Keep only the metrics whose interval has elapsed since their last point.

    The admin owns the collection frequency (design constraint 1), so a metric
    set to 300s must be polled at 300s and not at whatever the beat interval
    happens to be. Multi-instance metrics are stored as `<name>::<instance>`,
    so the stored name is split back to its base before matching.
    """
    from datetime import timezone
    from sqlalchemy import text

    if not metrics:
        return []

    longest = max((m.interval or 60) for m in metrics)
    window = max(2 * longest, MIN_DUE_WINDOW)

    # asyncpg cannot bind an INTERVAL, so the window is inlined — it comes from
    # metric definitions, never from user input.
    rows = (await session.execute(
        text(f"""
            SELECT split_part(metric_name, '::', 1) AS base, MAX(timestamp) AS last_ts
            FROM metric_data
            WHERE device_id = :device_id
              AND timestamp > now() - INTERVAL '{int(window)} seconds'
            GROUP BY base
        """),
        {"device_id": device_id},
    )).fetchall()
    last_seen = {r.base: r.last_ts for r in rows}

    due = []
    for m in metrics:
        last = last_seen.get(m.name)
        if last is None:
            # Never collected, or older than the window — either way, collect it.
            due.append(m)
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() >= (m.interval or 60) - SCHEDULE_TOLERANCE:
            due.append(m)
    return due


def _group_by_command(metrics: list) -> list[tuple[str, list]]:
    """Collapse metrics onto the distinct commands that feed them.

    Several metrics routinely parse different fields out of one response —
    session_count / session_max / session_cps / session_kbps all come from
    `show session info`, and cpu_usage / memory_usage both come from
    `show system resources`. Issuing the command once per metric asked the
    firewall the same question four times a minute; the management plane is the
    scarce resource here, so ask once and fan the response out.
    """
    grouped: dict[str, list] = {}
    for m in metrics:
        grouped.setdefault(m.command, []).append(m)
    return list(grouped.items())


async def _collect_device(device_id: str):
    from datetime import datetime, timezone
    from sqlalchemy import select
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

        now = datetime.now(timezone.utc)
        polled = [m for m in metrics if m.collector in ('panos_api', 'panos_ssh')]
        due = await _due_metrics(session, device_id, polled, now)
        api_metrics = [m for m in due if m.collector == 'panos_api']
        ssh_metrics = [m for m in due if m.collector == 'panos_ssh']
        report_metrics_all = [m for m in metrics if m.collector == 'panos_report']
        report_metrics = []
        for m in report_metrics_all:
            # ACC data points carry the bucket's start time, which always lags
            # now, so "has the interval elapsed since the newest point" would
            # be permanently true. Ask whether *this bucket* is already done.
            # The marker row answers that even for an empty bucket, which would
            # otherwise be re-requested on every beat tick for 15 minutes.
            bucket_start, _ = target_bucket(m)
            already_collected = (await session.execute(
                select(MetricData.timestamp).where(
                    MetricData.device_id == device_id,
                    MetricData.metric_name == bucket_marker_name(m.name),
                    MetricData.timestamp == bucket_start,
                ).limit(1)
            )).scalar()
            if already_collected is None:
                report_metrics.append(m)

        has_success = False
        has_attempt = False

        if api_metrics and device.api_key_encrypted:
            has_attempt = True
            results = await _collect_api_batch(device, _group_by_command(api_metrics))
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
            results = await _collect_ssh_batch(device, _group_by_command(ssh_metrics))
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
            rows = [
                {
                    "timestamp": r.timestamp,
                    "device_id": r.device_id,
                    "metric_name": r.metric_name,
                    "value": r.value,
                    "labels": r.labels or None,
                }
                for r in results if r.success
            ]
            if rows:
                has_success = True
                # Bucket timestamps are deterministic, so a re-run can collide
                # with an existing point. Skip duplicates instead of letting an
                # IntegrityError roll back this device's whole batch.
                await session.execute(
                    pg_insert(MetricData).values(rows).on_conflict_do_nothing()
                )

        if has_success:
            device.status = DeviceStatus.online
            device.last_seen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif has_attempt:
            device.status = DeviceStatus.offline

        await session.commit()


async def _collect_api_batch(device, commands) -> list[MetricResult]:
    """Run each distinct command once over a single HTTPS connection.

    `commands` is [(command, [metric_def, ...])]; every metric in a group is
    parsed out of that command's single response.
    """
    results = []
    all_metrics = [m for _, group in commands for m in group]
    try:
        url = f"https://{device.hostname}/api/"
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            for command, group in commands:
                try:
                    params = {
                        "type": "op",
                        "cmd": command,
                        "key": device.api_key_decrypted,
                    }
                    response = await client.get(url, params=params)
                    response.raise_for_status()

                    root = etree.fromstring(response.content)
                    if root.get("status") != "success":
                        results.extend(
                            MetricResult.failure(
                                device.id, m.name, f"API status: {root.get('status')}")
                            for m in group
                        )
                        continue
                except Exception as e:
                    results.extend(
                        MetricResult.failure(device.id, m.name, str(e)) for m in group
                    )
                    continue

                # One metric's parser blowing up must not cost the others their
                # share of a response that was fetched successfully.
                for metric_def in group:
                    try:
                        results.extend(
                            parse_value(root, metric_def.parser, device.id, metric_def.name)
                        )
                    except Exception as e:
                        results.append(MetricResult.failure(device.id, metric_def.name, str(e)))
    except Exception as e:
        for metric_def in all_metrics:
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


async def _collect_ssh_batch(device, commands) -> list[MetricResult]:
    """Run each distinct command once over a single SSH session.

    `commands` is [(command, [metric_def, ...])]. Deduplication matters more
    here than on the API path: each CLI command costs a fixed 4s settle plus up
    to 8s of draining, so a repeated command is seconds of wall clock, not just
    a request.
    """
    results = []
    all_metrics = [m for _, group in commands for m in group]
    try:
        output_map = await asyncio.to_thread(
            _ssh_execute_batch, device, [command for command, _ in commands]
        )
        for command, group in commands:
            output = output_map.get(command)
            if output is None:
                results.extend(
                    MetricResult.failure(device.id, m.name, "No output") for m in group
                )
                continue
            for metric_def in group:
                try:
                    results.extend(
                        parse_value_text(output, metric_def.parser, device.id, metric_def.name)
                    )
                except Exception as e:
                    results.append(MetricResult.failure(device.id, metric_def.name, str(e)))
    except Exception as e:
        for metric_def in all_metrics:
            results.append(MetricResult.failure(device.id, metric_def.name, f"SSH failed: {e}"))
    return results


def _ssh_execute_batch(device, commands: list[str]) -> dict[str, str]:
    """Execute commands over a single SSH session. Returns {command: output}."""
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

        for command in commands:
            channel.send(f"{command}\n")
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

            output_map[command] = output.decode("utf-8", errors="ignore")

    finally:
        client.close()

    return output_map


@celery_app.task(name="tasks.collect_metric")
def collect_metric(device_id: str, metric_name: str):
    """Legacy single-metric task — kept for backward compatibility.

    Delegates to collect_device so it goes through the per-device lock instead
    of opening a second concurrent connection to the same firewall.
    """
    collect_device(device_id)


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
        # A task still sitting in the queue when the next tick dispatches its
        # replacement has nothing left to contribute — running it late would
        # only pile more load onto a device that is evidently already slow.
        collect_device.apply_async(
            args=[device.id], expires=settings.collect_task_expires
        )
