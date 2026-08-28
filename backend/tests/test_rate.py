"""app/metrics/rate.py —— 计数器→速率的读时差分配置与 SQL。

`counter_rate_config` 是纯函数，直接测。`counter_rate_source` 只产出 SQL 字符串，
这里只钉住几处与已知坑对应的片段（asyncpg 不能绑 INTERVAL、分区必须带 device_id、
负差分要丢弃）；SQL 真正跑对没跑对属于第二批的集成测试。
"""

import pytest

from app.metrics.rate import (
    MAX_RATE_LOOKBACK,
    counter_rate_config,
    counter_rate_source,
)


class Enum:
    """SQLAlchemy 的 enum 列读出来是带 .value 的对象，不是裸字符串。"""

    def __init__(self, value):
        self.value = value


class Definition:
    def __init__(self, data_type="gauge", parser=None, interval=60):
        self.data_type = data_type
        self.parser = parser
        self.interval = interval


# --- counter_rate_config ------------------------------------------------------

def test_missing_definition_is_not_a_counter():
    assert counter_rate_config(None) == (False, 1.0, MAX_RATE_LOOKBACK)


def test_gauge_is_not_differenced():
    assert counter_rate_config(Definition("gauge")) == (False, 1.0, MAX_RATE_LOOKBACK)


def test_counter_reads_scale_from_parser_json():
    """scale 塞在 parser JSON 里，因为建库用 create_all，加不了新列。"""
    d = Definition(data_type="counter", parser={"rate": {"scale": 0.008}}, interval=60)
    assert counter_rate_config(d) == (True, 0.008, 120)


def test_enum_data_type_is_unwrapped():
    d = Definition(data_type=Enum("counter"), parser={"rate": {"scale": 0.008}})
    is_counter, scale, _ = counter_rate_config(d)
    assert (is_counter, scale) == (True, 0.008)


def test_lookback_is_two_intervals():
    _, _, lookback = counter_rate_config(Definition("counter", interval=300))
    assert lookback == 600


def test_lookback_is_clamped_to_one_hour():
    """采集间隔调大后 lookback 不能跟着无限膨胀，否则每次查询都拖一小时以上的数据。"""
    _, _, lookback = counter_rate_config(Definition("counter", interval=3600))
    assert lookback == MAX_RATE_LOOKBACK == 3600


def test_missing_scale_defaults_to_one():
    for parser in (None, {}, {"rate": {}}):
        _, scale, _ = counter_rate_config(Definition("counter", parser=parser))
        assert scale == 1.0


def test_missing_interval_falls_back_to_sixty():
    _, _, lookback = counter_rate_config(Definition("counter", interval=None))
    assert lookback == 120


# --- counter_rate_source ------------------------------------------------------

def sql(lookback=120, scale=0.008):
    return counter_rate_source("device_id = :device_id", "TRUE", lookback, scale)


def test_interval_is_inlined_not_bound():
    """asyncpg 不支持 INTERVAL 参数绑定，所以 lookback 必须内联进 SQL。"""
    assert "INTERVAL '120 seconds'" in sql(lookback=120)


def test_lookback_is_coerced_to_int():
    """内联意味着这个值直接进 SQL 文本，非整数必须炸而不是拼进去。"""
    with pytest.raises(ValueError):
        sql(lookback="120; DROP TABLE metric_data")


def test_partition_covers_device_and_instance():
    """少任何一维都会拿两个不相关的计数器相减（不同设备、不同接口各有自己的计数器）。"""
    assert "PARTITION BY device_id, mn" in sql()


def test_counter_rollback_points_are_dropped():
    """负差分说明设备重启或计数器回绕，丢点，不编造尖峰也不产生负速率。"""
    assert "value >= prev_value" in sql()


def test_lookback_window_reaches_before_start():
    """首个样本需要它**之前**的那个点，否则每次改时间范围都丢掉打头的样本。"""
    body = sql(lookback=120)
    assert "CAST(:start AS timestamptz)" in body and "- INTERVAL '120 seconds'" in body
