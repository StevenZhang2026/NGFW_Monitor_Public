"""
LLM-based intent parsing: natural language → structured API call.
"""

import json
import httpx

SYSTEM_PROMPT = """你是 NGFW Monitor 防火墙监控系统的 AI 助手。根据用户的自然语言问题，生成对应的 API 查询参数。

可用的查询能力：
1. acc_ranking - 应用/威胁排名
   参数: metric_name (acc_application|acc_threat), days (天数), limit (数量), severity (可选,逗号分隔: critical,high,medium,low)
2. acc_trend - 应用/威胁趋势
   参数: metric_name (acc_application|acc_threat), days (天数), top_n (数量)
3. metric_data - 设备指标数据(CPU、内存、会话数等)
   参数: metric_name (cpu_usage|memory_usage|session_count|session_kbps|session_cps|packet_buffer|packet_descriptor|interface_throughput_in|interface_throughput_out|temperature), days (天数)
   注意: 整机吞吐量用 session_kbps；interface_throughput_in/out 是单接口速率，只在问某个接口时用
4. alert_events - 告警事件
   参数: severity (可选: critical|warning|info), status (可选: firing|acknowledged), days (天数)
5. device_status - 设备状态概览
   参数: 无

你必须以 JSON 格式回复，包含以下字段：
- action: 上述查询能力之一
- params: 对应的参数对象
- summary_request: 用一句话描述用户想知道什么（用于格式化输出时参考）

示例：
用户: "最近3天威胁top 10"
回复: {"action": "acc_ranking", "params": {"metric_name": "acc_threat", "days": 3, "limit": 10}, "summary_request": "最近3天的威胁排名前10"}

用户: "这周CPU使用率怎么样"
回复: {"action": "metric_data", "params": {"metric_name": "cpu_usage", "days": 7}, "summary_request": "本周CPU使用率趋势"}

用户: "有没有严重告警"
回复: {"action": "alert_events", "params": {"severity": "critical", "days": 7}, "summary_request": "最近的严重级别告警"}

只返回 JSON，不要附加其他文字。"""


class IntentError(Exception):
    pass


async def parse_intent(message: str, api_base: str, api_key: str, model: str) -> dict:
    """Parse user message into structured intent. Raises IntentError on failure."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        "temperature": 0,
        "max_tokens": 500,
    }

    url = f"{api_base.rstrip('/')}/chat/completions"
    try:
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.ConnectError as e:
        raise IntentError(f"无法连接模型服务: {e}")
    except httpx.TimeoutException:
        raise IntentError("模型服务请求超时（30s）")
    except Exception as e:
        raise IntentError(f"网络错误: {e}")

    if resp.status_code != 200:
        detail = resp.text[:200] if resp.text else str(resp.status_code)
        raise IntentError(f"模型 API 返回错误 ({resp.status_code}): {detail}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise IntentError(f"模型返回格式异常: {e}")
