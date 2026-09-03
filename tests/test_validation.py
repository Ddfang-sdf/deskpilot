"""MCP 层参数规整（validate_call / TOOL_SCHEMAS）单元测试。

覆盖：TC-E-PAR-01/02/03/04、TC-S-CH-02 基础、TC-S-TOK-06 基础（额外参数透传）。
断言值来源：validate_call 返回值与 InvalidParamsError 异常的 code/message。
"""

from __future__ import annotations

import pytest

from deskpilot import errors
from deskpilot.errors import InvalidParamsError
from deskpilot.mcp_server import TOOL_SCHEMAS, validate_call
from deskpilot.models import TOOL_LEVELS


class TestSchemaCompleteness:
    def test_all_tools_have_schema(self):
        """全部工具均有参数模式声明（与设计工具清单一致）。

        注：设计文档按功能条目计 22 个，其中 attach / detach 占同一条目行，
        协议方法实为 23 个；ISS-0012 增 request_remove_from_whitelist 后为 24 个；
        ISS-0021 增 click_text 后为 25 个。
        """
        assert set(TOOL_SCHEMAS.keys()) == set(TOOL_LEVELS.keys())
        assert len(TOOL_SCHEMAS) == 25

    def test_unknown_tool_rejected(self, policy):
        """TC-S-CH-02 基础：未发布的方法名直接拒绝。"""
        with pytest.raises(InvalidParamsError):
            validate_call("execute_raw", {}, policy)


class TestRequiredAndTypes:
    @pytest.mark.parametrize("tool,params", [
        ("type_text", {"text": "x"}),                    # 缺 token
        ("type_text", {"token": "t"}),                   # 缺 text
        ("click", {"token": "t", "x": 1}),               # 缺 y
        ("screenshot", {}),                              # 缺 scope
        ("key", {"token": "t"}),                         # 缺 key
    ])
    def test_missing_required(self, policy, tool, params):
        """TC-E-PAR-01：缺必填参数拒绝，不进入后续模块。"""
        with pytest.raises(InvalidParamsError) as exc:
            validate_call(tool, params, policy)
        assert exc.value.code == errors.INVALID_PARAMS

    def test_wrong_type(self, policy):
        """TC-E-PAR-02：类型不符拒绝。"""
        with pytest.raises(InvalidParamsError):
            validate_call("click", {"token": "t", "x": "abc", "y": 1}, policy)

    @pytest.mark.parametrize("tool,params", [
        ("screenshot", {"scope": "windowX"}),            # 枚举越界
        ("scroll", {"token": "t", "direction": "斜着", "amount": 3}),
    ])
    def test_enum_out_of_range(self, policy, tool, params):
        """TC-E-PAR-03：枚举取值越界拒绝。"""
        with pytest.raises(InvalidParamsError):
            validate_call(tool, params, policy)

    def test_at_least_one(self, policy):
        """attach / find_window 至少一个定位条件。"""
        with pytest.raises(InvalidParamsError):
            validate_call("attach", {}, policy)
        with pytest.raises(InvalidParamsError):
            validate_call("find_window", {}, policy)
        ok = validate_call("attach", {"title": "记事本"}, policy)
        assert ok["title"] == "记事本"

    def test_conditional_required(self, policy):
        """screenshot：region 必须带 rect，window 必须带窗口标识。"""
        with pytest.raises(InvalidParamsError):
            validate_call("screenshot", {"scope": "region"}, policy)
        ok = validate_call("screenshot",
                           {"scope": "region", "rect": [0, 0, 10, 10]}, policy)
        assert ok["scope"] == "region"


class TestLengthLimit:
    def test_text_over_limit(self, policy):
        """TC-E-PAR-04：超 input_max_chars 拒绝。"""
        over = policy.input_max_chars + 1
        with pytest.raises(InvalidParamsError) as exc:
            validate_call("type_text", {"token": "t", "text": "x" * over}, policy)
        assert exc.value.code == errors.INVALID_PARAMS

    def test_text_at_limit_ok(self, policy):
        """TC-E-PAR-04 边界：恰在上限放行。"""
        ok = validate_call("type_text",
                           {"token": "t", "text": "x" * policy.input_max_chars},
                           policy)
        assert len(ok["text"]) == policy.input_max_chars


class TestPassThrough:
    def test_extra_params_pass_through(self, policy):
        """TC-S-TOK-06 基础：未声明的额外参数透传（参与指纹但不影响判定）。"""
        ok = validate_call("key", {"token": "t", "key": "alt+f4", "force": True},
                           policy)
        assert ok["force"] is True
        assert ok["key"] == "alt+f4"

    def test_returned_params_are_copy(self, policy):
        """规整返回副本，不改写调用方传入的原始字典。"""
        raw = {"token": "t", "text": "hello"}
        ok = validate_call("type_text", raw, policy)
        assert ok == raw
        assert ok is not raw
