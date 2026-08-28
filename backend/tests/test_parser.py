"""app/metrics/parser.py 的解析行为。

第一批测试选这里：这个模块全是纯函数（XML / 文本进，MetricResult 出），不需要
设备、数据库或网络。用到的 parser 配置全部照抄 app/metrics/builtin.yaml，不自己
编——内置指标的解析规则被改坏时这里要红。

cpu_usage 那一节里带 REAL_ 前缀的输入是 PA-440 上抓的真实采样，配的期望值有同时刻
进程列表 %CPU 之和做参照。这个指标已经被改错过两次（只读 `us`、`100 - id`），两次
都是自造样本看着合理、真机上错得离谱，所以那两条不要改成手编的数字。
"""

from lxml import etree

from app.metrics.parser import parse_value, parse_value_text

DEV = "dev-1"


# --- builtin.yaml 里的真实 parser 配置 ----------------------------------------

CPU_USAGE = {
    "type": "regex_cdata_fields",
    "pattern": r"%Cpu\(s\):(.*)",
    "field_pattern": r"([\d.]+)\s+(\w+)",
    "exclude": ["id"],
    "range": [0, 100],
}
MEMORY_USAGE = {
    "type": "regex_cdata",
    "pattern": r"[KMG]iB Mem\s*:\s*([\d.]+)\s+total.*?([\d.]+)\s+used",
    "calc": "value1 / value0 * 100",
    "range": [0, 100],
}
SESSION_COUNT = {"type": "xpath", "expr": ".//num-active", "on_multiple": "sum"}
SESSION_MAX = {"type": "xpath", "expr": ".//num-max"}
THROUGHPUT_IN = {
    "type": "xpath_multi",
    "entries_expr": ".//ifnet/ifnet/entry",
    "value_expr": "ibytes/text()",
    "label_expr": "name/text()",
}
TEMPERATURE = {
    "type": "regex_multi",
    "pattern": r"(?m)^\s*(\S+)\s+.+?\s+(?:True|False)\s+([\d.]+)",
}


# --- 响应外壳 ------------------------------------------------------------------

def xml(text: str) -> etree._Element:
    return etree.fromstring(text.encode())


def system_resources(
    cpu_line: str = "%Cpu(s):  5.9 us,  2.0 sy,  0.0 ni, 91.8 id,  0.0 wa",
    mem_line: str = "MiB Mem :  15725.1 total,   3200.0 free,   7028.8 used,   5496.3 buff/cache",
) -> etree._Element:
    """`show system resources` —— top 的输出裹在 CDATA 里。"""
    return xml(
        '<response status="success"><result><![CDATA['
        "top - 10:24:41 up 5 days,  2:17,  0 users,  load average: 0.55, 0.61, 0.63\n"
        "Tasks: 132 total,   1 running, 131 sleeping,   0 stopped,   0 zombie\n"
        f"{cpu_line}\n{mem_line}\n"
        "]]></result></response>"
    )


def session_info(body: str) -> etree._Element:
    return xml(f'<response status="success"><result>{body}</result></response>')


def interface_counters(entries: str) -> etree._Element:
    return xml(
        f'<response status="success"><result><ifnet><ifnet>{entries}'
        "</ifnet></ifnet></result></response>"
    )


def one(results):
    """单值解析器约定只返回一条结果。"""
    assert len(results) == 1
    return results[0]


# --- regex_cdata_fields: cpu_usage -------------------------------------------
#
# 下面两条 REAL_* 是 PA-440 上抓到的真实输出，同时抓到的进程列表 %CPU 之和写在
# 各自注释里，作为「这个数对不对」的独立参照。别改这两行的数字。

REAL_IDLEISH = "%Cpu(s): 17.7 us,  2.9 sy,  0.0 ni, 17.6 id,  0.0 wa,  1.5 hi,  0.0 si,  0.0 st"
REAL_BUSY = "%Cpu(s): 74.9 us,  8.7 sy,  2.9 ni,  0.0 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st"


def test_cpu_usage_parses_top_output():
    r = one(parse_value(system_resources(), CPU_USAGE, DEV, "cpu_usage"))
    assert r.success and r.value == 7.9  # 5.9 us + 2.0 sy


def test_cpu_usage_counts_everything_that_is_not_idle():
    """`us` 只是那行八个字段里的一个。

    45 us + 30 sy + 5 ni 的设备真实占用 80%，只读 `us` 报 45%。
    """
    r = one(parse_value(
        system_resources("%Cpu(s): 45.0 us, 30.0 sy,  5.0 ni, 20.0 id,  0.0 wa"),
        CPU_USAGE, DEV, "cpu_usage",
    ))
    assert r.value == 80.0


def test_cpu_usage_matches_the_process_list_on_a_quiet_device():
    """真机采样，同时刻进程列表 %CPU 之和 = 18.6。

    17.7+2.9+0+0+1.5 = 22.1，量级对得上。同一条采样上 `100 - id` 给的是 82.4 ——
    进程只用了 18.6% 的机器不可能忙到 82%，这就是 `id` 不能信的证据。
    """
    r = one(parse_value(system_resources(REAL_IDLEISH), CPU_USAGE, DEV, "cpu_usage"))
    assert r.value == 22.1


def test_cpu_usage_matches_the_process_list_on_a_busy_device():
    """真机采样，同时刻进程列表 %CPU 之和 = 81.1。

    74.9+8.7+2.9 = 86.5。这条上 `id` 是 0.0，`100 - id` 会报 100%（满格），
    而 `us` 单独看是 74.9 —— 差 11.6 个点，正好跨过 80 的告警阈值。
    """
    r = one(parse_value(system_resources(REAL_BUSY), CPU_USAGE, DEV, "cpu_usage"))
    assert r.value == 86.5


def test_cpu_usage_counts_a_field_top_did_not_used_to_print():
    """按字段名抓、不按捕获组位置抓，就是为了这个。

    top 版本之间字段会增减（gnice、st）。位置固定的写法遇到新字段会安静地漏掉它，
    这也是当初否掉"把忙的字段加起来"的理由；按名字抓之后这个理由不成立了。
    """
    r = one(parse_value(
        system_resources("%Cpu(s): 40.0 us,  5.0 sy,  0.0 ni, 50.0 id,  0.0 wa,  3.0 gnice"),
        CPU_USAGE, DEV, "cpu_usage",
    ))
    assert r.value == 48.0


def test_cpu_usage_accepts_a_field_without_a_decimal_point():
    """真机上出现过 `31 us`（无小数）—— top 单次迭代的量化产物。"""
    r = one(parse_value(
        system_resources("%Cpu(s): 31 us,  2.9 sy,  0.0 ni, 19.1 id,  0.0 wa"),
        CPU_USAGE, DEV, "cpu_usage",
    ))
    assert r.value == 33.9


def test_cpu_usage_out_of_range_is_rejected():
    """这条线上采到过 105.8 和 118.4。不管用哪个公式，有些采样就是不可能的值，
    必须失败而不是落库 —— 存成 gauge 之后它永远看着像真的，还会喂给阈值告警。
    """
    r = one(parse_value(
        system_resources("%Cpu(s): 112.3 us,  2.0 sy,  0.0 ni, 250.0 id"),
        CPU_USAGE, DEV, "cpu_usage",
    ))
    assert not r.success and "outside declared range" in r.error


def test_pattern_without_capture_group_falls_back_to_whole_match():
    """捕获组的作用是把字段搜索限定在一行内（否则 Mem 行的 `15725.1 total` 也会
    被抓进来）。没写捕获组时退回整个匹配，而不是抛 IndexError。"""
    cfg = {**CPU_USAGE, "pattern": r"%Cpu\(s\).*"}
    r = one(parse_value(system_resources(), cfg, DEV, "cpu_usage"))
    assert r.value == 7.9  # 只有那一行，没混进 15725.1


def test_excluded_field_missing_is_a_failure():
    """要排除的字段不在行上，说明配置写错了或者输出格式变了。

    不查的话，本该被减掉的那个字段会直接被算成负载 —— 一个看着合理的高估。
    """
    cfg = {**CPU_USAGE, "exclude": ["idle"]}
    r = one(parse_value(system_resources(), cfg, DEV, "cpu_usage"))
    assert not r.success
    assert "not on the line" in r.error and "idle" in r.error


def test_field_pattern_matching_nothing_is_a_failure():
    cfg = {**CPU_USAGE, "field_pattern": r"([\d.]+)\s+(%%%\w+)"}
    r = one(parse_value(system_resources(), cfg, DEV, "cpu_usage"))
    assert not r.success and "matched no fields" in r.error


def test_regex_cdata_fields_no_match_is_a_failure():
    r = one(parse_value(
        system_resources("CPU: idle"), CPU_USAGE, DEV, "cpu_usage"
    ))
    assert not r.success and "no match" in r.error


def test_regex_cdata_fields_keeps_first_of_several_matches():
    """和 regex_cdata 一样用 re.search，没有 _reduce_matches 的多值保护。

    钉住当前行为：`show system resources` 是管理面的 top，实测只有一行 %Cpu(s)。
    """
    r = one(parse_value(
        system_resources("%Cpu(s):  5.9 us,  2.0 sy, 91.8 id\n"
                         "%Cpu(s): 88.8 us,  1.0 sy, 11.2 id"),
        CPU_USAGE, DEV, "cpu_usage",
    ))
    assert r.value == 7.9


# --- regex_cdata + calc -------------------------------------------------------
#
# calc 仍然由 memory_usage 在用（见下一节），这里测它的白名单行为。

def test_regex_cdata_no_match_is_a_failure():
    cfg = {"type": "regex_cdata", "pattern": r"%Cpu\(s\):.*?([\d.]+)\s+id"}
    r = one(parse_value(system_resources("CPU: idle"), cfg, DEV, "cpu_usage"))
    assert not r.success and "no match" in r.error


def test_unknown_calc_is_a_failure():
    """calc 是白名单。写错的表达式必须报错，不能退回"取第一个捕获组"——那会得到
    一个看着合理的错数字（旧实现就是这样）。"""
    cfg = {**MEMORY_USAGE, "calc": "value0 * 2"}
    r = one(parse_value(system_resources(), cfg, DEV, "memory_usage"))
    assert not r.success and "unknown calc 'value0 * 2'" in r.error


def test_calc_needing_more_groups_than_pattern_has_fails():
    cfg = {"type": "regex_cdata", "pattern": r"%Cpu\(s\):.*?([\d.]+)\s+id",
           "calc": "value1 / value0 * 100"}
    r = one(parse_value(system_resources(), cfg, DEV, "cpu_usage"))
    assert not r.success and "more capture groups" in r.error


def test_regex_cdata_non_numeric_capture_is_a_failure():
    cfg = {"type": "regex_cdata", "pattern": r"load average: (\S+),"}
    r = one(parse_value(
        xml('<response><result><![CDATA[load average: n/a, 0.61]]></result></response>'),
        cfg, DEV, "load",
    ))
    assert not r.success and "Cannot parse values" in r.error


# --- regex_cdata + calc: memory_usage ----------------------------------------

def test_memory_usage_is_used_over_total():
    r = one(parse_value(system_resources(), MEMORY_USAGE, DEV, "memory_usage"))
    assert r.value == 44.7  # 7028.8 / 15725.1 * 100


def test_memory_usage_ignores_unit_prefix():
    """PAN-OS 的单位随内存大小变（KiB/MiB/GiB），比值与单位无关。"""
    r = one(parse_value(
        system_resources(mem_line="GiB Mem :  15.4 total,   3.1 free,    6.9 used"),
        MEMORY_USAGE, DEV, "memory_usage",
    ))
    assert r.value == 44.81


def test_memory_usage_zero_total_does_not_raise():
    r = one(parse_value(
        system_resources(mem_line="MiB Mem :  0.0 total,   0.0 free,    0.0 used"),
        MEMORY_USAGE, DEV, "memory_usage",
    ))
    assert r.success and r.value == 0.0


def test_memory_usage_ratio_outside_range_is_rejected():
    """used 大于 total 说明 pattern 挑错了两个数字。"""
    r = one(parse_value(
        system_resources(mem_line="MiB Mem :  100.0 total,   0.0 free,   250.0 used"),
        MEMORY_USAGE, DEV, "memory_usage",
    ))
    assert not r.success and "outside declared range" in r.error


# --- xpath: session_count -----------------------------------------------------

def test_xpath_reads_single_node():
    r = one(parse_value(
        session_info("<num-active>1234</num-active>"), SESSION_COUNT, DEV, "session_count"
    ))
    assert r.value == 1234.0


def test_xpath_strips_thousands_separator_and_units():
    r = one(parse_value(
        session_info("<num-active>1,234</num-active>"), SESSION_COUNT, DEV, "session_count"
    ))
    assert r.value == 1234.0


def two_dataplanes(field: str, a: str, b: str) -> etree._Element:
    """PA-5500 / PA-7000 按 DP 各报一份 `show session info`。"""
    return session_info(f"<dp><{field}>{a}</{field}></dp><dp><{field}>{b}</{field}></dp>")


def test_xpath_multiple_matches_fail_loudly_without_on_multiple():
    """没声明 on_multiple 时必须失败，不能只留第一个 DP —— 那会得到一个看着合理、
    实际少算一个数量级的数字。

    session_max 是 builtin.yaml 里唯一故意不声明的（sum 还是 first 取决于设备到底
    报的是每 DP 容量还是系统总量，猜错会把容量放大 DP 倍），所以拿它来测这条路径。
    """
    r = one(parse_value(
        two_dataplanes("num-max", "262142", "262142"), SESSION_MAX, DEV, "session_max"
    ))
    assert not r.success
    assert "matched 2 values" in r.error and "on_multiple" in r.error


def test_session_count_sums_dataplanes():
    """builtin.yaml 里 session_count 声明了 sum：活跃会话数在 DP 之间是可加的。"""
    r = one(parse_value(
        two_dataplanes("num-active", "100", "200"), SESSION_COUNT, DEV, "session_count"
    ))
    assert r.value == 300.0


def test_xpath_on_multiple_max_takes_worst_dataplane():
    cfg = {**SESSION_MAX, "on_multiple": "max"}
    r = one(parse_value(
        two_dataplanes("num-max", "100", "200"), cfg, DEV, "session_max"
    ))
    assert r.value == 200.0


def test_xpath_unknown_on_multiple_is_a_failure():
    cfg = {**SESSION_MAX, "on_multiple": "median"}
    r = one(parse_value(
        two_dataplanes("num-max", "100", "200"), cfg, DEV, "session_max"
    ))
    assert not r.success and "unknown on_multiple 'median'" in r.error


def test_range_is_enforced_on_other_parser_types_too():
    """range 在分发层统一生效，不是 regex_cdata 专属——管理员在 Web UI 上配的
    xpath 百分比指标也该受保护。"""
    cfg = {"type": "xpath", "expr": ".//util", "range": [0, 100]}
    r = one(parse_value(session_info("<util>140</util>"), cfg, DEV, "util"))
    assert not r.success and "outside declared range" in r.error


def test_xpath_no_match_is_a_failure():
    r = one(parse_value(session_info("<cps>45</cps>"), SESSION_COUNT, DEV, "session_count"))
    assert not r.success and "returned nothing" in r.error


def test_xpath_non_numeric_content_is_a_failure():
    r = one(parse_value(
        session_info("<num-active>n/a</num-active>"), SESSION_COUNT, DEV, "session_count"
    ))
    assert not r.success and "Cannot parse value" in r.error


def test_xpath_accepts_scalar_expression():
    """count() 之类返回的是标量而不是节点列表。"""
    cfg = {"type": "xpath", "expr": "count(.//dp)"}
    r = one(parse_value(
        session_info("<dp/><dp/><dp/>"), cfg, DEV, "dp_count"
    ))
    assert r.value == 3.0


def test_xpath_scalar_zero_is_reported_as_no_match():
    """`not 0.0` 为真，所以合法的"数出来是 0"被当成采集失败。

    钉住当前行为：真要用 count() 做指标得先改这个判空。
    """
    cfg = {"type": "xpath", "expr": "count(.//dp)"}
    r = one(parse_value(session_info("<cps>45</cps>"), cfg, DEV, "dp_count"))
    assert not r.success and "returned nothing" in r.error


# --- xpath_multi: interface_throughput ---------------------------------------

def test_xpath_multi_yields_one_point_per_interface():
    results = parse_value(
        interface_counters(
            "<entry><name>ethernet1/1</name><ibytes>1000</ibytes></entry>"
            "<entry><name>ethernet1/2</name><ibytes>3000</ibytes></entry>"
        ),
        THROUGHPUT_IN, DEV, "interface_throughput_in",
    )
    assert [(r.labels["instance"], r.value) for r in results] == [
        ("ethernet1/1", 1000.0),
        ("ethernet1/2", 3000.0),
    ]


def test_xpath_multi_accepts_element_expr_as_well_as_text():
    """builtin.yaml 用 `ibytes/text()`，Web UI 上手配的指标常写成 `ibytes`。"""
    cfg = {**THROUGHPUT_IN, "value_expr": "ibytes", "label_expr": "name"}
    results = parse_value(
        interface_counters("<entry><name>ethernet1/1</name><ibytes>1000</ibytes></entry>"),
        cfg, DEV, "interface_throughput_in",
    )
    assert [(r.labels["instance"], r.value) for r in results] == [("ethernet1/1", 1000.0)]


def test_xpath_multi_skips_entries_without_value():
    results = parse_value(
        interface_counters(
            "<entry><name>ethernet1/1</name></entry>"
            "<entry><name>ethernet1/2</name><ibytes>3000</ibytes></entry>"
        ),
        THROUGHPUT_IN, DEV, "interface_throughput_in",
    )
    assert [r.labels["instance"] for r in results] == ["ethernet1/2"]


def test_xpath_multi_skips_non_numeric_value():
    results = parse_value(
        interface_counters("<entry><name>ethernet1/1</name><ibytes>n/a</ibytes></entry>"),
        THROUGHPUT_IN, DEV, "interface_throughput_in",
    )
    assert results == []


def test_xpath_multi_labels_missing_name_as_unknown():
    results = parse_value(
        interface_counters("<entry><ibytes>1000</ibytes></entry>"),
        THROUGHPUT_IN, DEV, "interface_throughput_in",
    )
    assert results[0].labels["instance"] == "unknown"


# --- 文本解析器（SSH 输出）-----------------------------------------------------

# builtin.yaml 目前没有 type: regex 的指标，但多 DP 的归并逻辑住在这条路径上
# （parser.py 里 `show running resource-monitor` 那段注释），所以照它的形状测。
DP_LOAD = {"type": "regex", "pattern": r"CPU load\s+:\s+(\d+)"}


def test_regex_reads_single_match():
    r = one(parse_value_text("DP dp0:\nCPU load : 42\n", DP_LOAD, DEV, "dp_cpu"))
    assert r.value == 42.0


def test_regex_multiple_dataplanes_fail_loudly_without_on_multiple():
    r = one(parse_value_text(
        "DP dp0:\nCPU load : 42\nDP dp1:\nCPU load : 77\n", DP_LOAD, DEV, "dp_cpu"
    ))
    assert not r.success and "matched 2 values" in r.error


def test_regex_on_multiple_max_takes_worst_dataplane():
    cfg = {**DP_LOAD, "on_multiple": "max"}
    r = one(parse_value_text(
        "DP dp0:\nCPU load : 42\nDP dp1:\nCPU load : 77\n", cfg, DEV, "dp_cpu"
    ))
    assert r.value == 77.0


def test_regex_no_match_is_a_failure():
    r = one(parse_value_text("DP dp0:\n", DP_LOAD, DEV, "dp_cpu"))
    assert not r.success and "no match" in r.error


ENVIRONMENTALS = """Thermal
Slot  Description                     Alarm  Degrees C  Minimum  Maximum
S1    Temperature @ Ambient           False  32.5       5.0      45.0
S2    Temperature @ Core              False  48.0       5.0      90.0
"""


def test_regex_multi_labels_each_sensor():
    results = parse_value_text(ENVIRONMENTALS, TEMPERATURE, DEV, "temperature")
    assert [(r.labels["instance"], r.value) for r in results] == [
        ("S1", 32.5),
        ("S2", 48.0),
    ]


def test_regex_multi_single_group_labels_default():
    cfg = {"type": "regex_multi", "pattern": r"CPU load\s+:\s+(\d+)"}
    results = parse_value_text("CPU load : 42\n", cfg, DEV, "dp_cpu")
    assert [(r.labels["instance"], r.value) for r in results] == [("default", 42.0)]


def test_regex_multi_skips_non_numeric():
    cfg = {"type": "regex_multi", "pattern": r"(\S+)\s+=\s+(\S+)"}
    results = parse_value_text("a = 1\nb = n/a\n", cfg, DEV, "x")
    assert [(r.labels["instance"], r.value) for r in results] == [("a", 1.0)]


# --- 分发 ---------------------------------------------------------------------

def test_unknown_xml_parser_type_is_a_failure():
    r = one(parse_value(session_info("<x/>"), {"type": "jsonpath"}, DEV, "x"))
    assert not r.success and "Unknown parser type: jsonpath" in r.error


def test_unknown_text_parser_type_is_a_failure():
    r = one(parse_value_text("x", {"type": "jsonpath"}, DEV, "x"))
    assert not r.success and "Unknown text parser type: jsonpath" in r.error
