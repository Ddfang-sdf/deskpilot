"""ISS-0015 工具描述意图化测试（TC-DESC-01~06,2026-09-01 批准）。

层级：单元（注册表/文本直出）+ 源码接线断言（list_tools 不再模板拼接）。
入口（设计）：mcp_server.TOOL_SCHEMAS[*]["description"] / _list() 描述取用。
"""

from __future__ import annotations

import inspect

from deskpilot import mcp_server
from deskpilot.models import TOOL_LEVELS

DOMAIN_HINTS = ("Windows 桌面", "非浏览器")
COMBO_TOOLS = {"find_window": ("attach", "绑定"),
               "attach": ("token", "令牌"),
               "get_ui_tree": ("attach", "绑定"),
               "click_element": ("attach", "绑定")}


class TestDescriptionQuality:
    """TC-DESC:意图化描述质量五查。
    断言:注册表 description 字段文本(直出)。"""

    def _descs(self):
        return {name: schema.get("description", "")
                for name, schema in mcp_server.TOOL_SCHEMAS.items()}

    def test_desc01_complete_registry(self):
        """TC-DESC-01:每个工具均有非空 description。"""
        descs = self._descs()
        assert set(descs.keys()) == set(TOOL_LEVELS.keys())
        assert all(d.strip() for d in descs.values())

    def test_desc02_no_template(self):
        """TC-DESC-02:无模板废话。"""
        for name, d in self._descs().items():
            assert "桌面操作工具" not in d, name

    def test_desc03_combo_guidance(self):
        """TC-DESC-03:核心链路工具描述含组合引导关键词。"""
        descs = self._descs()
        for name, hints in COMBO_TOOLS.items():
            assert any(h in descs[name] for h in hints), name

    def test_desc04_domain_qualifier(self):
        """TC-DESC-04:每条描述含领域限定词(多 MCP 路由依据)。"""
        for name, d in self._descs().items():
            assert any(h in d for h in DOMAIN_HINTS), name

    def test_desc05_length_bounded(self):
        """TC-DESC-05:每条 ≤200 字。"""
        for name, d in self._descs().items():
            assert len(d) <= 200, name

    def test_desc06_list_uses_registry_not_template(self):
        """TC-DESC-06:list_tools 直接取用注册描述(源码不再模板拼接)。"""
        src = inspect.getsource(mcp_server)
        assert "DeskPilot 桌面操作工具" not in src
        assert 'schema["description"]' in src or 'schema.get("description"' in src
