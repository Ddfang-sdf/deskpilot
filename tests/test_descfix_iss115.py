"""ISS-0115 描述体检整改钉(TC-115-01~03)。

背景:2026-09-24 全量体检三发现——①type_text 缺 TYPE_MISMATCH/
READBACK_UNAVAILABLE 自愈指引;②六处「网页用浏览器工具」泛称未点名
browser_snapshot/browser_get_rect;③rect 两格式(region=[x,y,w,h] vs
[l,t,r,b])未写明。整改=描述文本修正(零行为面)。

层级:形态(注册表直读)。断言出处:TOOL_SCHEMAS 描述直读。
红态预期:三条全红(描述未改)。
"""

from __future__ import annotations

from deskpilot.mcp_server import TOOL_SCHEMAS


class TestDescriptionRemedyIss115:
    """TC-115-01~03(形态,ISS-0115 §1 整改三发现)。"""

    def test_tc115_01_type_text_error_code_guidance(self):
        """TC-115-01:type_text 描述含 TYPE_MISMATCH 与
        READBACK_UNAVAILABLE 的自愈指引(改用 type_element 或
        screenshot 自核)。断言:描述直读。"""
        d = TOOL_SCHEMAS["type_text"]["description"]
        assert "TYPE_MISMATCH" in d, "缺 TYPE_MISMATCH 指引(直读)"
        assert "READBACK_UNAVAILABLE" in d, "缺 READBACK_UNAVAILABLE 指引(直读)"
        assert "type_element" in d or "screenshot" in d, \
            "缺自愈下一步指引(直读)"

    def test_tc115_02_browser_tools_named_not_generic(self):
        """TC-115-02:六处「网页/浏览器工具」泛称必须点名
        browser_snapshot/browser_get_rect。断言:描述直读。"""
        for tool in ("screenshot", "find_window", "get_ui_tree", "attach",
                     "click_element", "type_element"):
            d = TOOL_SCHEMAS[tool]["description"]
            assert "browser_snapshot" in d, \
                f"{tool} 未点名 browser_snapshot(泛称残留,直读)"
            assert "浏览器工具" not in d or "browser_" in d, \
                f"{tool} 泛称未消除(直读)"

    def test_tc115_03_rect_format_written(self):
        """TC-115-03:rect 两格式写明——screenshot region=[x,y,w,h];
        set_window_rect/browser_get_rect=[l,t,r,b]。断言:描述直读。"""
        assert "[x,y,w,h]" in TOOL_SCHEMAS["screenshot"]["description"], \
            "screenshot 未写明 region 格式(直读)"
        assert "[l,t,r,b]" in TOOL_SCHEMAS["set_window_rect"]["description"], \
            "set_window_rect 未写明 rect 格式(直读)"
        assert "[l,t,r,b]" in TOOL_SCHEMAS["browser_get_rect"]["description"], \
            "browser_get_rect 未写明返回格式(直读)"
