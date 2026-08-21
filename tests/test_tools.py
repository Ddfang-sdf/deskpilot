"""工具层调度（tools.call_tool / 各工具公开入口）单元测试。

覆盖：结构化返回包装、放行/拒绝路径、TC-S-CH-03（注入载荷按纯文本透传）。
断言值来源：工具公开入口返回的 ToolResult、executor 收到的指令。
"""

from __future__ import annotations

from deskpilot import errors, tools

from .conftest import FIXTURE_HWND


class TestResultWrapping:
    def test_allowed_result_ok(self, ctx, bound_record):
        """放行：ToolResult.ok 为真且携带执行结果数据。"""
        r = tools.type_text(ctx, token=bound_record.token, text="hello")
        assert r.ok is True
        assert r.error_code == ""
        assert r.data is not None

    def test_denied_result(self, ctx, bound_record):
        """拒绝：ok 为假，错误码与裁决一致。"""
        r = tools.key(ctx, token=bound_record.token, key="alt+f4")
        assert r.ok is False
        assert r.error_code == errors.APPROVAL_DENIED
        assert "alt+f4" in r.message

    def test_invalid_params_result(self, ctx, bound_record):
        """参数规整失败：INVALID_PARAMS，执行层零接触。"""
        r = tools.call_tool(ctx, "click", {"token": bound_record.token,
                                           "x": "abc", "y": 1})
        assert r.ok is False
        assert r.error_code == errors.INVALID_PARAMS

    def test_no_binding_result(self, ctx):
        """无绑定：NO_BINDING 结构化返回。"""
        r = tools.type_text(ctx, token="no-such-token", text="x")
        assert r.ok is False
        assert r.error_code == errors.NO_BINDING


class TestDispatch:
    def test_executor_receives_plain_text_payload(self, ctx, bound_record, executor):
        """TC-S-CH-03：注入载荷作为纯文本原样进入指令，不做任何执行解释。"""
        payload = "calc.exe & format C:\\"
        r = tools.type_text(ctx, token=bound_record.token, text=payload)
        assert r.ok is True
        assert executor.instructions[0]["params"]["text"] == payload

    def test_instruction_carries_binding_hwnd(self, ctx, bound_record, executor):
        """指令携带绑定窗口句柄，供执行层定位。"""
        tools.click(ctx, token=bound_record.token, x=300, y=300)
        ins = executor.instructions[0]
        assert ins["tool"] == "click"
        assert ins["binding_hwnd"] == FIXTURE_HWND
        assert ins["params"]["x"] == 300 and ins["params"]["y"] == 300

    def test_denied_never_touches_executor(self, ctx, executor):
        """拒绝路径执行层零接触。"""
        tools.key(ctx, token="bad-token", key="a")
        tools.type_text(ctx, token="bad-token", text="x")
        assert executor.instructions == []

    def test_launch_app_via_tool_entry(self, ctx, executor):
        """launch_app 工具入口：白名单内放行并下发执行。"""
        r = tools.launch_app(ctx, app="notepad.exe")
        assert r.ok is True
        assert executor.instructions[0]["params"]["app"] == "notepad.exe"
