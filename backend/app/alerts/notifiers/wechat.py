import httpx

from app.alerts.notifiers.base import BaseNotifier, AlertMessage

SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "🔵",
}


class WechatNotifier(BaseNotifier):
    """企业微信群机器人 Webhook 通知"""

    async def send(self, channel_config: dict, alert: AlertMessage) -> bool:
        webhook_url = channel_config.get("webhook_url")
        if not webhook_url:
            return False

        emoji = SEVERITY_EMOJI.get(alert.severity, "🔵")
        content = (
            f"{emoji} **{alert.title}**\n"
            f"> 设备: {alert.device_name}\n"
            f"> 指标: {alert.metric_name}\n"
            f"> 级别: {alert.severity}\n"
            f"> 当前值: {alert.value or 'N/A'}\n"
            f"> 时间: {alert.timestamp or 'N/A'}\n\n"
            f"{alert.message}"
        )

        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json=payload)
                data = response.json()
                return data.get("errcode") == 0
        except Exception:
            return False

    async def test(self, channel_config: dict) -> bool:
        test_alert = AlertMessage(
            title="测试通知",
            device_name="Test Device",
            metric_name="test_metric",
            severity="info",
            message="这是一条测试消息，确认企业微信通知配置正确。",
            value="0",
        )
        return await self.send(channel_config, test_alert)
