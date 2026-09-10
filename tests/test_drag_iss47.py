"""ISS-0047 drag 终点校验虚拟桌面全域单元测试(TC-47-01~06,问题单 §2 方案A)。

层级:单元(真 Executor + 替身 pyautogui + 替身显示器枚举接缝)。
入口(设计):Executor.execute("drag")(公开入口);校验在派发前(零派发断言)。
断言值来源:pyautogui 替身调用记录 / ExecutorError.code / execute 返回值——直出。

语义钉:
- start 仍在绑定窗内(防误射不变);
- end 允许虚拟桌面任意点(逐屏矩形判定——并集包围盒死角仍拒);
- end 越出所有屏 → OUT_OF_BOUNDS(fail-closed 保留);
- 显示器枚举失败/为空 → INTERNAL_ERROR(fail-closed,不静默放行)。

测试设计(五要素):
- TC-47-01 场景=终点副屏(越窗但在屏内)放行;前提=双屏替身
  [(0,0,1920,1080),(1920,0,3840,1080)],绑定窗 (100,100,800,600);
  步骤=drag (200,200)→(2880,300);预期=ok 且 down/up 派发;断言=rec+返回值。
- TC-47-02 场景=终点不在任何屏;步骤=end (5000,300);预期=OUT_OF_BOUNDS
  零派发;断言=code + rec.calls 空。
- TC-47-03 场景=起点窗外仍拒;步骤=start (50,50);预期=OUT_OF_BOUNDS 零派发。
- TC-47-04 场景=负坐标副屏(屏在主屏左侧);前提=[(0,0,1920,1080),
  (-1920,0,0,1080)];步骤=end (-500,300);预期=放行。
- TC-47-05 场景=并集包围盒死角;前提=错位屏 [(0,0,1920,1080),
  (1920,1080,3840,2160)];步骤=end (100,1500)(包围盒内、任何屏外);
  预期=OUT_OF_BOUNDS 零派发(逐屏判定钉)。
- TC-47-06 场景=枚举失败;前提=接缝抛 OSError;预期=INTERNAL_ERROR 零派发。
"""

from __future__ import annotations

import time

import pytest

from deskpilot.errors import (INTERNAL_ERROR, OUT_OF_BOUNDS, ExecutorError)
from deskpilot.executor.core import Executor

from .conftest import FIXTURE_HWND, FakeProbe
from .test_mouse_req01 import _Rec

_DUAL = [{"rect": (0, 0, 1920, 1080)},
         {"rect": (1920, 0, 3840, 1080)}]


def _exec(estop, tmp_path, monkeypatch, monitors):
    rec = _Rec()
    import deskpilot.executor.core as core_mod
    for fn in ("mouseDown", "mouseUp", "moveTo", "click", "hscroll", "scroll"):
        monkeypatch.setattr(core_mod.pyautogui, fn, rec.fn(fn))
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  clock=time.monotonic, probe=FakeProbe())
    ex._check_occlusion = lambda *a, **k: None
    if monitors is not None:
        ex._enum_monitors = lambda: monitors
    rec.calls.clear()          # 构造期启动抬键清扫从 0 计(同 test_mouse_req01)
    return ex, rec


class TestDragEndVirtualDesktop:
    def test_tc47_01_end_on_secondary_screen_allowed(self, estop, tmp_path,
                                                     monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        out = ex.execute({"tool": "drag",
                          "params": {"start": [200, 200], "end": [2880, 300]},
                          "binding_hwnd": FIXTURE_HWND})
        assert out["status"] == "ok"
        assert len(rec.named("mouseDown")) == 1
        assert len(rec.named("mouseUp")) == 1

    def test_tc47_02_end_beyond_all_screens_rejected(self, estop, tmp_path,
                                                     monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "drag",
                        "params": {"start": [200, 200], "end": [5000, 300]},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == OUT_OF_BOUNDS
        assert rec.calls == []                        # 校验在派发前

    def test_tc47_03_start_outside_window_still_rejected(self, estop, tmp_path,
                                                         monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "drag",
                        "params": {"start": [50, 50], "end": [2880, 300]},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == OUT_OF_BOUNDS
        assert rec.calls == []

    def test_tc47_04_negative_origin_secondary_allowed(self, estop, tmp_path,
                                                       monkeypatch):
        mons = [{"rect": (0, 0, 1920, 1080)},
                {"rect": (-1920, 0, 0, 1080)}]       # 副屏在主屏左侧
        ex, rec = _exec(estop, tmp_path, monkeypatch, mons)
        out = ex.execute({"tool": "drag",
                          "params": {"start": [200, 200], "end": [-500, 300]},
                          "binding_hwnd": FIXTURE_HWND})
        assert out["status"] == "ok"
        assert len(rec.named("mouseDown")) == 1

    def test_tc47_05_union_bbox_deadzone_rejected(self, estop, tmp_path,
                                                  monkeypatch):
        mons = [{"rect": (0, 0, 1920, 1080)},
                {"rect": (1920, 1080, 3840, 2160)}]  # 右下错位排列
        ex, rec = _exec(estop, tmp_path, monkeypatch, mons)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "drag",
                        "params": {"start": [200, 200], "end": [100, 1500]},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == OUT_OF_BOUNDS          # 包围盒内但任何屏外
        assert rec.calls == []

    def test_tc47_06_enum_failure_fail_closed(self, estop, tmp_path,
                                              monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch, None)

        def _boom():
            raise OSError("display query down")
        ex._enum_monitors = _boom
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "drag",
                        "params": {"start": [200, 200], "end": [2880, 300]},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == INTERNAL_ERROR
        assert rec.calls == []
