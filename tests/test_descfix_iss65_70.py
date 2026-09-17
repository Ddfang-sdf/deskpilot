"""ISS-0065/0066/0069/0070 描述与 schema 一致性批次测试(五要素见各单据)。

层级:fw/cm/te 单元(FakeExecutor/FakeElement 替身,允许打桩,断言在返回值/
替身记录直出);oc 形态(schema 注册表直出)+单元路由钉。

入口(设计):mcp_server.validate_call / TOOL_SCHEMAS(形态面);
tools.call_tool(路由面);Executor.get_clickable_map(SoM 产出面)。

断言出处:参数规整结果/ToolResult/entries 字段直出;替身调用记录直出;
描述文本=注册表字段直出。

红态预期(现状):
- fw01/fw02:at_least_one=[title,process] 拒 hwnd → INVALID_PARAMS(ISS-0065);
- cm01:entries 无 som_id 键 → KeyError/断言失败(ISS-0066);
- oc01:描述含「屏幕区域」假象形态 → 断言失败(ISS-0069);
- te01:描述无「至少一项」指引 → 断言失败(ISS-0070);
- fw03/oc02/te02 红期即绿(回归钉:既有形态不破坏/错误消息指引已具)。
"""

from __future__ import annotations

import pytest
from PIL import Image

from deskpilot import errors
from deskpilot.executor import Executor
from deskpilot.mcp_server import TOOL_SCHEMAS, validate_call
from deskpilot.tools import ToolContext, call_tool

from .conftest import FIXTURE_HWND, FakeExecutor, FakeProbe
from .test_elements import FakeElement, make_callable_source


class TestFindWindowHwnd:
    """ISS-0065 方向①:schema 补 hwnd(int),与 probe 能力对齐。"""

    def test_fw01_schema_accepts_hwnd(self, policy):
        """fw01(形态):纯 hwnd 通过参数规整(optional 增 hwnd,
        at_least_one 扩 [title, process, hwnd])。
        红态(现状):at_least_one 只认 title/process → InvalidParamsError。"""
        params = validate_call("find_window", {"hwnd": 123}, policy)
        assert params["hwnd"] == 123            # 规整结果直出

    def test_fw02_hwnd_routes_and_filters(self, policy):
        """fw02(单元):hwnd 直查命中——call_tool 路由透传 hwnd 到
        executor.find_windows,返回按 hwnd 过滤后的窗口清单。
        红态(现状):schema 拦截 → ok=False。"""
        ex = FakeExecutor()
        ex.live_windows = [{"hwnd": 7, "title": "甲", "process": "a.exe",
                            "rect": [0, 0, 100, 100]},
                           {"hwnd": 9, "title": "乙", "process": "b.exe",
                            "rect": [0, 0, 100, 100]}]
        ctx = ToolContext(policy=policy, enforcement=None, executor=ex)
        r = call_tool(ctx, "find_window", {"hwnd": 7})
        assert r.ok is True                     # 返回值直出
        assert [w["hwnd"] for w in r.data["windows"]] == [7]  # 直出

    def test_fw03_title_path_unchanged(self, policy):
        """fw03(回归钉):title 路径不变。红期即绿。"""
        ex = FakeExecutor()
        ex.live_windows = [{"hwnd": 7, "title": "甲", "process": "a.exe",
                            "rect": [0, 0, 100, 100]}]
        ctx = ToolContext(policy=policy, enforcement=None, executor=ex)
        r = call_tool(ctx, "find_window", {"title": "甲"})
        assert r.ok is True
        assert len(r.data["windows"]) == 1      # FakeExecutor 现状:title 不过滤
        # (title/process 过滤在真 probe 层;本钉只锁「schema 放行+路由到达」)


class TestSomIdDualWrite:
    """ISS-0066 方向②:UIA 条目 id 与 som_id 双写同值(id 废弃日程入描述)。"""

    def test_cm01_entries_dual_write_som_id(self, estop, tmp_path, clock):
        """cm01(单元):get_clickable_map 的 UIA 条目同带 id 与 som_id 同值。
        红态(现状):条目只有 id 键 → KeyError/断言失败。
        click_element 消费 som_id 由既有套件覆盖(test_elements)。"""
        leaf = FakeElement(name="保存", control_type="ButtonControl",
                           rect=(110, 110, 160, 140))
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      wait_timeout_max=5.0, clock=clock, probe=FakeProbe())
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[leaf])})
        ex._shot_fn = lambda region: Image.new(
            "RGB", (region["width"], region["height"]))
        r = ex.get_clickable_map(FIXTURE_HWND)
        assert r["count"] >= 1
        for e in r["entries"]:                  # 条目字段直出
            assert e["som_id"] == e["id"]

    def test_cm02_description_marks_id_deprecated(self):
        """cm02(形态):描述注明双写与 id 废弃日程(AI 一次性认知)。
        红态(现状):描述无 som_id/id 双写说明。"""
        d = TOOL_SCHEMAS["get_clickable_map"]["description"]
        assert "som_id" in d and "id" in d
        assert "废弃" in d                      # 注册表字段直出


class TestOcrDescriptionHonesty:
    """ISS-0069 方向②:描述收紧到真实形态(路径/rect),指向 screenshot ocr:true。"""

    def test_oc01_description_no_fake_screen_form(self):
        """oc01(形态):描述不得再宣称「屏幕区域」假形态;须写真实形态
        (图像路径 / [l,t,r,b] rect)并指向 screenshot(ocr:true)组合;
        ISS-0039 闸门关键词(局部/重试)保住。
        红态(现状):描述含「屏幕区域」。"""
        d = TOOL_SCHEMAS["ocr"]["description"]
        assert "屏幕区域" not in d              # 假形态剔除(注册表直出)
        assert "[l,t,r,b]" in d                 # 真实形态写明
        assert "局部" in d and "重试" in d       # ISS-0039 TC-OC-01 闸门不动

    def test_oc02_claimed_forms_validate(self, policy):
        """oc02(单元,宣称形态逐一命中):描述宣称的两种 source 形态
        (路径字符串 / rect 四元组)均通过参数规整。红期即绿(路由钉)。"""
        assert validate_call("ocr", {"source": "shot.png"}, policy)
        assert validate_call("ocr", {"source": [0, 0, 10, 10]}, policy)


class TestTypeElementGuidance:
    """ISS-0070:描述与错误消息都写明「name/automation_id 至少一项」。"""

    def test_te01_description_declares_at_least_one(self):
        """te01(形态):描述写明至少一项定位必填。
        红态(现状):描述无此指引。"""
        d = TOOL_SCHEMAS["type_element"]["description"]
        assert "至少" in d and "name/automation_id" in d   # 注册表字段直出

    def test_te02_empty_selector_error_guides(self, ctx):
        """te02(单元,钉既有):空选择器 → INVALID_PARAMS 且消息含
        「name/automation_id 至少提供」指引(结构化拒绝已在校验层,
        比单据所记 AMBIGUOUS 更早更准——行为不回退)。红期即绿。"""
        r = call_tool(ctx, "type_element", {"token": "t", "text": "x"})
        assert r.ok is False
        assert r.error_code == errors.INVALID_PARAMS      # 返回值直出
        assert "name/automation_id" in r.message          # 消息指引直出
