import asyncio
import time

import paramiko

from app.collectors.base import BaseCollector, MetricResult
from app.collectors.registry import register_collector
from app.metrics.parser import parse_value_text


@register_collector
class PanosSshCollector(BaseCollector):
    name = "panos_ssh"

    async def collect(self, device, metric_def) -> list[MetricResult]:
        try:
            output = await asyncio.to_thread(
                self._ssh_execute, device, metric_def.command
            )
            results = parse_value_text(output, metric_def.parser, device.id, metric_def.name)
            return results
        except Exception as e:
            return [MetricResult.failure(device.id, metric_def.name, str(e))]

    def _ssh_execute(self, device, command: str) -> str:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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

            channel.send(f"{command}\n")
            time.sleep(4)
            output = b""
            while channel.recv_ready():
                output += channel.recv(65535)
                time.sleep(0.5)

            return output.decode("utf-8", errors="ignore")
        finally:
            client.close()

    async def test_connection(self, device) -> bool:
        try:
            output = await asyncio.to_thread(
                self._ssh_execute, device, "show system info"
            )
            return "hostname" in output.lower()
        except Exception:
            return False
