from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from app.alerts.notifiers.base import BaseNotifier, AlertMessage, SendResult


class EmailNotifier(BaseNotifier):
    async def send(self, channel_config: dict, alert: AlertMessage) -> SendResult:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[{alert.severity.upper()}] {alert.title} - {alert.device_name}"
            msg["From"] = channel_config.get("from", channel_config.get("username", ""))
            msg["To"] = ", ".join(channel_config.get("recipients", []))

            html = f"""
            <html>
            <body>
                <h2 style="color: {'red' if alert.severity == 'critical' else 'orange'}">{alert.title}</h2>
                <table>
                    <tr><td><b>设备:</b></td><td>{alert.device_name}</td></tr>
                    <tr><td><b>指标:</b></td><td>{alert.metric_name}</td></tr>
                    <tr><td><b>级别:</b></td><td>{alert.severity}</td></tr>
                    <tr><td><b>当前值:</b></td><td>{alert.value or 'N/A'}</td></tr>
                    <tr><td><b>时间:</b></td><td>{alert.timestamp or 'N/A'}</td></tr>
                </table>
                <p>{alert.message}</p>
            </body>
            </html>
            """
            msg.attach(MIMEText(html, "html"))

            await aiosmtplib.send(
                msg,
                hostname=channel_config["smtp_host"],
                port=channel_config.get("smtp_port", 465),
                username=channel_config.get("username"),
                password=channel_config.get("password"),
                use_tls=channel_config.get("use_ssl", True),
            )
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=f"邮件发送失败: {e}")

    async def test(self, channel_config: dict) -> SendResult:
        test_alert = AlertMessage(
            title="测试通知",
            device_name="Test Device",
            metric_name="test_metric",
            severity="info",
            message="这是一条测试邮件，确认邮件通知配置正确。",
            value="0",
        )
        return await self.send(channel_config, test_alert)
