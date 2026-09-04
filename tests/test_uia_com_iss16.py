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

def _close_all_and_wait(hwnds, timeout: float = 8.0) -> bool:
    """关窗卫生:对 hwnds 逐一发 WM_CLOSE,轮候全部消失。

    只用 WM_CLOSE(优雅关闭,会话状态干净);禁用 taskkill /F——
    Store 版记事本会话恢复机制会把强杀的窗口下次启动全部还原,
    越杀越多(2026-09-02 实盘实证)。关不掉就返回 False 让测试红,
    交人处置(fail-closed),不静默强杀。

    2026-09-04 实盘修复(未保存文档关窗):
    ① Store 版:等待自动保存生效(标题 * 前缀消失)再 WM_CLOSE——未保存
      文档的 WM_CLOSE 会弹 XAML 内嵌保存提示,窗口滞留且模态阻塞同进程
      后续窗口(全套件下后序记事本测试遮挡报错的根因);
    ② 经典版(CI):修改文档的 WM_CLOSE 弹 #32770 保存对话框——
      对同 PID 的可见 #32770 对话框发 WM_COMMAND IDNO 点「不保存」。
    """
    import ctypes
    u32 = ctypes.windll.user32
    # ① Store 版:等自动保存(标题去 *)——最多 5s,等不到也照关
    for h in hwnds:
        waited = 0.0
        while waited < 5.0:
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, buf, 256)
            if not buf.value.startswith("*"):
                break
            time.sleep(0.3)
            waited += 0.3
        u32.PostMessageW(h, 0x0010, 0, 0)                # WM_CLOSE
    # ② 轮候期间对同 PID 的经典保存对话框点「不保存」
    pids = set()
    for h in hwnds:
        pid = ctypes.wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value:
            pids.add(pid.value)

    def _discard_dialogs():
        for pid in list(pids):
            def enum_cb(dhwnd, _lparam):
                if not u32.IsWindowVisible(dhwnd):
                    return True
                dpid = ctypes.wintypes.DWORD()
                u32.GetWindowThreadProcessId(dhwnd, ctypes.byref(dpid))
                cls = ctypes.create_unicode_buffer(256)
                u32.GetClassNameW(dhwnd, cls, 256)
                if dpid.value == pid and cls.value == "#32770":
                    u32.PostMessageW(dhwnd, 0x0111, 7, 0)   # WM_COMMAND IDNO
                return True

            u32.EnumWindows(ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_cb), 0)

    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if all(not u32.IsWindow(h) for h in hwnds):
            return True
        _discard_dialogs()
        time.sleep(0.2)
    return False


@pytest.mark.integration
class TestUiaThroughDaemon:
    """场景(集成):真实 HttpDaemon+真实 executor 实调 get_ui_tree——
    消灭"executor 全替身"装配盲区;断言在系统外表面(响应体/真实窗口)。

    资源卫生(2026-09-02 实盘根因):Popen("notepad.exe") 拉起的是 Win11
    应用执行别名存根,存根转手即退,proc.terminate() 杀的是存根尸体,
    真记事本成孤儿残留——每跑一轮全量漏一个窗口。且 Store 版一次拉起
    多个同标题同矩形窗口(框架窗+XAML 岛),被 /F 强杀后下次启动还会
    会话恢复成倍还原。修法:前后窗口集差分锁定"本次新开的所有主窗"
    (不得误关用户已有记事本),全部 WM_CLOSE 优雅关闭,末尾断言全灭
    (泄漏即红)。"""

    def test_get_ui_tree_real_notepad(self, policy, audit_log, tmp_path):
        import ctypes
        import subprocess
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.estop import EstopMonitor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext

        def notepad_mains() -> list[dict]:
            return [w for w in DesktopProbe().find_windows(
                process="notepad.exe", include_hidden=True)
                if w.get("title")
                and (w["rect"][2] - w["rect"][0]) > 100
                and (w["rect"][3] - w["rect"][1]) > 100]

        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"),
                            probe=DesktopProbe())
        ctx = ToolContext(policy=policy, enforcement=None, bindings=None,
                          executor=executor, audit=audit_log)
        d = HttpDaemon(ctx, port=0)
        d.start()
        new_mains: list[dict] = []
        closed = None
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{d.port}/health",
                            timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.1)
            before = {w["hwnd"] for w in notepad_mains()}
            proc = subprocess.Popen(["notepad.exe"])
            time.sleep(3.0)                  # 等会话恢复/多窗全部出现
            try:
                new_mains = [w for w in notepad_mains()
                             if w["hwnd"] not in before]
                assert len(new_mains) >= 1, \
                    "未找到本测试新开的记事本窗口(可能被会话恢复合并)"
                body = json.dumps({"tool": "get_ui_tree",
                                   "params": {"window": new_mains[0]["hwnd"]}}).encode()
                req = urllib.request.Request(
                    f"http://127.0.0.1:{d.port}/call", data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    r = json.loads(resp.read().decode("utf-8"))
                assert r["ok"] is True, r.get("message")
                assert len(r["data"]["elements"]) > 0
            finally:
                proc.terminate()                         # 存根句柄(无害)
                if new_mains:
                    closed = _close_all_and_wait(
                        [w["hwnd"] for w in new_mains])
        finally:
            d.stop()
        # 卫生断言(泄漏即红):本测试新开的窗口必须全部消失
        assert closed is True, "测试残留记事本窗口(Store 存根泄漏)"
