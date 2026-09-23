"""ISS-0044 无文字图形定位测试(TC-CT-01~16,问题单 §4 v0.3)。

层级:单元(FakeElement/pyautogui/OCR 替身)+形态+集成(真机,--run-integration)。
入口(设计):Executor.get_ui_tree(control_type)/ _click_element(control_type+index)
/ _click_text(offset+distance)/ TOOL_SCHEMAS。
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from deskpilot.errors import InvalidParamsError
from deskpilot.executor import Executor
from deskpilot.executor import core as core_mod

from .conftest import FIXTURE_HWND, FakeProbe
from .test_elements import FakeElement, make_callable_source


class _Rec:
    def __init__(self):
        self.calls = []

    def fn(self, name):
        def f(*a, **k):
            self.calls.append((name, a, k))
        return f

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def _exec(estop, tmp_path, monkeypatch, ocr_engine=None):
    rec = _Rec()
    for fn in ("mouseDown", "mouseUp", "moveTo", "click", "hscroll", "scroll"):
        monkeypatch.setattr(core_mod.pyautogui, fn, rec.fn(fn))
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  probe=FakeProbe(), ocr_engine=ocr_engine)
    ex._check_occlusion = lambda *a, **k: None
    rec.calls.clear()                       # 清启动抬键清扫
    return ex, rec


class TestUiTreeFilter:
    """TC-CT-01/02/13:get_ui_tree control_type 过滤。断言:元素清单直出。"""

    def _tree(self):
        return FakeElement(children=[
            FakeElement(name="甲", control_type="CheckBoxControl",
                        rect=[10, 10, 30, 30]),
            FakeElement(name="乙", control_type="ButtonControl",
                        rect=[40, 10, 60, 30]),
            FakeElement(name="丙", control_type="CheckBoxControl",
                        rect=[70, 10, 90, 30]),
            FakeElement(name="丁", control_type="TextControl",
                        rect=[100, 10, 120, 30]),
        ])

    def test_ct01_filter_hits(self, estop, tmp_path, monkeypatch):
        ex, _ = _exec(estop, tmp_path, monkeypatch)
        ex._element_source = make_callable_source({FIXTURE_HWND: self._tree()})
        out = ex.get_ui_tree(FIXTURE_HWND, control_type="checkbox")
        names = [e["name"] for e in out["elements"]]
        assert sorted(names) == ["丙", "甲"]          # 仅两 CheckBox(直出)

    def test_ct02_filter_no_match_honest_empty(self, estop, tmp_path,
                                               monkeypatch):
        ex, _ = _exec(estop, tmp_path, monkeypatch)
        ex._element_source = make_callable_source({FIXTURE_HWND: self._tree()})
        out = ex.get_ui_tree(FIXTURE_HWND, control_type="radio")
        assert out["elements"] == []                  # 空集如实(直出)

    def test_ct13_truncated_tree_filter_honest(self, estop, tmp_path,
                                               monkeypatch):
        kids = [FakeElement(name=f"e{i}", control_type="ButtonControl",
                            rect=[10, 10, 30, 30]) for i in range(810)]
        kids.append(FakeElement(name="目标", control_type="CheckBoxControl",
                                rect=[40, 10, 60, 30]))
        ex, _ = _exec(estop, tmp_path, monkeypatch)
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=kids)})
        out = ex.get_ui_tree(FIXTURE_HWND, control_type="checkbox")
        assert out["truncated"] is True               # 截断继承(直出)


class TestClickElementByType:
    """TC-CT-03/04/05/14:类型+序号寻址。断言:替身坐标/异常直出。"""

    def _setup(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        cb1 = FakeElement(name="", control_type="CheckBoxControl",
                          rect=[120, 120, 160, 150], invokable=False,
                          setable=False)
        cb2 = FakeElement(name="", control_type="CheckBoxControl",
                          rect=[220, 220, 260, 250], invokable=False,
                          setable=False)
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[cb1, cb2])})
        return ex, rec, cb1, cb2

    def test_ct03_type_and_index_positive(self, estop, tmp_path, monkeypatch):
        ex, rec, cb1, cb2 = self._setup(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click_element",
                    "params": {"control_type": "CheckBox", "index": 1},
                    "binding_hwnd": FIXTURE_HWND})
        assert cb2.invoked == 1 and cb1.invoked == 0  # 第 2 个被激活(直出)

    def test_ct04_index_out_of_range_fails_closed(self, estop, tmp_path,
                                                  monkeypatch):
        ex, rec, _, _ = self._setup(estop, tmp_path, monkeypatch)
        from deskpilot.errors import ELEMENT_NOT_FOUND, ExecutorError
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element",
                        "params": {"control_type": "CheckBox", "index": 5},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == ELEMENT_NOT_FOUND
        assert rec.named("click") == []               # 零派发(直出)

    def test_ct05_type_and_som_id_conflict(self, estop, tmp_path,
                                           monkeypatch):
        ex, rec, _, _ = self._setup(estop, tmp_path, monkeypatch)
        from deskpilot.errors import INVALID_PARAMS, ExecutorError
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element",
                        "params": {"control_type": "CheckBox", "som_id": 1},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == INVALID_PARAMS
        assert rec.named("click") == []

    def test_ct14_name_and_type_joint_filter(self, estop, tmp_path,
                                             monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        btn_file = FakeElement(name="文件", control_type="ButtonControl",
                               rect=[120, 120, 160, 140], invokable=False,
                               setable=False)
        menu_file = FakeElement(name="文件", control_type="MenuItemControl",
                                rect=[220, 220, 260, 240], invokable=False,
                                setable=False)
        btn_edit = FakeElement(name="编辑", control_type="ButtonControl",
                               rect=[320, 320, 360, 340], invokable=False,
                               setable=False)
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[btn_file, menu_file,
                                                 btn_edit])})
        ex.execute({"tool": "click_element",
                    "params": {"name": "文件", "control_type": "MenuItem"},
                    "binding_hwnd": FIXTURE_HWND})
        assert menu_file.invoked == 1                 # 交集条目被激活(直出)
        assert btn_file.invoked == 0 and btn_edit.invoked == 0


class TestClickTextOffset:
    """TC-CT-07~11/15/16:文字锚点偏移。断言:替身坐标/异常直出。"""

    def _exec_with_ocr(self, estop, tmp_path, monkeypatch,
                       box=(200, 100, 260, 120)):
        ocr = lambda img: [{"text": "记住我",
                            "position": list(box)}]
        return _exec(estop, tmp_path, monkeypatch, ocr_engine=ocr)

    def test_ct07_offset_left_lands_left_of_label(self, estop, tmp_path,
                                                  monkeypatch):
        ex, rec = self._exec_with_ocr(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click_text",
                    "params": {"text": "记住我", "offset": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        c = rec.named("click")[-1][1]
        # 命中框 [200,100,260,120](图像像素)→ 虚拟 [300,200,360,220]
        # (FIXTURE_RECT 原点 100,100,缩放 1.0)
        assert (c[0], c[1]) == (300 - 28, 210)      # 左缘−28+垂直中线(直出)

    def test_ct08_four_directions(self, estop, tmp_path, monkeypatch):
        expect = {"left": (272, 210), "right": (388, 210),
                  "above": (330, 172), "below": (330, 248)}
        for direction, want in expect.items():
            ex, rec = self._exec_with_ocr(estop, tmp_path, monkeypatch)
            ex.execute({"tool": "click_text",
                        "params": {"text": "记住我", "offset": direction},
                        "binding_hwnd": FIXTURE_HWND})
            c = rec.named("click")[-1][1]
            assert (c[0], c[1]) == want, f"{direction}: {c} != {want}"

    def test_ct09_offset_out_of_window_fails_closed(self, estop, tmp_path,
                                                    monkeypatch):
        # 命中框 [0,100,60,120](图像)→ 虚拟 [100,200,160,220](贴窗左缘),
        # 左偏 28 → (72,210) 越出 FIXTURE_RECT(left=100)
        ex, rec = self._exec_with_ocr(estop, tmp_path, monkeypatch,
                                      box=(0, 100, 60, 120))
        from deskpilot.errors import OUT_OF_BOUNDS, ExecutorError
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_text",
                        "params": {"text": "记住我", "offset": "left"},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == OUT_OF_BOUNDS
        assert rec.named("click") == []

    def test_ct10_default_no_offset_unchanged(self, estop, tmp_path,
                                              monkeypatch):
        ex, rec = self._exec_with_ocr(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click_text",
                    "params": {"text": "记住我"},
                    "binding_hwnd": FIXTURE_HWND})
        c = rec.named("click")[-1][1]
        assert (c[0], c[1]) == (330, 210)             # 命中框中心(旧行为)

    def test_ct11_distance_custom(self, estop, tmp_path, monkeypatch):
        ex, rec = self._exec_with_ocr(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click_text",
                    "params": {"text": "记住我", "offset": "left",
                               "distance": 50},
                    "binding_hwnd": FIXTURE_HWND})
        c = rec.named("click")[-1][1]
        assert (c[0], c[1]) == (250, 210)             # 300−50(直出)

    def test_ct15_invalid_offset_and_distance_rejected(self, estop, tmp_path,
                                                       monkeypatch, policy):
        from deskpilot.errors import INVALID_PARAMS, ExecutorError
        from deskpilot.mcp_server import validate_call
        with pytest.raises(InvalidParamsError):
            validate_call("click_text",
                          {"token": "t", "text": "x", "offset": "leftside"},
                          policy)                     # enum 校验真实触发
        ex, rec = self._exec_with_ocr(estop, tmp_path, monkeypatch)
        for bad in (0, -5):
            with pytest.raises(ExecutorError) as ei:
                ex.execute({"tool": "click_text",
                            "params": {"text": "记住我", "offset": "left",
                                       "distance": bad},
                            "binding_hwnd": FIXTURE_HWND})
            assert ei.value.code == INVALID_PARAMS
        assert rec.named("click") == []               # 零派发(直出)

    def test_ct16_index_then_offset(self, estop, tmp_path, monkeypatch):
        ocr = lambda img: [{"text": "甲框", "position": [200, 100, 260, 120]},
                           {"text": "乙框", "position": [400, 300, 460, 320]}]
        ex, rec = _exec(estop, tmp_path, monkeypatch, ocr_engine=ocr)
        ex.execute({"tool": "click_text",
                    "params": {"text": "框", "match": "contains", "index": 1,
                               "offset": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        c = rec.named("click")[-1][1]
        assert (c[0], c[1]) == (500 - 28, 410)        # 先 index 再偏移(直出)


class TestSchemaShape:
    """TC-CT-06:schema 形态(直出)。"""

    def test_ct06_schema_shape(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        assert TOOL_SCHEMAS["get_ui_tree"]["optional"]["control_type"] == ("str",)
        ce = TOOL_SCHEMAS["click_element"]["optional"]
        assert ce["control_type"] == ("str",)
        assert ce["index"] == ("int",)
        ct = TOOL_SCHEMAS["click_text"]["optional"]
        assert ct["offset"] == ("enum", ["left", "right", "above", "below"])
        assert ct["distance"] == ("int",)


@pytest.mark.integration
class TestRealAnchorClick:
    """TC-CT-12(集成):文字锚点偏移点中桌面图标图形(终效应对照)。"""

    def test_ct12_anchor_lands_in_graphic_rect(self, audit_log, tmp_path):
        from deskpilot.approval import ApprovalManager
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.estop import EstopMonitor
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        from .conftest import FakeApprover, make_policy
        # 本用例在桌面上点 L2 工具,白名单需 explorer.exe=L2
        # (共享 policy fixture 中 explorer.exe=L1 是既有约束,不动它)
        policy = make_policy(audit_dir=str(tmp_path / "audit"),
                             whitelist={"notepad.exe": "L2",
                                        "explorer.exe": "L2"})
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"),
                            probe=DesktopProbe(), audit=audit_log)

        def _ocr_factory():                     # 与 main.py 装配同款
            from rapidocr_onnxruntime import RapidOCR
            from deskpilot.main import _build_ocr_engine
            return _build_ocr_engine(RapidOCR())
        executor.ocr_factory = _ocr_factory
        probe = DesktopProbe()
        bindings = BindingManager(probe, policy.binding_ttl, time.monotonic)
        approvals = ApprovalManager(FakeApprover(), policy.approval_ttl,
                                    time.monotonic)
        enforcement = Enforcement(policy, bindings, approvals, estop,
                                  executor, audit_log)
        ctx = ToolContext(policy=policy, enforcement=enforcement,
                          bindings=bindings, executor=executor,
                          audit=audit_log)
        d = HttpDaemon(ctx, port=0)
        d.start()

        def call(tool, params, timeout=60):
            body = json.dumps({"tool": tool, "params": params}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{d.port}/call", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            icons = call("list_desktop_icons", {})["data"]["items"]
            w = call("find_window", {"process": "explorer.exe"})
            pm = [x for x in w["data"]["windows"]
                  if x["title"] == "Program Manager"][0]
            a = call("attach", {"hwnd": pm["hwnd"]})
            # 环境自适应:窗口布局常变,挑一个「图形中心未被遮挡」的图标做锚点
            # ISS-0062 步骤 A:选图标同构逻辑收敛 envguard(纯重构)
            from .envguard import env_skip, pick_unoccluded_desktop_icon
            target_icon = pick_unoccluded_desktop_icon(icons)
            if target_icon is None:
                env_skip("当前桌面无可用的未遮挡图标"
                         "(桌面被窗口全覆盖时跳过,清桌面后跑)")
            g = target_icon["graphic_rect"]
            r = call("click_text", {"text": target_icon["display"],
                                    "offset": "above",
                                    "token": a["data"]["token"]})
            # 环境守卫(CI 红实证 2026-09-18):CI 桌面的异物窗(如 runner
            # 宿主控制台)压在图标文字区时,OCR 读出污染文本致文字找不到——
            # 环境,非 click_text 行为回归;清桌面/换 runner 后重跑
            if not r["ok"] and r.get("error_code") == "OCR_TEXT_NOT_FOUND":
                env_skip("桌面异物窗污染图标文字区, OCR 读不到干净标签")
            assert r["ok"], r.get("message")
            tx, ty = r["data"]["target"]
            assert g[0] <= tx <= g[2] and g[1] <= ty <= g[3], \
                f"锚点落点({tx},{ty})不在图形矩形{g}内"
        finally:
            d.stop()
