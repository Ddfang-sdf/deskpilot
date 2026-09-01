"""ISS-0015 划界版测试（TC-BOUND-01~05,2026-09-01 批准；验证通过才提交）。

层级：单元（Server.instructions 属性/描述文本直出）。
入口（设计）：mcp_server.build_server 的 Server.instructions / TOOL_SCHEMAS 描述。
"""

from __future__ import annotations

from deskpilot import mcp_server
from deskpilot.models import TOOL_LEVELS


def _descs():
    return {name: schema.get("description", "")
            for name, schema in mcp_server.TOOL_SCHEMAS.items()}


class TestBoundary:
    """TC-BOUND:领域划界——服务级路由规则+描述第一句定界。
    断言:instructions 属性与描述文本(直出)。"""

    def test_bound01_server_instructions_routing(self):
        """TC-BOUND-01:Server.instructions 为双向路由规则。"""
        ctx = type("C", (), {"policy": None})()
        server = mcp_server.build_server(ctx)
        ins = getattr(server, "instructions", "") or ""
        assert "Windows 桌面" in ins
        assert "浏览器" in ins

    def test_bound02_first_sentence_domain(self):
        """TC-BOUND-02:每条描述第一句含领域对象(桌面/窗口)。"""
        for name, d in _descs().items():
            first = d.split("。")[0]
            assert ("桌面" in first) or ("窗口" in first), name

    def test_bound03_no_bracket_prefix(self):
        """TC-BOUND-03:无【】模板前缀。"""
        for name, d in _descs().items():
            assert not d.strip().startswith("【"), name

    def test_bound04_screenshot_viewable(self):
        """TC-BOUND-04:screenshot 声明图像可查看。"""
        d = _descs()["screenshot"]
        assert ("查看" in d) or ("图像内容" in d)

    def test_bound05_quality_regression(self):
        """TC-BOUND-05:既有质量规则回归(非模板/组合引导/长度/完整)。"""
        descs = _descs()
        assert set(descs.keys()) == set(TOOL_LEVELS.keys())
        for name, d in descs.items():
            assert "桌面操作工具" not in d, name
            assert len(d) <= 260, name
