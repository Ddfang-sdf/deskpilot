"""DeskPilot 错误码与异常定义。

错误码与详细设计说明书附录 A 登记册对应；本文件**不自述数量**——计数声明
散落多处即漂移之源。附录 A 的全量回填与计数单源化见 ISS-0074。
"""

# 参数与协议
INVALID_PARAMS = "INVALID_PARAMS"
# 闸一 / 绑定
NO_BINDING = "NO_BINDING"
# 闸二 / 白名单
NOT_WHITELISTED = "NOT_WHITELISTED"
POLICY_VIOLATION = "POLICY_VIOLATION"
REVOKED_BY_HUMAN = "REVOKED_BY_HUMAN"   # ISS-0072：人类撤回即永久否决，硬拒
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
# ISS-0091：像素兜底遇退化矩形（宽/高≤0，中心计算退化为屏幕原点=甩角判定点），
# fail-closed 拒绝点击
ELEMENT_RECT_DEGENERATE = "ELEMENT_RECT_DEGENERATE"
OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
TIMEOUT = "TIMEOUT"
# ISS-0017：提权边界与遮挡
ELEVATION_REQUIRED = "ELEVATION_REQUIRED"
WINDOW_OCCLUDED = "WINDOW_OCCLUDED"
# 安全与运行
EMERGENCY_STOP = "EMERGENCY_STOP"
# ISS-0087：安全桌面（锁屏/UAC）激活期间全禁 AI 操作（含 L0 感知）。
# 与 EMERGENCY_STOP 区分：本码退出安全桌面后自动恢复，无须人工复位
SECURE_DESKTOP = "SECURE_DESKTOP"
AUDIT_FAILURE = "AUDIT_FAILURE"
INTERNAL_ERROR = "INTERNAL_ERROR"
TOOL_TIMEOUT = "TOOL_TIMEOUT"         # ISS-0009 §6：超时预算触发（处理中）
# ISS-0021：click_text 文字寻址失败分类（fail-closed）
OCR_TEXT_NOT_FOUND = "OCR_TEXT_NOT_FOUND"
OCR_AMBIGUOUS = "OCR_AMBIGUOUS"
# REQ-003：检测器通道不可用（未装配 / 权重校验不过 / 装填或推理失败）
# 详尽设计 §5.3 §8：本码 fail-closed——不写图像、不产生条目。附录 A 登记
# 义务见详设 §11/§12（登记册全量回填见 ISS-0074）
DETECTOR_UNAVAILABLE = "DETECTOR_UNAVAILABLE"
# 注（ISS-0029）：原 ALL_REASON_CODES 登记册为零消费死代码且漏登
# TOOL_TIMEOUT,已按 sdfang 裁定删除;防复活守卫见 tests/test_errors_iss29.py


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
