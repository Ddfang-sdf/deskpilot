"""ISS-0022 按键可发现性测试(TC-KD-01~04,问题单 §4/§5 v0.2 评审通过,
方案 C:sdfang 2026-09-03 批准浏览器组合全收 L3)。

层级:单元(conftest 装配/替身直出;TC-KD-04 为 TOOL_SCHEMAS 形态断言)。
入口(设计):enforcement.submit(key) / TOOL_SCHEMAS["key"]["description"]。
"""

from __future__ import annotations

from deskpilot import errors
from deskpilot.models import OperationRequest


def _req(tool, params=None, token=None):
    return OperationRequest(tool=tool, params=params or {}, binding_token=token)


class TestKeyUnknownDiscoverability:
    """TC-KD-01/02:KEY_UNKNOWN 带可用键清单与"未执行"明示;拒绝零派发。
    断言:Decision 字段(直出)+执行器指令列(终效应直出)。"""

    def test_kd01_error_carries_list_and_no_exec_note(self, enforcement,
                                                      bound_record):
        """TC-KD-01:未收录键 → KEY_UNKNOWN + 未发送明示 + L2 成员可见。"""
        d = enforcement.submit(_req("key", {"key": "ctrl+shift+f99"},
                                    bound_record.token))
        assert d.reason_code == errors.KEY_UNKNOWN
        assert "未发送任何按键" in d.message
        assert "ctrl+c" in d.message                  # L2 成员在清单内(直出)

    def test_kd02_deny_dispatches_nothing(self, enforcement, executor,
                                          bound_record):
        """TC-KD-02:KEY_UNKNOWN 拒绝时执行层零指令(锁死"报错即未执行")。"""
        enforcement.submit(_req("key", {"key": "ctrl+shift+f99"},
                                bound_record.token))
        assert executor.instructions == []            # 终效应:未发送(直出)


class TestBrowserCombosEnrolledL3:
    """TC-KD-03:浏览器组合键(ctrl+t)收 L3 后走审批流,不再 KEY_UNKNOWN。
    断言:reason_code(直出)。"""

    def test_kd03_ctrl_t_goes_to_approval(self, enforcement, bound_record):
        d = enforcement.submit(_req("key", {"key": "ctrl+t"},
                                    bound_record.token))
        # FakeApprover 默认 deny → L3 审批拒绝语义;关键是不再 KEY_UNKNOWN
        assert d.reason_code == errors.APPROVAL_DENIED
        assert d.reason_code != errors.KEY_UNKNOWN


class TestKeyToolDescription:
    """TC-KD-04:key 工具描述具备可发现性指引(形态断言 R3)。"""

    def test_kd04_description_mentions_unknown_and_list(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        desc = TOOL_SCHEMAS["key"]["description"]
        assert "KEY_UNKNOWN" in desc
        assert "可用键" in desc
