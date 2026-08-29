"""DeskPilot 错误码与异常定义。

错误码与详细设计说明书附录 A 一致（19 个原因码）。
"""

# 参数与协议
INVALID_PARAMS = "INVALID_PARAMS"
# 闸一 / 绑定
NO_BINDING = "NO_BINDING"
# 闸二 / 白名单
NOT_WHITELISTED = "NOT_WHITELISTED"
POLICY_VIOLATION = "POLICY_VIOLATION"
# 闸三 / 按键
KEY_DENIED = "KEY_DENIED"
KEY_UNKNOWN = "KEY_UNKNOWN"
# 闸四 / 审批
APPROVAL_DENIED = "APPROVAL_DENIED"
APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
# 目标对象
TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
WINDOW_GONE = "WINDOW_GONE"
ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
ELEMENT_AMBIGUOUS = "ELEMENT_AMBIGUOUS"
ELEMENT_DISABLED = "ELEMENT_DISABLED"
ELEMENT_UNSUPPORTED = "ELEMENT_UNSUPPORTED"
OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
TIMEOUT = "TIMEOUT"
# 安全与运行
EMERGENCY_STOP = "EMERGENCY_STOP"
AUDIT_FAILURE = "AUDIT_FAILURE"
INTERNAL_ERROR = "INTERNAL_ERROR"
TOOL_TIMEOUT = "TOOL_TIMEOUT"         # ISS-0009 §6：超时预算触发（处理中）

ALL_REASON_CODES = frozenset({
    INVALID_PARAMS, NO_BINDING, NOT_WHITELISTED, POLICY_VIOLATION,
    KEY_DENIED, KEY_UNKNOWN, APPROVAL_DENIED, APPROVAL_TIMEOUT,
    TARGET_NOT_FOUND,
    AMBIGUOUS_TARGET, WINDOW_GONE, ELEMENT_NOT_FOUND, ELEMENT_AMBIGUOUS,
    ELEMENT_DISABLED, ELEMENT_UNSUPPORTED, OUT_OF_BOUNDS, TIMEOUT,
    EMERGENCY_STOP, AUDIT_FAILURE, INTERNAL_ERROR,
})


class DeskPilotError(Exception):
    """服务内部异常基类，携带错误码。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class PolicyError(DeskPilotError):
    """策略文件缺失或非法（启动期 fail-closed）。"""


class InvalidParamsError(DeskPilotError):
    """MCP 层参数规整失败。"""

    def __init__(self, message: str = ""):
        super().__init__(INVALID_PARAMS, message)


class AuditFailure(DeskPilotError):
    """审计落盘失败（操作必须视为失败）。"""

    def __init__(self, message: str = ""):
        super().__init__(AUDIT_FAILURE, message)


class ExecutorError(DeskPilotError):
    """执行层动作失败（OUT_OF_BOUNDS / WINDOW_GONE / ELEMENT_* 等）。"""
