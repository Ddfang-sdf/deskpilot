"""ISS-0039 OCR 超时指引与预算覆盖测试(TC-OC-01~06,问题单 §3)。

层级:单元(预算决议纯函数直出)+ 形态断言(描述/调用点接线)。
入口(设计):httpd.resolve_budget(tool, level, policy) /
models.TOOL_BUDGET_OVERRIDES / TOOL_SCHEMAS["ocr"].description。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestOcrBudgetOverride:
    """TC-OC-02~05:per-tool 预算覆盖决议。断言:返回值直出。"""

    def test_oc02_ocr_override(self, policy):
        from deskpilot.httpd import resolve_budget
        assert resolve_budget("ocr", "L0", policy) == 12.0

    def test_oc03_screenshot_override(self, policy):
        from deskpilot.httpd import resolve_budget
        assert resolve_budget("screenshot", "L0", policy) == 12.0

    def test_oc04_uncovered_tool_unchanged(self, policy):
        from deskpilot.httpd import resolve_budget
        assert resolve_budget("find_window", "L0", policy) == 5.0

    def test_oc05_level_semantics_unchanged(self, policy):
        from deskpilot.httpd import resolve_budget
        assert resolve_budget("drag", "L2", policy) == policy.approval_ttl + 5


class TestOcrGuidanceShape:
    """TC-OC-01/06:描述指引与调用点接线。断言:形态直出。"""

    def test_oc01_description_guidance(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        d = TOOL_SCHEMAS["ocr"]["description"]
        assert ("局部" in d or "区域" in d) and "重试" in d

    def test_oc06_call_site_passes_tool(self):
        src = (ROOT / "deskpilot" / "httpd.py").read_text(encoding="utf-8")
        assert "resolve_budget(tool" in src            # 调用点接线(源码形态直出)
