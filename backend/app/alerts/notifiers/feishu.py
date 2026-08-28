import logging

import httpx

from app.alerts.notifiers.base import BaseNotifier, AlertMessage, SendResult
from app.outbound import outbound_verify, tls_error_hint

logger = logging.getLogger(__name__)

SEVERITY_COLORS = {
    "critical": "red",
    "warning": "orange",
    "info": "blue",
}


class FeishuNotifier(BaseNotifier):
    async def send(self, channel_config: dict, alert: AlertMessage) -> SendResult:
        webhook_url = channel_config.get("webhook_url")
        if not webhook_url:
            return SendResult(success=False, error="webhook_url not configured")

        color = SEVERITY_COLORS.get(alert.severity, "blue")
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"🚨 防火墙告警: {alert.title}"},
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
            # webhook_url embeds the bot token — verify the peer.
            async with httpx.AsyncClient(timeout=10, verify=outbound_verify()) as client:
                response = await client.post(webhook_url, json=card)
                data = response.json()
                if data.get("code") != 0:
                    msg = data.get("msg", "unknown error")
                    logger.error("Feishu webhook failed: %s", msg)
                    return SendResult(success=False, error=f"飞书返回错误: {msg}")
                return SendResult(success=True)
        except Exception as e:
            logger.error("Feishu webhook request error: %s", e)
            return SendResult(success=False, error=f"请求失败: {e}{tls_error_hint(e)}")

    async def test(self, channel_config: dict) -> SendResult:
        test_alert = AlertMessage(
            title="测试通知",
            device_name="Test Device",
            metric_name="test_metric",
            severity="info",
            message="这是一条防火墙监控平台的测试消息，确认通知渠道配置正确。",
            value="0",
        )
        return await self.send(channel_config, test_alert)
