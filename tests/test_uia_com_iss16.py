"""ISS-0016 窗口定位与读取可靠性测试（问题单 §4.1/§4.2）。

层级：
- 单元：惰性 COM 初始化幂等/错误分类/搜索无果指引（替身注入直出）；
- 集成：经 daemon 实调 get_ui_tree（真实 HttpDaemon+真实 executor+真实记事本，
  消灭"executor 全替身"装配盲区,R1 守门）。
入口（设计）：executor UIA 入口 / find_window 无果 message / ocr 描述 /
tools.find_window / httpd /call。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest

from deskpilot import errors


# ---------- A 线程级 COM 惰性初始化（单元） ----------

class TestLazyComInit:
    """场景:executor UIA 入口在任何线程上惰性 CoInitialize 且幂等。
    断言:初始化调用计数(替身直出)。"""

    def test_com_init_once_per_thread(self, monkeypatch, estop, tmp_path,
                                      clock, probe):
        import deskpilot.executor.core as core
        from deskpilot.executor import Executor
        calls = []
        monkeypatch.setattr(core, "_com_initialize",
                            lambda: calls.append(1))
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      clock=clock, probe=probe)
        ex._ensure_com()
        ex._ensure_com()
        assert calls == [1]                             # 幂等(直出)

    def test_com_init_on_new_thread(self, monkeypatch, estop, tmp_path,
                                    clock, probe):
        import deskpilot.executor.core as core
        from deskpilot.executor import Executor
        calls = []
        monkeypatch.setattr(core, "_com_initialize",
                            lambda: calls.append(threading.get_ident()))
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      clock=clock, probe=probe)
        ids = []
        t = threading.Thread(target=lambda: ids.append(ex._ensure_com()),
                             daemon=True)
        t.start()
        t.join()
        ex._ensure_com()
        assert len(set(calls)) == 2                     # 两线程各初始化一次(直出)


# ---------- B 错误分类（单元） ----------

class TestErrorClassification:
    """场景:COM 通道异常与窗口消失分流——真因不再被 WINDOW_GONE 吞掉。
    断言:ExecutorError.code 与 message(直出)。"""

    def _executor(self, estop, tmp_path, clock, probe, boom):
        from deskpilot.executor import Executor
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      clock=clock, probe=probe)
        ex._element_source = lambda hwnd: (_ for _ in ()).throw(boom)
        return ex

    def test_com_error_maps_uia_channel(self, estop, tmp_path, clock,
                                        probe):
        boom = OSError("[WinError -2147221008] 尚未调用 CoInitialize")
        ex = self._executor(estop, tmp_path, clock, probe, boom)
        from .conftest import FIXTURE_HWND
        with pytest.raises(errors.ExecutorError) as ei:
            ex.get_ui_tree(FIXTURE_HWND)
        assert ei.value.code == errors.INTERNAL_ERROR
        assert "UIA 通道异常" in ei.value.message

    def test_dead_hwnd_maps_window_gone(self, estop, tmp_path, clock,
                                        probe):
        ex = self._executor(estop, tmp_path, clock, probe, None)
        ex._element_source = lambda hwnd: None
        from .conftest import FIXTURE_HWND
        with pytest.raises(errors.ExecutorError) as ei:
            ex.get_ui_tree(FIXTURE_HWND)
        assert ei.value.code == errors.WINDOW_GONE


# ---------- C find_window 无果指引（单元） ----------

class TestFindWindowGuidance:
    """场景:find_window 零命中时给出下一步指引(按进程名/hwnd)。
    断言:ToolResult.message 文本(直出)。"""

    def test_zero_hit_message_guides(self, policy, enforcement, bindings,
                                     executor, audit_log):
        from deskpilot.tools import ToolContext, call_tool
        ctx = ToolContext(policy=policy, enforcement=enforcement,
                          bindings=bindings, executor=executor, audit=audit_log)
        r = call_tool(ctx, "find_window", {"title": "绝无此窗口xyz123"})
        assert r.data["windows"] == []
        assert "按进程名" in r.message


# ---------- E ocr 分工描述（单元） ----------

class TestOcrDescription:
    """场景:ocr 描述含 OCR/视觉分工指引。
    断言:描述文本(直出)。"""

    def test_ocr_desc_has_division(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        d = TOOL_SCHEMAS["ocr"]["description"]
        assert "文字清单" in d or "定位" in d
        assert "布局" in d or "多模态" in d or "查看" in d


# ---------- D 经 daemon 实调 UIA（集成,R1 守门） ----------

@pytest.mark.integration
class TestUiaThroughDaemon:
    """场景(集成):真实 HttpDaemon+真实 executor 实调 get_ui_tree——
    消灭"executor 全替身"装配盲区;断言在系统外表面(响应体/真实窗口)。"""

    def test_get_ui_tree_real_notepad(self, policy, audit_log, tmp_path):
        import subprocess
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.estop import EstopMonitor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext

        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"),
                            probe=DesktopProbe())
        ctx = ToolContext(policy=policy, enforcement=None, bindings=None,
                          executor=executor, audit=audit_log)
        d = HttpDaemon(ctx, port=0)
        d.start()
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{d.port}/health",
                            timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.1)
            proc = subprocess.Popen(["notepad.exe"])
            time.sleep(2.0)
            try:
                hwnd = proc._handle if hasattr(proc, "_handle") else None
                import uiautomation as uia
                win = uia.WindowControl(searchDepth=1, SubName="Notepad")
                hwnd = win.NativeWindowHandle
                body = json.dumps({"tool": "get_ui_tree",
                                   "params": {"window": hwnd}}).encode()
                req = urllib.request.Request(
                    f"http://127.0.0.1:{d.port}/call", data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    r = json.loads(resp.read().decode("utf-8"))
                assert r["ok"] is True, r.get("message")
                assert len(r["data"]["elements"]) > 0
            finally:
                proc.terminate()
        finally:
            d.stop()
