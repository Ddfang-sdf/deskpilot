"""ISS-0042 遮挡错误点名遮挡者测试(TC-OC-01~02,问题单 §3)。

层级:单元(_occlusion_user32/probe 接缝替身;被测 _check_occlusion 真实)。
入口(设计):executor._check_occlusion。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deskpilot import errors
from deskpilot.executor import Executor

from .conftest import FIXTURE_HWND, FIXTURE_RECT


def _executor(estop, tmp_path, clock, probe, *, point_hwnd, is_child,
              title_text, proc_name):
    import deskpilot.executor.core as core
    seam = MagicMock()
    seam.WindowFromPoint.return_value = point_hwnd
    seam.IsChild.return_value = is_child
    seam.GetWindowTextLengthW.return_value = len(title_text)
    if title_text:
        seam.GetWindowTextW.side_effect = (
            lambda h, buf, n: setattr(buf, "value", title_text) or len(title_text))
    core._occlusion_user32 = seam
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  clock=clock, probe=probe)
    ex._probe.process_of = lambda h: proc_name
    return ex


class TestOccluderNamed:
    """TC-OC-01/02:遮挡错误附遮挡者进程+标题。断言:message 直出。"""

    def test_oc01_process_and_title_in_message(self, estop, tmp_path,
                                               clock, probe):
        ex = _executor(estop, tmp_path, clock, probe,
                       point_hwnd=999999, is_child=False,
                       title_text="元气桌面", proc_name="kdesk64.exe")
        with pytest.raises(errors.ExecutorError) as ei:
            ex._check_occlusion(FIXTURE_HWND, FIXTURE_RECT[0] + 10,
                                FIXTURE_RECT[1] + 10)
        assert ei.value.code == errors.WINDOW_OCCLUDED
        assert "kdesk64.exe" in ei.value.message
        assert "元气桌面" in ei.value.message

    def test_oc02_untitled_process_only(self, estop, tmp_path, clock, probe):
        ex = _executor(estop, tmp_path, clock, probe,
                       point_hwnd=999999, is_child=False,
                       title_text="", proc_name="kdesk64.exe")
        with pytest.raises(errors.ExecutorError) as ei:
            ex._check_occlusion(FIXTURE_HWND, FIXTURE_RECT[0] + 10,
                                FIXTURE_RECT[1] + 10)
        assert ei.value.code == errors.WINDOW_OCCLUDED
        assert "kdesk64.exe 遮挡" in ei.value.message
        assert "()" not in ei.value.message          # 无空括号残留(形态)
