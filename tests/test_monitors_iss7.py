"""ISS-0007 双屏支持单元测试（问题单 §6 接口定义）。

层级：单元测试（允许打桩；断言在纯函数返回值/返回结构字段/替身调用记录，均直出）。
五要素：各类 docstring 标注。
入口（§6）：enum_monitors / screen_of_point / screen_of_rect /
build_window(target_screen) / _toast_placement(screen dict) /
screenshot fullscreen 的 coord_space+monitors / get_ui_tree coord_space /
_set_dpi_awareness。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from deskpilot.monitors import screen_of_point, screen_of_rect

PRIMARY = {"rect": (0, 0, 2560, 1440), "work_area": (0, 0, 2560, 1392),
           "is_primary": True}
LEFT = {"rect": (-2560, 0, 0, 1440), "work_area": (-2560, 0, 0, 1392),
        "is_primary": False}
RIGHT = {"rect": (2560, 0, 5120, 1440), "work_area": (2560, 0, 5120, 1392),
         "is_primary": False}
TWO_MON = [PRIMARY, LEFT]
TWO_MON_R = [PRIMARY, RIGHT]


# ---------- A 显示器几何判定 ----------

class TestScreenOf:
    """场景:点/矩形归属屏判定(含负坐标副屏)。
    断言:screen_of_point / screen_of_rect 返回的显示器 dict(直出)。"""

    def test_point_on_each_screen(self):
        assert screen_of_point(TWO_MON, 100, 100) is PRIMARY
        assert screen_of_point(TWO_MON, -100, 100) is LEFT

    def test_point_outside_all_returns_none(self):
        assert screen_of_point(TWO_MON, 3000, 100) is None

    def test_rect_picks_larger_overlap(self):
        # 跨两屏窗口:主屏内 900x400,副屏内 100x400 → 主屏
        rect = (-100, 100, 900, 500)
        assert screen_of_rect(TWO_MON, rect) is PRIMARY

    def test_rect_fully_on_left_screen(self):
        rect = (-2000, 100, -1000, 500)
        assert screen_of_rect(TWO_MON, rect) is LEFT

    def test_rect_no_overlap_returns_none(self):
        assert screen_of_rect(TWO_MON, (3000, 0, 4000, 100)) is None


# ---------- B 弹窗落位跟随目标屏 ----------

class TestToastPlacement:
    """场景:提供目标屏时 toast 落该屏右下角;单屏语义不变。
    断言:_toast_placement 返回的 (x, y_start, y_final)(直出)。"""

    def test_placement_on_left_screen(self):
        from deskpilot.approval_dialog import _toast_placement
        x, y_start, y_final = _toast_placement(LEFT, 480, 216)
        assert x == LEFT["work_area"][2] - 480 - 16     # 副屏右缘内侧
        assert y_start == LEFT["rect"][3]               # 屏外底部滑入起点
        assert y_final == LEFT["work_area"][3] - 216 - 48 - 16

    def test_placement_primary_unchanged(self):
        from deskpilot.approval_dialog import _toast_placement
        x, y_start, y_final = _toast_placement(PRIMARY, 480, 216)
        assert x == 2560 - 480 - 16
        assert y_final == 1392 - 216 - 48 - 16


class TestBuildWindowTargetScreen:
    """场景:build_window 传入目标屏时按其 work_area 落位(不打断建窗流程)。
    断言:落位函数被调用时的 screen 参数(替身记录直出)。"""

    def test_approval_uses_target_screen(self, monkeypatch):
        import deskpilot.approval_dialog as ad
        seen = {}

        class FakeWin:
            def __init__(self):
                self.geo = None

            def winfo_screenwidth(self):
                return 999999

            def winfo_screenheight(self):
                return 999999

            def title(self, *a):
                pass

            def overrideredirect(self, *a):
                pass

            def attributes(self, *a):
                pass

            def configure(self, *a, **k):
                pass

            def geometry(self, g):
                self.geo = g

            def after(self, *a, **k):
                pass

            def bind(self, *a, **k):
                pass

        monkeypatch.setattr(ad.tk, "Toplevel", lambda parent: FakeWin())
        monkeypatch.setattr(ad.tk, "Frame", lambda *a, **k: _FakeWidget())
        monkeypatch.setattr(ad.tk, "Label", _fake_label)
        monkeypatch.setattr(ad.tk, "Button", _fake_button)

        win = ad.build_window(object(), "测试", "/tmp/r.txt", 5,
                              target_screen=LEFT)
        x = int(win.geo.split("+")[1])
        assert x == LEFT["work_area"][2] - 480 - 16


def _FakeWidget():
    class W:
        def pack(self, *a, **k):
            pass

        def place(self, *a, **k):
            pass

        def bind(self, *a, **k):
            pass

        def focus_set(self):
            pass

        def config(self, *a, **k):
            pass

    return W()


def _fake_label(*a, **k):
    return _FakeWidget()


def _fake_button(*a, **k):
    return _FakeWidget()


# ---------- C 坐标系声明 ----------

class TestCoordSpaceDeclaration:
    """场景:fullscreen 截图与 get_ui_tree 返回坐标系声明与屏列表。
    断言:返回结构的 coord_space / monitors 字段(直出)。"""

    def test_fullscreen_declares_coord_space_and_monitors(self, m3_executor):
        from PIL import Image
        m3_executor._shot_fn = lambda region: Image.new("RGB", (4, 4))
        r = m3_executor.screenshot("fullscreen")
        assert r["coord_space"] == "virtual_desktop"
        assert isinstance(r["monitors"], list) and len(r["monitors"]) >= 1

    def test_ui_tree_declares_coord_space(self, m3_executor):
        from .test_elements import FakeElement
        from .conftest import FIXTURE_HWND
        m3_executor._element_source = lambda hwnd: FakeElement(children=[])
        r = m3_executor.get_ui_tree(FIXTURE_HWND)
        assert r["coord_space"] == "virtual_desktop"


# ---------- D DPI 感知回退 ----------

class TestDpiAwareness:
    """场景:优先 Per-Monitor V2,失败回退 V1,再败不阻断启动。
    断言:_set_dpi_awareness 返回所用形态(直出)。"""

    def test_pmv2_success(self, monkeypatch):
        from deskpilot import main as m
        monkeypatch.setattr("ctypes.windll.user32.SetProcessDpiAwarenessContext",
                            lambda v: True, raising=False)
        assert m._set_dpi_awareness() == "pmv2"

    def test_fallback_to_v1(self, monkeypatch):
        from deskpilot import main as m
        monkeypatch.setattr("ctypes.windll.user32.SetProcessDpiAwarenessContext",
                            lambda v: False, raising=False)
        monkeypatch.setattr("ctypes.windll.user32.SetProcessDPIAware",
                            lambda: True, raising=False)
        assert m._set_dpi_awareness() == "v1"

    def test_all_fail_returns_none_not_raise(self, monkeypatch):
        from deskpilot import main as m
        monkeypatch.setattr("ctypes.windll.user32.SetProcessDpiAwarenessContext",
                            lambda v: (_ for _ in ()).throw(OSError()),
                            raising=False)
        monkeypatch.setattr("ctypes.windll.user32.SetProcessDPIAware",
                            lambda: (_ for _ in ()).throw(OSError()),
                            raising=False)
        assert m._set_dpi_awareness() == "none"


@pytest.fixture
def fake_probe():
    p = __import__("tests.conftest", fromlist=["FakeProbe"]).FakeProbe()
    p.rects = {999999: (100, 100, 800, 600)}
    return p


@pytest.fixture
def m3_executor(estop, tmp_path, clock, fake_probe):
    from deskpilot.executor.core import Executor
    return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                    wait_timeout_max=5.0, clock=clock, probe=fake_probe)
