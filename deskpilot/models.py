"""DeskPilot 数据实体。

字段与详细设计说明书 §3.1 / §6.9 / §7.9 / §10.9 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# 操作级别
L0 = "L0"
L1 = "L1"
L2 = "L2"
L3 = "L3"

# 22 个工具的静态分级（详细设计 §12.2 / §13.2 / §14.2）
TOOL_LEVELS: Mapping[str, str] = {
    "screenshot": L0, "ocr": L0, "find_window": L0, "get_ui_tree": L0,
    "get_clickable_map": L0, "template_match": L0, "get_cursor": L0,
    "get_clipboard": L0,
    "wait_for_window": L1, "wait_for_element": L1, "move": L1,
    "scroll": L1, "attach": L1, "detach": L1,
    "launch_app": L2, "activate_window": L2, "click_element": L2,
    "type_element": L2, "click": L2, "type_text": L2, "key": L2,
    "set_clipboard": L2, "drag": L2,
    "click_text": L2,                # ISS-0021：按文字点击(OCR 定位)
    # ISS-0012 §6 E3：AI 请求撤回白名单（人类弹窗裁决后才执行，L1 请求类）
    "request_remove_from_whitelist": L1,
}

# 需要有效绑定的工具（详细设计 §12.4 / §13.4 / §14.4 输入项中含"绑定令牌✱"者；
# launch_app 豁免闸一，见详细设计 §8.7 豁免规则）
BINDING_REQUIRED_TOOLS = frozenset({
    "wait_for_element", "scroll", "detach",
    "activate_window", "click_element", "type_element", "click",
    "type_text", "key", "set_clipboard", "drag", "click_text",
})

# ISS-0009 §6：各级别调用的内部时限预算（秒）；临期返回 TOOL_TIMEOUT
# 结构化"处理中"错误而非悬挂。L3 不在表内——其预算为 approval_ttl+5（同步审批语义）。
TOOL_TIME_BUDGETS: Mapping[str, float] = {
    "L0": 5.0,
    "L1": 15.0,
    "L2": 30.0,
}

# ISS-0039：per-tool 预算覆盖（注册表，通用性优先）——全屏 CPU OCR 实测
# 首推 5.2s 超 L0 5s 预算（2026-09-05 实证，与 daemon 同一适配路径）；
# screenshot 含 ocr:true（ISS-0037-B）同链。12.0 = 实测 2.3 倍余量。
TOOL_BUDGET_OVERRIDES: Mapping[str, float] = {
    "ocr": 12.0,
    "screenshot": 12.0,
}

# ISS-0023：TOOL_TIMEOUT 重试指引（单源常量，httpd 响应构造消费）。
# L3（审批挂起语义）密集重试无意义给 2000ms；其余预算级 500ms。
RETRY_AFTER_MS: Mapping[str, int] = {"L3": 2000, "default": 500}
RETRY_MAX: int = 3


@dataclass(frozen=True)
class Policy:
    """策略只读视图（详细设计 §5.9）。加载后锁定，运行期不可变（INV-9）。"""

    whitelist: Mapping[str, str]          # 进程名(小写) -> 级别上限 "L0"|"L1"|"L2"
    terminal_apps: frozenset[str]
    l2_keys: frozenset[str]               # 规范化后的 L2 许可键
    l3_keys: frozenset[str]               # 规范化后的 L3 危险键
    input_scenario_keys: frozenset[str]   # 场景受限键（默认仅 backspace）
    input_control_types: frozenset[str]   # 输入场景控件类型（默认 Edit/Document）
    binding_ttl: float
    approval_ttl: float
    wait_poll_interval: float
    wait_timeout_max: float
    input_max_chars: int
    l0_during_freeze: bool
    corner_hold_ms: int
    freeze_remind_interval: float     # 冻结弹窗稍后提醒重提醒间隔秒（ISS-0004）
    audit_dir: str
    idle_timeout_minutes: float = 0.0  # daemon idle 自停分钟数，0=禁用（ISS-0008）
    logs_max_age_days: float = 90.0        # 审计日志留存天数（ISS-0031,仅年龄档）
    shots_max_age_days: float = 90.0       # 截图留存天数（ISS-0031:14→90）
    shots_max_bytes: int = 471859200       # 截图空间上限字节 450MB（ISS-0031:2GB→450MB）
    cleanup_grace_seconds: float = 600.0   # 清理在场保护窗秒（ISS-0010）
    cleanup_interval_seconds: float = 3600.0  # 清理定时周期秒，0=仅启动时（ISS-0010）


@dataclass
class BindingRecord:
    """绑定记录（详细设计 §6.9）。last_active_at 随校验通过刷新。"""

    token: str
    hwnd: int
    process_name: str
    window_rect: tuple[int, int, int, int]
    bound_at: float
    last_active_at: float
    window_title: str = ""      # attach 时刻的标题快照（审批描述兜底用）


@dataclass
class ApprovalToken:
    """审批令牌（详细设计 §7.9）。仅内存，不经 AI。"""

    token_id: str
    fingerprint: str
    issued_at: float
    expires_at: float
    consumed: bool = False
    # ISS-0019：授权范围——"once" 单操作(默认) / "window_session"
    # 同一绑定窗口+同一工具的会话内后续同类(终端类与 key 类不适用)
    scope: str = "once"
    tool: str = ""
    binding_token: str = ""


@dataclass(frozen=True)
class OperationRequest:
    """写操作请求（详细设计 §8.4）。"""

    tool: str
    params: Mapping[str, Any]
    binding_token: str | None


@dataclass(frozen=True)
class Decision:
    """裁决结果（详细设计 §8.5）。data 为放行时执行层返回的结果数据。"""

    allowed: bool
    reason_code: str        # 放行时为空串
    message: str
    effective_level: str
    data: Any = None


@dataclass(frozen=True)
class AuditEntry:
    """审计记录（详细设计 §10.9）。"""

    seq: int
    timestamp: str
    tool: str
    params_digest: str
    params_full: str
    level: str
    decision: str           # "放行" / "拒绝"
    reason_code: str
    result: str
    duration_ms: int
    before_shot: str
    after_shot: str
    binding_token: str


@dataclass(frozen=True)
class ToolResult:
    """工具层对 MCP 客户端的结构化返回。"""

    ok: bool
    error_code: str         # 成功时为空串
    message: str
    data: Any = field(default=None)
