"""ISS-0017 窗口激活容错与提权边界测试（问题单 §4.1）。

层级：单元（替身 user32/token 直出）。
入口（设计）：DesktopProbe.activate / enforcement.submit 写前检测 /
executor._check_point 遮挡判定 / errors 新码。
"""

from __future__ import annotations

import ctypes
from unittest.mock import MagicMock

import pytest

from deskpilot import errors
from deskpilot.models import OperationRequest


# ---------- A activate 容错退避（单元） ----------

class TestActivateRetry:
    """场景:前台锁瞬时失败按短退避重试;最终失败诚实 False。
    断言:返回布尔与重试次数(替身直出)。"""

    def _probe_with_foreground(self, monkeypatch, foreground_seq):
        from deskpilot.executor import probe as probe_mod
        fg = iter(foreground_seq)
        monkeypatch.setattr(probe_mod.user32, "IsWindow", lambda h: True)
        monkeypatch.setattr(probe_mod.user32, "ShowWindow", lambda h, s: None)
        monkeypatch.setattr(probe_mod.user32, "SetForegroundWindow",
                            lambda h: True)
        monkeypatch.setattr(probe_mod.user32, "BringWindowToTop",
                            lambda h: None)
        monkeypatch.setattr(probe_mod.user32, "AttachThreadInput",
                            lambda a, b, c: True)
        monkeypatch.setattr(probe_mod.user32, "GetForegroundWindow",
                            lambda: next(fg, 0))
        monkeypatch.setattr(probe_mod.user32, "GetWindowThreadProcessId",
                            lambda h, p: 1)
        monkeypatch.setattr(probe_mod.kernel32, "GetCurrentThreadId",
                            lambda: 1)
        return probe_mod.DesktopProbe()

    def test_retry_then_success(self, monkeypatch):
        # activate 每次尝试消耗两个前台读数(线程计算+成功判定)
        p = self._probe_with_foreground(
            monkeypatch, [111, 111, 111, 111, 222, 222])
        assert p.activate(222) is True

    def test_never_foreground_returns_false(self, monkeypatch):
        p = self._probe_with_foreground(monkeypatch, [111, 111, 111, 111])
        assert p.activate(222) is False


# ---------- B 写前提权边界（单元,enforcement 直通） ----------

class TestElevationBoundary:
    """场景:目标提权高于自身 → ELEVATION_REQUIRED(fail-closed);
    同级放行;检测失败拒绝。
    断言:Decision.reason_code 与 message(直出)。"""

    def _submit_write(self, enforcement, bound_record):
        return enforcement.submit(
            OperationRequest("type_text", {"text": "x"}, bound_record.token))

    def test_target_elevated_denies(self, enforcement, bound_record,
                                    monkeypatch):
        import deskpilot.enforcement as enf
        monkeypatch.setattr(enf, "_pid_of_hwnd", lambda hwnd: 4242)
        monkeypatch.setattr(enf, "_elevation_of_process",
                            lambda pid: "full")
        monkeypatch.setattr(enf, "_self_elevation", lambda: "limited")
        d = self._submit_write(enforcement, bound_record)
        assert d.allowed is False
        assert d.reason_code == errors.ELEVATION_REQUIRED
        assert "管理员" in d.message

    def test_same_level_allows(self, enforcement, bound_record, monkeypatch):
        import deskpilot.enforcement as enf
        monkeypatch.setattr(enf, "_pid_of_hwnd", lambda hwnd: 4242)
        monkeypatch.setattr(enf, "_elevation_of_process",
                            lambda pid: "limited")
        monkeypatch.setattr(enf, "_self_elevation", lambda: "limited")
        d = self._submit_write(enforcement, bound_record)
        assert d.allowed is True

    def test_detection_failure_denies(self, enforcement, bound_record,
                                      monkeypatch):
        import deskpilot.enforcement as enf

        def boom(pid):
            raise OSError("token 不可用")

        monkeypatch.setattr(enf, "_pid_of_hwnd", lambda hwnd: 4242)
        monkeypatch.setattr(enf, "_elevation_of_process", boom)
        d = self._submit_write(enforcement, bound_record)
        assert d.allowed is False
        assert d.reason_code == errors.ELEVATION_REQUIRED


# ---------- C 遮挡判定（单元,executor._check_point） ----------

class TestOcclusion:
    """场景:落点被其他窗口遮挡 → 拒绝且明示遮挡;落点属目标或子窗口 → 放行。
    断言:ExecutorError.code 与 message(直出)。"""

    def _executor(self, estop, tmp_path, clock, probe, point_hwnd, is_child):
        import deskpilot.executor.core as core
        from deskpilot.executor import Executor
        monkey_user32 = MagicMock()
        monkey_user32.WindowFromPoint.return_value = point_hwnd
        monkey_user32.IsChild.return_value = is_child
        core._occlusion_user32 = monkey_user32
        return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                        clock=clock, probe=probe)

    def test_occluded_point_denied(self, estop, tmp_path, clock, probe):
        from .conftest import FIXTURE_HWND, FIXTURE_RECT
        ex = self._executor(estop, tmp_path, clock, probe, 999999, False)
        with pytest.raises(errors.ExecutorError) as ei:
            ex._check_occlusion(FIXTURE_HWND, FIXTURE_RECT[0] + 10,
                            FIXTURE_RECT[1] + 10)
        assert ei.value.code == errors.WINDOW_OCCLUDED
        assert "遮挡" in ei.value.message

    def test_own_point_allowed(self, estop, tmp_path, clock, probe):
        from .conftest import FIXTURE_HWND, FIXTURE_RECT
        ex = self._executor(estop, tmp_path, clock, probe, FIXTURE_HWND,
                            False)
        ex._check_occlusion(FIXTURE_HWND, FIXTURE_RECT[0] + 10,
                        FIXTURE_RECT[1] + 10)      # 不抛即放行

    def test_child_point_allowed(self, estop, tmp_path, clock, probe):
        from .conftest import FIXTURE_HWND, FIXTURE_RECT
        ex = self._executor(estop, tmp_path, clock, probe, 555, True)
        ex._check_occlusion(FIXTURE_HWND, FIXTURE_RECT[0] + 10,
                        FIXTURE_RECT[1] + 10)
