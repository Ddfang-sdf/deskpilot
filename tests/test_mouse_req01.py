"""REQ-001 鼠标能力补全测试(TC-MOUSE-01~18,测试设计 v0.1)。

层级:单元(真 Executor/tracker 本体;替身仅 pyautogui/时钟/睡眠/OS 接缝)
+ 形态(注册表直读)。
入口(设计):Executor.execute(mouse_down/mouse_up/hold/click/drag/scroll/
click_text)/ mousehold.PressedTracker/TOOL_SCHEMAS/models 注册表。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from deskpilot.errors import InvalidParamsError
from deskpilot.executor import core as core_mod
from deskpilot.executor import Executor

from deskpilot.audit_events import (
    EV_MOUSE_KEY_SELF_HEAL,
    EV_STARTUP_KEY_SWEEP,
    EV_STARTUP_KEY_SWEEP_FAILSAFE)
from .conftest import FIXTURE_HWND, FakeProbe


class _Rec:
    """pyautogui 调用记录替身。"""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def fn(self, name):
        def f(*a, **k):
            self.calls.append((name, a, k))
        return f

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def _audit_events(audit_dir: str) -> list[dict]:
    out = []
    for f in sorted(Path(audit_dir).glob("**/*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _exec(estop, tmp_path, monkeypatch, clock=None, probe=None,
          ocr_engine=None, clear_after=True, audit=None):
    """真 Executor + 替身 pyautogui;返回 (executor, rec)。
    P3 起构造期有启动抬键清扫,默认清空记录从 0 计(TC-16 例外)。"""
    rec = _Rec()
    for fn in ("mouseDown", "mouseUp", "moveTo", "click", "hscroll", "scroll"):
        monkeypatch.setattr(core_mod.pyautogui, fn, rec.fn(fn))
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  clock=clock or time.monotonic,
                  probe=probe or FakeProbe(), ocr_engine=ocr_engine,
                  audit=audit)
    ex._check_occlusion = lambda *a, **k: None      # 单元层遮挡打桩(同 ct08)
    if clear_after:
        rec.calls.clear()
    return ex, rec


class TestMouseVerbs:
    """TC-MOUSE-01~09/17:动词层扩展。断言:替身调用记录直出。"""

    def test_mouse01_right_click(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click",
                    "params": {"x": 200, "y": 200, "button": "right"},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("click")[-1][2]["button"] == "right"

    def test_mouse02_middle_click(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click",
                    "params": {"x": 200, "y": 200, "button": "middle"},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("click")[-1][2]["button"] == "middle"

    def test_mouse03_double_click(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click",
                    "params": {"x": 200, "y": 200, "clicks": 2},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("click")[-1][2]["clicks"] == 2

    def test_mouse04_invalid_button_zero_dispatch(self, estop, tmp_path,
                                                  monkeypatch, policy):
        from deskpilot.mcp_server import validate_call
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        with pytest.raises(InvalidParamsError):
            validate_call("click",
                          {"token": "t", "x": 1, "y": 1, "button": "shift"},
                          policy)                   # enum 校验真实触发(带 token)
        assert rec.calls == []                        # 零派发(直出)

    def test_mouse05_right_drag(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "drag",
                    "params": {"start": [200, 200], "end": [400, 400],
                               "button": "right"},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("mouseDown")[0][2]["button"] == "right"
        assert rec.named("mouseUp")[-1][2]["button"] == "right"

    def test_mouse06_hold_sequence(self, estop, tmp_path, monkeypatch):
        rec_sleep = []
        monkeypatch.setattr(core_mod.time, "sleep",
                            lambda s: rec_sleep.append(s))
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        out = ex.execute({"tool": "hold",
                          "params": {"duration_ms": 500},
                          "binding_hwnd": FIXTURE_HWND})
        seq = [c[0] for c in rec.calls]
        assert seq == ["mouseDown", "mouseUp"]        # down/up 各恰一次
        assert rec_sleep == [0.5]                     # 500ms 一次等待
        assert out["held_ms"] == 500                  # 假钟/实计直出

    def test_mouse07_hold_exception_still_releases(self, estop, tmp_path,
                                                   monkeypatch):
        def boom(s):
            raise RuntimeError("睡眠异常")
        monkeypatch.setattr(core_mod.time, "sleep", boom)
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        from deskpilot.errors import INTERNAL_ERROR, ExecutorError
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "hold",
                        "params": {"duration_ms": 500},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == INTERNAL_ERROR        # 异常透出(ISS-0009 §6 C 收敛)
        assert len(rec.named("mouseUp")) == 1         # finally 必抬(直出)

    def test_mouse08_hscroll_both_directions(self, estop, tmp_path,
                                             monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "scroll",
                    "params": {"direction": "left", "amount": 3},
                    "binding_hwnd": FIXTURE_HWND})
        ex.execute({"tool": "scroll",
                    "params": {"direction": "right", "amount": 3},
                    "binding_hwnd": FIXTURE_HWND})
        hs = rec.named("hscroll")
        assert hs[0][1][0] == -3                      # left=负向(args 直出)
        assert hs[1][1][0] == 3                       # right=正向(直出)

    def test_mouse09_click_text_double(self, estop, tmp_path, monkeypatch):
        ocr = lambda img: [{"text": "目标",
                            "position": [200, 200, 210, 210]}]
        ex, rec = _exec(estop, tmp_path, monkeypatch, ocr_engine=ocr)
        ex.execute({"tool": "click_text",
                    "params": {"text": "目标", "clicks": 2},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("click")[-1][2]["clicks"] == 2

    def test_mouse09b_click_text_middle(self, estop, tmp_path, monkeypatch):
        ocr = lambda img: [{"text": "目标",
                            "position": [200, 200, 210, 210]}]
        ex, rec = _exec(estop, tmp_path, monkeypatch, ocr_engine=ocr)
        ex.execute({"tool": "click_text",
                    "params": {"text": "目标", "button": "middle"},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("click")[-1][2]["button"] == "middle"

    def test_mouse19_clicks_three_and_bounds(self, estop, tmp_path,
                                             monkeypatch):
        from deskpilot.errors import INVALID_PARAMS, ExecutorError
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "click",
                    "params": {"x": 200, "y": 200, "clicks": 3},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("click")[-1][2]["clicks"] == 3
        for bad in (0, 4):
            with pytest.raises(ExecutorError) as ei:
                ex.execute({"tool": "click",
                            "params": {"x": 200, "y": 200, "clicks": bad},
                            "binding_hwnd": FIXTURE_HWND})
            assert ei.value.code == INVALID_PARAMS
        assert len(rec.named("click")) == 1           # 越界零派发(直出)

    def test_mouse17_hold_duration_bounds(self, estop, tmp_path,
                                          monkeypatch):
        """range 校验在执行层(validate_call 只查类型)——经 execute 路径断言。"""
        from deskpilot.errors import INVALID_PARAMS, ExecutorError
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        for bad in (0, 30001):
            with pytest.raises(ExecutorError) as ei:
                ex.execute({"tool": "hold",
                            "params": {"duration_ms": bad},
                            "binding_hwnd": FIXTURE_HWND})
            assert ei.value.code == INVALID_PARAMS
        assert rec.calls == []                        # 零派发(直出)


class TestMouseSchema:
    """TC-MOUSE-10:模式注册形态(直出)。"""

    def test_mouse10_schema_shape(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        from deskpilot.models import BINDING_REQUIRED_TOOLS, TOOL_LEVELS
        for t in ("mouse_down", "mouse_up"):
            s = TOOL_SCHEMAS[t]
            assert s["required"]["button"] == ("enum",
                                               ["left", "right", "middle"])
            assert TOOL_LEVELS[t] == "L2"
            assert t in BINDING_REQUIRED_TOOLS
        h = TOOL_SCHEMAS["hold"]
        assert h["required"]["duration_ms"] == ("int",)
        assert h["optional"]["button"] == ("enum", ["left", "right", "middle"])
        assert TOOL_LEVELS["hold"] == "L2"
        assert "hold" in BINDING_REQUIRED_TOOLS
        assert TOOL_SCHEMAS["click"]["optional"]["button"] == (
            "enum", ["left", "right", "middle"])
        assert TOOL_SCHEMAS["click"]["optional"]["clicks"] == ("int",)
        assert TOOL_SCHEMAS["drag"]["optional"]["button"] == (
            "enum", ["left", "right", "middle"])
        assert "left" in TOOL_SCHEMAS["scroll"]["required"]["direction"][1]
        assert "right" in TOOL_SCHEMAS["scroll"]["required"]["direction"][1]
        assert TOOL_SCHEMAS["click_text"]["optional"]["clicks"] == ("int",)


class TestMousePrimitives:
    """TC-MOUSE-11/12/15:原语层。断言:替身序列+快照+返回直出。"""

    def test_mouse11_left_right_chord(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        r1 = ex.execute({"tool": "mouse_down",
                         "params": {"button": "left"},
                         "binding_hwnd": FIXTURE_HWND})
        r2 = ex.execute({"tool": "mouse_down",
                         "params": {"button": "right"},
                         "binding_hwnd": FIXTURE_HWND})
        assert set(r2["pressed"]) == {"left", "right"}   # 两键共存(直出)
        u1 = ex.execute({"tool": "mouse_up",
                         "params": {"button": "right"},
                         "binding_hwnd": FIXTURE_HWND})
        assert u1["released"] is True
        u2 = ex.execute({"tool": "mouse_up",
                         "params": {"button": "left"},
                         "binding_hwnd": FIXTURE_HWND})
        assert u2["released"] is True
        seq = [c[0] for c in rec.calls]
        assert seq == ["mouseDown", "mouseDown", "mouseUp", "mouseUp"]

    def test_mouse12_hold_drag_combo(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "mouse_down",
                    "params": {"button": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        ex.execute({"tool": "move", "params": {"x": 300, "y": 300},
                    "binding_hwnd": FIXTURE_HWND})
        ex.execute({"tool": "mouse_up",
                    "params": {"button": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        seq = [c[0] for c in rec.calls]
        assert seq == ["mouseDown", "moveTo", "mouseUp"]

    def test_mouse15_up_idempotent(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        out = ex.execute({"tool": "mouse_up",
                          "params": {"button": "left"},
                          "binding_hwnd": FIXTURE_HWND})
        assert out["released"] is False               # 无按下 no-op(直出)
        assert rec.named("mouseUp") == []             # 零物理动作(直出)

    def test_mouse20_down_same_button_idempotent(self, estop, tmp_path,
                                                 monkeypatch):
        """同键重复 down:物理两次(与实物一致),按下表不新增(时刻覆盖)。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "mouse_down",
                    "params": {"button": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        out = ex.execute({"tool": "mouse_down",
                          "params": {"button": "left"},
                          "binding_hwnd": FIXTURE_HWND})
        assert len(rec.named("mouseDown")) == 2       # 物理两次(直出)
        assert out["pressed"] == ["left"]             # 表内仍一条(直出)

    def test_mouse21_hold_with_button(self, estop, tmp_path, monkeypatch):
        rec_sleep = []
        monkeypatch.setattr(core_mod.time, "sleep",
                            lambda s: rec_sleep.append(s))
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "hold",
                    "params": {"duration_ms": 200, "button": "right"},
                    "binding_hwnd": FIXTURE_HWND})
        assert rec.named("mouseDown")[0][2]["button"] == "right"
        assert rec.named("mouseUp")[-1][2]["button"] == "right"

    def test_mouse22_primitives_no_evidence_shots(self, estop, tmp_path,
                                                  monkeypatch):
        """MOUSE-14:原语 down/up 只记审计不拍图;动词层照常拍。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        d = ex.execute({"tool": "mouse_down",
                        "params": {"button": "left"},
                        "binding_hwnd": FIXTURE_HWND})
        assert d["before_shot"] == "" and d["after_shot"] == ""
        u = ex.execute({"tool": "mouse_up",
                        "params": {"button": "left"},
                        "binding_hwnd": FIXTURE_HWND})
        assert u["before_shot"] == "" and u["after_shot"] == ""
        c = ex.execute({"tool": "click",
                        "params": {"x": 200, "y": 200},
                        "binding_hwnd": FIXTURE_HWND})
        assert c["before_shot"] and c["after_shot"]   # 动词层照常(直出)


class TestPressedTrackerDirect:
    """TC-MOUSE-23:tracker 本体直测(详设 §3.1 契约,直出)。"""

    def test_tracker_contract(self):
        from deskpilot.executor.mousehold import PressedTracker
        from .conftest import FakeClock
        clock = FakeClock()
        t = PressedTracker(clock=clock)
        t.press("left")
        t.press("left")                               # 幂等:不新增
        assert t.snapshot() == ["left"]
        t.press("right")
        assert set(t.snapshot()) == {"left", "right"}
        clock.advance(31)
        assert t.stale()                              # 超龄判定(直出)
        assert t.release("left") is True
        assert t.release("left") is False             # 二次 release 幂等
        assert t.release_all() == ["right"]
        assert t.snapshot() == []                     # 全抬后必空(不变式)


class TestMouseSafetyNet:
    """TC-MOUSE-13/14/16/18:安全网。断言:替身计数+审计+快照直出。"""

    def test_mouse13_estop_force_release(self, estop, tmp_path, monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        ex.execute({"tool": "mouse_down",
                    "params": {"button": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        ex.execute({"tool": "mouse_down",
                    "params": {"button": "right"},
                    "binding_hwnd": FIXTURE_HWND})
        rec.calls.clear()
        estop.on_trigger_hotkey()                     # 冻结触发
        assert len(rec.named("mouseUp")) == 2         # 全部按下键被抬
        assert ex._mouse.snapshot() == []             # 按下表清空(直出)

    def test_mouse14_watchdog_selfheal(self, estop, tmp_path, monkeypatch,
                                       clock, audit_log):
        ex, rec = _exec(estop, tmp_path, monkeypatch, clock=clock,
                        audit=audit_log)
        ex.execute({"tool": "mouse_down",
                    "params": {"button": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        clock.advance(31)                             # 超龄(>30s)
        ex._mouse_watchdog_tick()                     # 手动驱动一次 tick
        assert len(rec.named("mouseUp")) == 1
        events = _audit_events(str(tmp_path / "audit"))
        heals = [e for e in events if e.get("event") == EV_MOUSE_KEY_SELF_HEAL]
        assert heals and "left" in heals[-1].get("detail", "")

    def test_mouse14b_watchdog_fresh_press_no_action(self, estop, tmp_path,
                                                     monkeypatch, clock,
                                                     audit_log):
        """负向:未超龄按下,tick 零动作零审计。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch, clock=clock,
                        audit=audit_log)
        ex.execute({"tool": "mouse_down",
                    "params": {"button": "left"},
                    "binding_hwnd": FIXTURE_HWND})
        clock.advance(10)                             # 未超龄(<30s)
        ex._mouse_watchdog_tick()
        assert rec.named("mouseUp") == []             # 零抬起(直出)
        assert ex._mouse.snapshot() == ["left"]       # 按下保留(直出)
        events = _audit_events(str(tmp_path / "audit"))
        assert not [e for e in events if e.get("event") == EV_MOUSE_KEY_SELF_HEAL]

    def test_mouse16_startup_sweep(self, estop, tmp_path, monkeypatch,
                                   audit_log):
        ex, rec = _exec(estop, tmp_path, monkeypatch, clear_after=False,
                        audit=audit_log)
        ups = rec.named("mouseUp")
        assert len(ups) == 3                          # 三键各一次幂等 up
        events = _audit_events(str(tmp_path / "audit"))
        assert any(e.get("event") == EV_STARTUP_KEY_SWEEP for e in events)

    def test_mouse16b_sweep_tolerates_corner_failsafe(self, estop, tmp_path,
                                                      monkeypatch,
                                                      audit_log):
        """ISS-0048(修改引入回归):光标压角时 pyautogui FAILSAFE 拦截清扫,
        构造不得崩+审计拦截事件。"""
        import pyautogui
        rec = _Rec()

        def boom_up(*a, **k):
            rec.calls.append(("mouseUp", a, k))
            raise pyautogui.FailSafeException("光标压角")

        monkeypatch.setattr(core_mod.pyautogui, "mouseUp", boom_up)
        for fn in ("mouseDown", "moveTo", "click", "hscroll", "scroll"):
            monkeypatch.setattr(core_mod.pyautogui, fn, rec.fn(fn))
        # 构造不得抛(清扫被 FAILSAFE 拦截也须活)
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      probe=FakeProbe(), audit=audit_log)
        assert len(rec.named("mouseUp")) == 3         # 三键都尝试过(直出)
        events = _audit_events(str(tmp_path / "audit"))
        assert any(e.get("event") == EV_STARTUP_KEY_SWEEP_FAILSAFE
                   for e in events)                   # 拦截如实记审计(直出)

    def test_mouse18_drag_tracks_pressed_symmetric(self, estop, tmp_path,
                                                   monkeypatch):
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        seen = []

        orig_move = core_mod.pyautogui.moveTo
        def spy_move(*a, **k):
            seen.append(ex._mouse.snapshot())
            return orig_move(*a, **k)
        monkeypatch.setattr(core_mod.pyautogui, "moveTo", spy_move)
        for btn in ("right", "left"):
            ex.execute({"tool": "drag",
                        "params": {"start": [200, 200], "end": [400, 400],
                                   "button": btn},
                        "binding_hwnd": FIXTURE_HWND})
            assert btn in seen[-1]                    # 移动中快照含该键
            assert ex._mouse.snapshot() == []         # 完成后核销(直出)
