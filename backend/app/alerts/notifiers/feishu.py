import httpx

from app.alerts.notifiers.base import BaseNotifier, AlertMessage

SEVERITY_COLORS = {
    "critical": "red",
    "warning": "orange",
    "info": "blue",
}


class FeishuNotifier(BaseNotifier):
    async def send(self, channel_config: dict, alert: AlertMessage) -> bool:
        webhook_url = channel_config.get("webhook_url")
        if not webhook_url:
            return False

        color = SEVERITY_COLORS.get(alert.severity, "blue")
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"🚨 {alert.title}"},
                    "template": color,
                },
                "elements": [
                    {
                        "tag": "div",
                        "fields": [
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**设备:** {alert.device_name}"}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**指标:** {alert.metric_name}"}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**级别:** {alert.severity}"}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**当前值:** {alert.value or 'N/A'}"}},
                        ],
                    },
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": alert.message},
                    },
                ],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json=card)
                return response.status_code == 200
        except Exception:
            return False

    async def test(self, channel_config: dict) -> bool:
        test_alert = AlertMessage(
            title="测试通知",
            device_name="Test Device",
            metric_name="test_metric",
            severity="info",
            message="这是一条测试消息，确认通知渠道配置正确。",
            value="0",
        )
        return await self.send(channel_config, test_alert)
