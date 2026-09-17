"""ISS-0088 深度截断一致性测试(dt01~dt09,问题单 §6 v0.2 补立)。

层级:dt01~dt06/dt08/dt09 单元(FakeElement 替身树+元素源接缝,允许打桩,
断言在响应体/替身记录直出);dt07 集成(真 mspaint+真 UIA,禁桩,断言在
响应体直出;@pytest.mark.integration)。

入口(设计):Executor.execute(click_element)/get_ui_tree/get_clickable_map
公开入口。

断言出处:status/element=execute 响应直出;elements/truncated/entries=
get_ui_tree/get_clickable_map 响应直出;invoked=FakeElement 替身记录直出。

红态预期(现状):dt01/dt02/dt04a/dt09 深度>8 定位链不可见→NOT_FOUND 红;
dt03 名字路径命中外壳 ListItem(非 Button)→红;dt05 嵌套同名 AMBIGUOUS→红;
dt04b/dt06/dt08 红期即绿(边界钉:统一不过冲/兄弟歧义不变/800 上限不动)。
"""

from __future__ import annotations

import subprocess
import time

import pytest
from PIL import Image

from deskpilot.errors import (ELEMENT_AMBIGUOUS, ELEMENT_NOT_FOUND,
                              ExecutorError)
from deskpilot.executor import Executor

from .conftest import FIXTURE_HWND, FakeProbe
from .test_elements import FakeElement, make_callable_source


@pytest.fixture
def ex(estop, tmp_path, clock):
    """真 Executor + FakeProbe(镜像 test_elements real_executor 装配)。"""
    return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                    wait_timeout_max=5.0, clock=clock, probe=FakeProbe())


def _wrap(depth: int, leaf: FakeElement) -> FakeElement:
    """造深度链:根 depth0,每包一层 +1,叶子落于 depth。"""
    node = leaf
    for _ in range(depth):
        node = FakeElement(control_type="PaneControl", children=[node])
    return node


def _click(ex, hwnd, params):
    return ex.execute({"tool": "click_element", "params": params,
                       "binding_hwnd": hwnd})


class TestDeepTreeReachable:
    """dt01/dt02/dt04a:加深后定位链与取树同口径(方向①)。"""

    def test_dt01_depth9_leaf_clickable_by_name(self, ex):
        """dt01(单元):深度 9 叶子名字路径可点。
        红态(现状):_iter_summaries 截断 depth>8 → ELEMENT_NOT_FOUND。"""
        leaf = FakeElement(name="深层按钮", control_type="ButtonControl",
                           rect=(110, 110, 160, 140))
        ex._element_source = make_callable_source({FIXTURE_HWND: _wrap(9, leaf)})
        r = _click(ex, FIXTURE_HWND, {"name": "深层按钮"})
        assert r["status"] == "ok"              # 响应直出
        assert leaf.invoked == 1                # 替身记录直出

    def test_dt02_depth9_leaf_clickable_by_type_and_name(self, ex):
        """dt02(单元):深度 9 叶子 类型+名字 路径可点(事故路径)。
        红态(现状):深度 9 不进解析链 → ELEMENT_NOT_FOUND。"""
        leaf = FakeElement(name="深层按钮", control_type="ButtonControl",
                           rect=(110, 110, 160, 140))
        ex._element_source = make_callable_source({FIXTURE_HWND: _wrap(9, leaf)})
        r = _click(ex, FIXTURE_HWND,
                   {"name": "深层按钮", "control_type": "ButtonControl"})
        assert r["status"] == "ok"
        assert leaf.invoked == 1

    def test_dt04a_depth10_leaf_reachable(self, ex):
        """dt04a(单元):统一上界 10——深度 10 叶子可达。
        红态(现状):depth 10 > 8 → NOT_FOUND。"""
        leaf = FakeElement(name="深十", control_type="ButtonControl",
                           rect=(110, 110, 160, 140))
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: _wrap(10, leaf)})
        r = _click(ex, FIXTURE_HWND, {"name": "深十"})
        assert r["status"] == "ok"
        assert leaf.invoked == 1


class TestNestedSameName:
    """dt03/dt05/dt06:嵌套同名歧义化解(验收「同目标同结果」的机制)。"""

    def test_dt03_nested_same_name_same_target(self, ex):
        """dt03(单元,验收镜像):ListItem「矩形」(depth8 外壳)⊃
        Button「矩形」(depth9)——树见两者(既有);类型路径与名字路径
        **同目标同结果**=都命中内层 Button。
        红态(现状):类型路径 NOT_FOUND;名字路径命中外壳
        (element.control_type=="ListItemControl")。"""
        button = FakeElement(name="矩形", control_type="ButtonControl",
                             rect=(110, 82, 190, 102))
        shell = FakeElement(name="矩形", control_type="ListItemControl",
                            rect=(100, 80, 200, 110), children=[button])
        ex._element_source = make_callable_source({FIXTURE_HWND: _wrap(8, shell)})

        tree = ex.get_ui_tree(FIXTURE_HWND)
        same = [n for n in tree["elements"] if n["name"] == "矩形"]
        assert len(same) == 2                   # 树见两者(响应直出,既有不变)

        r1 = _click(ex, FIXTURE_HWND,
                    {"name": "矩形", "control_type": "ButtonControl"})
        assert r1["status"] == "ok"
        assert r1["element"]["control_type"] == "ButtonControl"   # 响应直出

        r2 = _click(ex, FIXTURE_HWND, {"name": "矩形"})
        assert r2["status"] == "ok"
        assert r2["element"]["control_type"] == "ButtonControl"   # 同目标
        assert button.invoked == 2              # 两路径同点按钮(替身记录)
        assert shell.invoked == 0               # 外壳零调用(替身记录)

    def test_dt05_shallow_nested_resolves_innermost(self, ex):
        """dt05(单元,行为变化明示):浅层嵌套同名 Button⊃Text「保存」
        → 解析最内层(矩形内含+深度更深者胜;Invoke-first 对 Text 有效)。
        红态(现状):两匹配 → ELEMENT_AMBIGUOUS。"""
        text = FakeElement(name="保存", control_type="TextControl",
                           rect=(120, 110, 180, 130))
        button = FakeElement(name="保存", control_type="ButtonControl",
                             rect=(100, 100, 200, 140), children=[text])
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[button])})
        r = _click(ex, FIXTURE_HWND, {"name": "保存"})
        assert r["status"] == "ok"
        assert text.invoked == 1                # 最内层被点(替身记录)
        assert button.invoked == 0              # 祖先让位(替身记录)

    def test_dt06_sibling_same_name_stays_ambiguous(self, ex):
        """dt06(单元,防过修钉):无内含关系的兄弟同名 → 歧义报错不变。
        红期即绿(边界钉)。"""
        a = FakeElement(name="保存", rect=(110, 110, 160, 140))
        b = FakeElement(name="保存", rect=(200, 110, 250, 140))
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[a, b])})
        with pytest.raises(ExecutorError) as ei:
            _click(ex, FIXTURE_HWND, {"name": "保存"})
        assert ei.value.code == ELEMENT_AMBIGUOUS   # 异常码直出


class TestBoundaryPins:
    """dt04b/dt08:统一上界不过冲;800 防爆炸上限不动。"""

    def test_dt04b_depth11_invisible_on_both_surfaces(self, ex):
        """dt04b(单元):深度 11 叶子取树与定位链同不可见(统一截断,
        不过冲)。红期即绿(边界钉)。"""
        leaf = FakeElement(name="深十一", control_type="ButtonControl",
                           rect=(110, 110, 160, 140))
        ex._element_source = make_callable_source(
            {FIXTURE_HWND: _wrap(11, leaf)})
        tree = ex.get_ui_tree(FIXTURE_HWND)
        assert "深十一" not in [n["name"] for n in tree["elements"]]  # 响应直出
        with pytest.raises(ExecutorError) as ei:
            _click(ex, FIXTURE_HWND, {"name": "深十一"})
        assert ei.value.code == ELEMENT_NOT_FOUND

    def test_dt08_node_cap_800_unchanged(self, ex):
        """dt08(单元,§5 约束):801 并列子节点 → 截断标志与 800 上限不变。
        红期即绿(约束钉)。"""
        tree = FakeElement(children=[FakeElement(control_type="PaneControl")
                                     for _ in range(801)])
        ex._element_source = make_callable_source({FIXTURE_HWND: tree})
        r = ex.get_ui_tree(FIXTURE_HWND)
        assert r["truncated"] is True           # 响应直出
        assert len(r["elements"]) <= 800


class TestSomNumberingDeepened:
    """dt09:SoM 编号面随定位链一起加深(方向① 的 SoM 面)。"""

    def test_dt09_som_numbers_depth9_leaf(self, ex):
        """dt09(单元):深度 9 叶子进入 SoM 编号空间(get_clickable_map
        与定位链同源 _iter_summaries)。_shot_fn 为 Executor 公开测试接缝
        (core.py:756 注释);落盘进 tmp audit 目录。
        红态(现状):深度 9 不编号 → entries 无此名。"""
        leaf = FakeElement(name="深层按钮", control_type="ButtonControl",
                           rect=(110, 110, 160, 140))
        ex._element_source = make_callable_source({FIXTURE_HWND: _wrap(9, leaf)})
        ex._shot_fn = lambda region: Image.new(
            "RGB", (region["width"], region["height"]))
        r = ex.get_clickable_map(FIXTURE_HWND)
        assert any(e["name"] == "深层按钮" for e in r["entries"])  # 响应直出


@pytest.mark.integration
class TestRealMspaint:
    """dt07:真画图形状钮(验收镜像;禁桩;真 UIA/真执行)。"""

    def test_dt07_real_mspaint_typed_path_hits_button(
            self, policy, audit_log, tmp_path):
        """dt07(集成):真 mspaint 树上 depth≥9 的 ButtonControl 形状钮,
        类型路径点击命中 ButtonControl(非外壳 ListItem)。
        环境守卫:mspaint 不可用/树上无深度≥9 具名 ButtonControl → skip。
        红态(现状):类型路径 ELEMENT_NOT_FOUND(问题单 §1 实测形态)。"""
        from deskpilot.executor import DesktopProbe
        from deskpilot.estop import EstopMonitor

        probe = DesktopProbe()
        before = {w["hwnd"] for w in probe.find_windows(process="mspaint.exe")}
        try:
            proc = subprocess.Popen(["mspaint.exe"])
        except OSError:
            pytest.skip("环境守卫:mspaint.exe 不可用")
        hwnd = None
        try:
            for _ in range(60):
                new = [w for w in probe.find_windows(process="mspaint.exe")
                       if w["hwnd"] not in before and w.get("title")]
                if new:
                    hwnd = new[0]["hwnd"]
                    break
                time.sleep(0.25)
            if hwnd is None:
                pytest.skip("环境守卫:mspaint 窗口未出现")
            estop = EstopMonitor(policy.corner_hold_ms, time.monotonic,
                                 audit_log)
            ex = Executor(estop, str(tmp_path / "audit"), probe=probe)
            tree = ex.get_ui_tree(hwnd)
            targets = [n for n in tree["elements"]
                       if n["control_type"] == "ButtonControl"
                       and n["name"] and n["depth"] >= 9]
            if not targets:
                pytest.skip("环境守卫:画图树上无深度≥9 具名 ButtonControl")
            t0 = targets[0]
            r = ex.execute({"tool": "click_element",
                            "params": {"name": t0["name"],
                                       "control_type": "ButtonControl"},
                            "binding_hwnd": hwnd})
            assert r["status"] == "ok"                  # 响应直出
            assert r["element"]["control_type"] == "ButtonControl"  # 同目标
        finally:
            proc.terminate()
