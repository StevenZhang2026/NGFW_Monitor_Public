"""builtin.yaml 与 parser.py 之间的约定。

这些不是在测解析逻辑（那在 test_parser.py），是在测**内置指标的配置有没有把话说
全**。配置里的错误在采集时才会暴露，而且多半表现为一个看着合理的错数字或者一条静默
失败；这里让它在 pytest 里就红。
"""

from pathlib import Path

import yaml

from app.metrics.parser import _CALCS, _REDUCERS

BUILTIN = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "app" / "metrics" / "builtin.yaml").read_text()
)

# 走 _reduce_matches（有多值保护）的单值解析器。regex_cdata 不在其中——它用
# re.search 只取第一个匹配，声明 on_multiple 也不会被读，所以不能要求它声明。
REDUCED_TYPES = {"xpath", "regex"}

# 故意不声明 on_multiple 的指标 → 为什么。往这里加条目就是在说"这个指标在多 DP
# 设备上会硬失败，我知道，并且宁可这样"。
ON_MULTIPLE_EXEMPT = {
    "session_max": "每 DP 容量还是系统总量未知；猜 sum 会把容量放大 DP 倍，"
                   "而这个数是会话利用率的分母，错了会掩盖饱和",
    "ha_state": "取的是 active/passive 字符串，float() 本来就过不去，是另一个待修问题",
}


def parsers_of_type(*types):
    return [
        (m["name"], m["parser"]) for m in BUILTIN
        if m["parser"].get("type") in types
    ]


def test_single_value_metrics_declare_on_multiple():
    """PA-5500 / PA-7000 按 DP 各报一份，单值表达式会匹配到多个。

    parser.py 的取舍是"多匹配且没声明归并方式就硬失败"——因为安静地只留第一个 DP
    会给出一个看着合理、实际少算一个数量级的数字。所以每个单值内置指标都得表态：
    声明 on_multiple，或者进 ON_MULTIPLE_EXEMPT 并写清为什么。
    """
    undeclared = [
        name for name, parser in parsers_of_type(*REDUCED_TYPES)
        if "on_multiple" not in parser and name not in ON_MULTIPLE_EXEMPT
    ]
    assert undeclared == [], (
        f"这些单值指标既没声明 on_multiple 也不在豁免名单里：{undeclared}。"
        "sum 用于可加的总量（会话数、cps、吞吐），max 用于饱和度读数（缓冲区、"
        "描述符）；确实无法判断就加进 ON_MULTIPLE_EXEMPT 说明理由。"
    )


def test_declared_reducers_exist():
    unknown = {
        name: parser["on_multiple"]
        for name, parser in parsers_of_type(*REDUCED_TYPES)
        if "on_multiple" in parser and parser["on_multiple"] not in _REDUCERS
    }
    assert unknown == {}, f"未知的 on_multiple：{unknown}，可选 {sorted(_REDUCERS)}"


def test_declared_calcs_exist():
    """calc 是白名单匹配。写错的表达式在采集时才会失败，这里提前红。"""
    unknown = {
        m["name"]: m["parser"]["calc"] for m in BUILTIN
        if m["parser"].get("calc") and m["parser"]["calc"] not in _CALCS
    }
    assert unknown == {}, f"未知的 calc：{unknown}，可选 {sorted(_CALCS)}"


def test_percent_metrics_declare_a_range():
    """百分比指标必须声明 range。

    cpu_usage 曾采到 112.3%：解析出错的数字一旦以 gauge 存进去就永远看着像真的，
    还会喂给阈值告警和容量预测。声明范围让它在采集时就失败。
    """
    missing = [
        m["name"] for m in BUILTIN
        if m.get("unit") == "%" and "range" not in m["parser"]
    ]
    assert missing == [], f"百分比指标没声明 range：{missing}"


def test_percent_ranges_are_zero_to_hundred():
    wrong = {
        m["name"]: m["parser"]["range"] for m in BUILTIN
        if m.get("unit") == "%" and m["parser"].get("range") != [0, 100]
    }
    assert wrong == {}, f"百分比指标的 range 应为 [0, 100]：{wrong}"
