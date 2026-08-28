"""app/tasks/collect.py::_group_by_command —— 采集前的命令去重。

多个指标共用一条命令（`show session info` 喂 4 个指标），按指标各发一次等于一分钟
里把同一个问题问设备四遍。管理面是稀缺资源，所以问一次再把响应分发出去。
"""

from app.tasks.collect import _group_by_command

SESSION_INFO = "<show><session><info></info></session></show>"
SYSTEM_RESOURCES = "<show><system><resources></resources></system></show>"


class Metric:
    def __init__(self, name, command):
        self.name = name
        self.command = command

    def __repr__(self):
        return f"Metric({self.name})"


def test_metrics_sharing_a_command_are_issued_once():
    metrics = [
        Metric(name, SESSION_INFO)
        for name in ("session_count", "session_max", "session_cps", "session_kbps")
    ]
    grouped = _group_by_command(metrics)
    assert len(grouped) == 1
    command, fanout = grouped[0]
    assert command == SESSION_INFO
    assert [m.name for m in fanout] == [
        "session_count", "session_max", "session_cps", "session_kbps",
    ]


def test_distinct_commands_stay_separate():
    grouped = _group_by_command([
        Metric("session_count", SESSION_INFO),
        Metric("cpu_usage", SYSTEM_RESOURCES),
        Metric("memory_usage", SYSTEM_RESOURCES),
    ])
    assert [(cmd, [m.name for m in ms]) for cmd, ms in grouped] == [
        (SESSION_INFO, ["session_count"]),
        (SYSTEM_RESOURCES, ["cpu_usage", "memory_usage"]),
    ]


def test_command_order_follows_first_appearance():
    grouped = _group_by_command([
        Metric("cpu_usage", SYSTEM_RESOURCES),
        Metric("session_count", SESSION_INFO),
        Metric("memory_usage", SYSTEM_RESOURCES),
    ])
    assert [cmd for cmd, _ in grouped] == [SYSTEM_RESOURCES, SESSION_INFO]


def test_no_metrics_means_no_commands():
    assert _group_by_command([]) == []
