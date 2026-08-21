"""策略管理程序（详细设计 §5）。

启动时一次性加载 policy.yml，校验并锁定；运行期只读，不提供重载入口（INV-9）。
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import yaml

from .errors import PolicyError
from .models import Policy

# 可选节默认值（详细设计 §5.9）
DEFAULT_INPUT_MAX_CHARS = 65536
DEFAULT_L0_DURING_FREEZE = True
DEFAULT_CORNER_HOLD_MS = 200
DEFAULT_FREEZE_REMIND_INTERVAL = 180.0   # 冻结弹窗"稍后提醒"重提醒间隔（秒，ISS-0004）
DEFAULT_INPUT_SCENARIO_KEYS = frozenset({"backspace"})
DEFAULT_INPUT_CONTROL_TYPES = frozenset({"Edit", "Document"})

_REQUIRED_SECTIONS = ("whitelist", "terminal_apps", "keys", "timeouts", "audit_dir")
_TIMEOUT_KEYS = ("binding_ttl", "approval_ttl", "wait_poll_interval",
                 "wait_timeout_max")
_VALID_LEVELS = frozenset({"L0", "L1", "L2"})

_KEY_ALIASES = {"return": "enter", "esc": "escape"}
_MODIFIER_ORDER = {"ctrl": 0, "alt": 1, "shift": 2, "win": 3}


def normalize_key(raw: str) -> str:
    """按键规范化（详细设计 §8.6）：修饰键定序、别名归一、字母小写。

    策略表加载与闸三查询共用同一实现（禁止两份代码）。
    例："F4+Alt" → "alt+f4"；"Return" → "enter"。
    """
    tokens = [t.strip().lower() for t in str(raw).split("+") if t.strip()]
    mods = sorted({t for t in tokens if t in _MODIFIER_ORDER},
                  key=_MODIFIER_ORDER.get)
    bases = [t for t in tokens if t not in _MODIFIER_ORDER]
    base = _KEY_ALIASES.get(bases[-1], bases[-1]) if bases else ""
    parts = mods + ([base] if base else [])
    return "+".join(parts)


def _fail(message: str) -> PolicyError:
    return PolicyError(f"策略非法：{message}")


def _load_whitelist(raw) -> MappingProxyType:
    if not isinstance(raw, list):
        raise _fail("whitelist 必须为列表")
    table: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict) or "process" not in item:
            raise _fail("whitelist 条目必须含 process")
        proc = str(item["process"]).strip().lower()
        if not proc or "/" in proc or "\\" in proc:
            raise _fail(f"进程名非法: {item['process']!r}")
        level = str(item.get("max_level", "L2")).strip().upper()
        if level not in _VALID_LEVELS:
            raise _fail(f"白名单级别上限非法: {level}（进程 {proc}）")
        table[proc] = level
    return MappingProxyType(table)


def _load_str_set(raw, section: str, normalize_keys: bool = False) -> frozenset:
    if not isinstance(raw, list):
        raise _fail(f"{section} 必须为列表")
    items = []
    for v in raw:
        s = str(v).strip()
        items.append(normalize_key(s) if normalize_keys else s.lower())
    return frozenset(items)


def _load_timeouts(raw) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise _fail("timeouts 必须为映射")
    out = {}
    for k in _TIMEOUT_KEYS:
        if k not in raw:
            raise _fail(f"timeouts 缺少 {k}")
        v = raw[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise _fail(f"timeouts.{k} 必须为正数")
        out[k] = float(v)
    return out


def load_policy(path: str) -> Policy:
    """加载并校验策略文件。

    文件缺失、节缺失、类型错误或取值非法时抛出 PolicyError（启动 fail-closed）。
    limits / estop / keys.input_scenario_keys / keys.input_control_types 缺省用默认值。
    """
    p = Path(path)
    if not p.is_file():
        raise PolicyError(f"策略文件不存在: {path}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PolicyError(f"策略文件解析失败: {e}") from e
    if not isinstance(data, dict):
        raise _fail("顶层必须为映射")

    for section in _REQUIRED_SECTIONS:
        if section not in data:
            raise _fail(f"缺少必填节: {section}")

    whitelist = _load_whitelist(data["whitelist"])
    terminal_apps = _load_str_set(data["terminal_apps"], "terminal_apps")

    keys = data["keys"]
    if not isinstance(keys, dict) or "l2_allow" not in keys or "l3_controlled" not in keys:
        raise _fail("keys 节必须含 l2_allow 与 l3_controlled")
    l2_keys = _load_str_set(keys["l2_allow"], "keys.l2_allow", normalize_keys=True)
    l3_keys = _load_str_set(keys["l3_controlled"], "keys.l3_controlled",
                            normalize_keys=True)
    input_scenario_keys = _load_str_set(
        keys.get("input_scenario_keys", sorted(DEFAULT_INPUT_SCENARIO_KEYS)),
        "keys.input_scenario_keys", normalize_keys=True)
    input_control_types = frozenset(
        str(v).strip() for v in keys.get(
            "input_control_types", sorted(DEFAULT_INPUT_CONTROL_TYPES)))

    timeouts = _load_timeouts(data["timeouts"])

    limits = data.get("limits", {})
    if not isinstance(limits, dict):
        raise _fail("limits 必须为映射")
    input_max_chars = limits.get("input_max_chars", DEFAULT_INPUT_MAX_CHARS)
    if (isinstance(input_max_chars, bool) or not isinstance(input_max_chars, int)
            or input_max_chars <= 0):
        raise _fail("limits.input_max_chars 必须为正整数")

    estop_cfg = data.get("estop", {})
    if not isinstance(estop_cfg, dict):
        raise _fail("estop 必须为映射")
    l0_during_freeze = estop_cfg.get("l0_during_freeze", DEFAULT_L0_DURING_FREEZE)
    if not isinstance(l0_during_freeze, bool):
        raise _fail("estop.l0_during_freeze 必须为布尔")
    corner_hold_ms = estop_cfg.get("corner_hold_ms", DEFAULT_CORNER_HOLD_MS)
    if (isinstance(corner_hold_ms, bool) or not isinstance(corner_hold_ms, int)
            or corner_hold_ms <= 0):
        raise _fail("estop.corner_hold_ms 必须为正整数")
    freeze_remind_interval = estop_cfg.get("freeze_remind_interval",
                                           DEFAULT_FREEZE_REMIND_INTERVAL)
    if (isinstance(freeze_remind_interval, bool)
            or not isinstance(freeze_remind_interval, (int, float))
            or freeze_remind_interval <= 0):
        raise _fail("estop.freeze_remind_interval 必须为正数")

    audit_dir = str(data["audit_dir"]).strip()
    if not audit_dir:
        raise _fail("audit_dir 不能为空")

    return Policy(
        whitelist=whitelist,
        terminal_apps=terminal_apps,
        l2_keys=l2_keys,
        l3_keys=l3_keys,
        input_scenario_keys=input_scenario_keys,
        input_control_types=input_control_types,
        binding_ttl=timeouts["binding_ttl"],
        approval_ttl=timeouts["approval_ttl"],
        wait_poll_interval=timeouts["wait_poll_interval"],
        wait_timeout_max=timeouts["wait_timeout_max"],
        input_max_chars=input_max_chars,
        l0_during_freeze=l0_during_freeze,
        corner_hold_ms=corner_hold_ms,
        freeze_remind_interval=float(freeze_remind_interval),
        audit_dir=audit_dir,
    )
