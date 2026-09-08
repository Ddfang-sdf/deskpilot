"""ISS-0041 activate 状态驱动 ShowWindow 测试(TC-ACT-01~09,问题单 §3 v0.3)。

层级:TC-ACT-01~06 单元(fake user32/kernel32 调用记录直出);
TC-ACT-07 形态(描述直读);TC-ACT-08/09 集成(真记事本+真 Win32,--run-integration)。
入口(设计):DesktopProbe.activate / TOOL_SCHEMAS["activate_window"]。
"""

from __future__ import annotations

import pytest


def _probe(monkeypatch, *, alive=True, iconic=False, zoomed=False, fg_seq=()):
    """构造 DesktopProbe:替身仅 OS 接口层,被测 activate 本体真实执行。
    返回 (probe, show_window_cmds)——cmds 为 ShowWindow 的 nCmdShow 调用记录。"""
    from deskpilot.executor import probe as probe_mod
    cmds: list[int] = []
    fg = iter(fg_seq)
    monkeypatch.setattr(probe_mod.user32, "IsWindow", lambda h: alive)
    monkeypatch.setattr(probe_mod.user32, "IsIconic", lambda h: iconic)
    monkeypatch.setattr(probe_mod.user32, "IsZoomed", lambda h: zoomed)
    monkeypatch.setattr(probe_mod.user32, "ShowWindow",
                        lambda h, s: cmds.append(s))
    monkeypatch.setattr(probe_mod.user32, "GetForegroundWindow",
                        lambda: next(fg, 0))
    monkeypatch.setattr(probe_mod.user32, "GetWindowThreadProcessId",
                        lambda h, p: 1)
    monkeypatch.setattr(probe_mod.user32, "SetForegroundWindow",
                        lambda h: True)
    monkeypatch.setattr(probe_mod.user32, "BringWindowToTop",
                        lambda h: None)
    monkeypatch.setattr(probe_mod.user32, "AttachThreadInput",
                        lambda a, b, c: True)
    monkeypatch.setattr(probe_mod.kernel32, "GetCurrentThreadId", lambda: 1)
    return probe_mod.DesktopProbe(), cmds


class TestActivateStateDriven:
    """TC-ACT-01~06:ShowWindow 命令按窗口状态选择。断言:调用记录直出。"""

    def test_act01_maximized_never_restored(self, monkeypatch):
        """TC-ACT-01(判别性):最大化窗——nCmdShow 全为 3(SW_SHOWMAXIMIZED),无 9。"""
        p, cmds = _probe(monkeypatch, zoomed=True, fg_seq=[222, 222])
        assert p.activate(222) is True
        assert cmds, "activate 未调用 ShowWindow"
        assert all(c == 3 for c in cmds), f"最大化窗收到恢复命令: {cmds}"
        assert 9 not in cmds

    def test_act02_minimized_restored(self, monkeypatch):
        """TC-ACT-02(回归):最小化窗——SW_RESTORE(9)恢复原意图。"""
        p, cmds = _probe(monkeypatch, iconic=True, fg_seq=[222, 222])
        assert p.activate(222) is True
        assert 9 in cmds

    def test_act03_normal_window_no_restore(self, monkeypatch):
        """TC-ACT-03(判别性):普通窗——SW_SHOW(5),尺寸不动,无 9。"""
        p, cmds = _probe(monkeypatch, fg_seq=[222, 222])
        assert p.activate(222) is True
        assert cmds and all(c == 5 for c in cmds), f"普通窗收到: {cmds}"
        assert 9 not in cmds

    def test_act04_iconic_zoomed_prefers_restore(self, monkeypatch):
        """TC-ACT-04(边界):最小化的最大化窗——IsIconic 优先,SW_RESTORE 恢复到最大化。"""
        p, cmds = _probe(monkeypatch, iconic=True, zoomed=True,
                         fg_seq=[222, 222])
        assert p.activate(222) is True
        assert 9 in cmds

    def test_act05_dead_window_no_showwindow(self, monkeypatch):
        """TC-ACT-05(回归):死窗 False,ShowWindow 零调用。"""
        p, cmds = _probe(monkeypatch, alive=False)
        assert p.activate(222) is False
        assert cmds == []

    def test_act06_retry_uses_state_cmd_every_attempt(self, monkeypatch):
        """TC-ACT-06(ISS-0017 A 回归):3 轮重试,每轮 nCmdShow 均为 3。"""
        p, cmds = _probe(monkeypatch, zoomed=True,
                         fg_seq=[111, 111, 111, 111, 222, 222])
        assert p.activate(222) is True
        assert len(cmds) == 3
        assert all(c == 3 for c in cmds), f"重试轮次命令漂移: {cmds}"


class TestActivateWindowDescription:
    """TC-ACT-07:activate_window 描述含几何变化重新感知指引(形态直出)。"""

    def test_act07_description_guidance(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        d = TOOL_SCHEMAS["activate_window"]["description"]
        assert "最大化" in d and "重新感知" in d


@pytest.mark.integration
class TestActivateRealWindow:
    """TC-ACT-08/09(集成):真记事本+真 Win32,零打桩;断言在系统状态。

    触发点说明:取 probe.activate 直调——它正是 _activate_if_needed 在非
    前台时的委托点(core.py:734 单行委托,消费链路由单元层交叉面论证);
    直调使触发在本机/CI 均确定(前台跳过逻辑不介入)。activate 返回布尔
    不断言(CI 前台锁可失败,ShowWindow 已在尝试中执行)。
    资源卫生:前后差分锁定本次新窗,WM_CLOSE 优雅关闭,泄漏即红。"""

    def _new_notepad(self):
        import subprocess
        import time

        from deskpilot.executor import DesktopProbe
        from .test_uia_com_iss16 import _close_all_and_wait  # noqa: F401
        probe = DesktopProbe()

        def mains():
            return [w for w in probe.find_windows(
                process="notepad.exe", include_hidden=True)
                if w.get("title")
                and (w["rect"][2] - w["rect"][0]) > 100
                and (w["rect"][3] - w["rect"][1]) > 100]

        before = {w["hwnd"] for w in mains()}
        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(3.0)                      # 等会话恢复/多窗全部出现
        news = [w for w in mains() if w["hwnd"] not in before]
        assert news, "未找到本测试新开的记事本窗口"
        return proc, probe, news

    def test_act08_maximized_stays_maximized(self):
        """TC-ACT-08(终效应):最大化记事本 activate 后 IsZoomed 仍 True。"""
        import ctypes
        import time

        from .test_uia_com_iss16 import _close_all_and_wait
        u32 = ctypes.windll.user32
        proc, probe, news = self._new_notepad()
        closed = None
        try:
            hwnd = news[0]["hwnd"]
            u32.ShowWindow(hwnd, 3)          # SW_MAXIMIZE
            time.sleep(0.3)
            assert u32.IsZoomed(hwnd), "前置失败:记事本未能最大化"
            probe.activate(hwnd)             # 返回布尔不断言(CI 前台锁可失败)
            assert u32.IsZoomed(hwnd), \
                "activate 撤销了最大化(ISS-0041 缺陷实证)"
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in news])
        assert closed is True, "测试残留记事本窗口"

    def test_act09_minimized_gets_restored(self):
        """TC-ACT-09(原意图回归):最小化记事本 activate 后 IsIconic 变 False。"""
        import ctypes
        import time

        from .test_uia_com_iss16 import _close_all_and_wait
        u32 = ctypes.windll.user32
        proc, probe, news = self._new_notepad()
        closed = None
        try:
            hwnd = news[0]["hwnd"]
            u32.ShowWindow(hwnd, 6)          # SW_MINIMIZE
            time.sleep(0.3)
            assert u32.IsIconic(hwnd), "前置失败:记事本未能最小化"
            probe.activate(hwnd)
            assert not u32.IsIconic(hwnd), \
                "最小化恢复语义被破坏(原意图回归失败)"
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in news])
        assert closed is True, "测试残留记事本窗口"
