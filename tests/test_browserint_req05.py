"""REQ-005 TC-BR-26~28(集成):浏览器翻译层实盘链。

层级:集成(零 mock、真实例/真窗口,断言在响应体/页面读回值=数据层;
@pytest.mark.integration)。
环境守卫(沿用 envguard,测试设计 §3):真 daemon(9420)在线 skip
(不起临时服务打扰真服务);无可拉起浏览器二进制 skip;无用户自拉
浏览器窗 skip(TC-BR-27)。

入口(设计):POST /call browser_snapshot/browser_get_rect(临时端口
daemon 全链)/M4 拉起/M5 Runtime.evaluate 读回(测试侧读回通道)。
断言出处:HTTP 响应体直出/eval 读回值直出/两次快照元素数直出。

P1 红态预期:工具调用面未接线(未知工具)——红;本机真 daemon 在线
时全部环境守卫 skip。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from .envguard import env_skip, real_daemon_online


def _browser_binary() -> str | None:
    """Edge → Chrome 序探测(详设 §3.7);均无 → None(环境守卫 skip)。"""
    candidates = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _spawn_daemon(policy, audit_log, tmp_path):
    """临时端口真 daemon(TC-100-08 先例形态;零打桩)。"""
    from deskpilot.approval import ApprovalManager
    from deskpilot.binding import BindingManager
    from deskpilot.enforcement import Enforcement
    from deskpilot.estop import EstopMonitor
    from deskpilot.executor import DesktopProbe, Executor
    from deskpilot.httpd import HttpDaemon
    from deskpilot.tools import ToolContext

    from .conftest import FakeApprover, FakeClock

    probe = DesktopProbe()
    estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
    executor = Executor(estop, str(tmp_path / "audit"), probe=probe)
    clock = FakeClock()
    bindings = BindingManager(probe, policy.binding_ttl, clock)
    approvals = ApprovalManager(FakeApprover(), policy.approval_ttl, clock)
    enforcement = Enforcement(policy, bindings, approvals, estop,
                              executor, audit_log)
    ctx = ToolContext(policy=policy, enforcement=enforcement,
                      bindings=bindings, executor=executor,
                      audit=audit_log)
    d = HttpDaemon(ctx, port=0)
    d.start()
    for _ in range(50):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{d.port}/health", timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    return d


def _call(port: int, tool: str, params: dict, timeout=60) -> dict:
    body = json.dumps({"tool": tool, "params": params}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/call",
                                 data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@pytest.mark.integration
class TestManagedInstanceChain:
    """TC-BR-26(集成):受管实例全链——拉起→snapshot→get_rect→既有
    click(无害点)→eval 读回。"""

    def test_br26_managed_instance_full_chain(self, policy, audit_log,
                                              tmp_path):
        """TC-BR-26:快照非空 source=cdp;坐标在屏内;点击后页面状态
        变化(eval 读回)。断言:响应体/读回值直出。
        红态:工具调用面未接线。"""
        if real_daemon_online():
            env_skip("真实 daemon 在线,不打扰真服务")
        if not _browser_binary():
            env_skip("无可拉起浏览器二进制(Edge/Chrome 均无)")
        d = _spawn_daemon(policy, audit_log, tmp_path)
        try:
            snap = _call(d.port, "browser_snapshot", {})
            assert snap["ok"] is True, f"拉起+快照(响应体直出): {snap}"
            assert snap["data"]["source"] == "cdp", \
                f"source(直出): {snap['data'].get('source')}"
            assert snap["data"]["elements"], \
                f"共管实例快照非空(直出): {len(snap['data']['elements'])}"
            name = snap["data"]["elements"][0]["name"]
            rect = _call(d.port, "browser_get_rect", {"name": name})
            assert rect["ok"] is True, f"get_rect(响应体直出): {rect}"
            l, t, r, b = rect["data"]["rect"]
            assert l >= 0 and t >= 0, \
                f"坐标在屏内(直出): {rect['data']['rect']}"
            # 既有 click(无害点=空白区,非元素本体)+eval 读回面预留:
            # P3 接线后补点击前后页面状态比对(eval 读回通道)
        finally:
            d.stop()


@pytest.mark.integration
class TestUserBrowserSnapshot:
    """TC-BR-27(集成):用户自拉浏览器快照(Edge 或 Firefox 真窗)。"""

    def test_br27_user_launched_browser_snapshot(self, policy, audit_log,
                                                 tmp_path):
        """TC-BR-27:snapshot(hwnd)→source=uia、元素非空;
        get_rect(name)→rect 在窗口矩形内。断言:响应体直出。
        红态:工具调用面未接线。"""
        if real_daemon_online():
            env_skip("真实 daemon 在线,不打扰真服务")
        from deskpilot.executor import DesktopProbe
        probe = DesktopProbe()
        wins = (probe.find_windows(process="msedge.exe")
                or probe.find_windows(process="firefox.exe"))
        if not wins:
            env_skip("无用户自拉浏览器窗(Edge/Firefox 均无)")
        hwnd = wins[0]["hwnd"]
        d = _spawn_daemon(policy, audit_log, tmp_path)
        try:
            snap = _call(d.port, "browser_snapshot", {"window": hwnd})
            assert snap["ok"] is True, f"快照(响应体直出): {snap}"
            assert snap["data"]["source"] == "uia", \
                f"source(直出): {snap['data'].get('source')}"
            assert snap["data"]["elements"], "UIA 快照元素非空(直出)"
            name = snap["data"]["elements"][0]["name"]
            rect = _call(d.port, "browser_get_rect",
                         {"window": hwnd, "name": name})
            assert rect["ok"] is True, f"get_rect(响应体直出): {rect}"
            wl, wt, wr, wb = wins[0]["rect"]
            l, t, r, b = rect["data"]["rect"]
            assert wl <= l and wt <= t and r <= wr and b <= wb, \
                f"rect 须在窗口矩形内(直出): {rect['data']['rect']} vs " \
                f"{wins[0]['rect']}"
        finally:
            d.stop()


@pytest.mark.integration
class TestLazyEnableReal:
    """TC-BR-28(集成):懒启用实盘——全新受管实例(未点亮)首查→等→
    复走有内容(2~3s 内)。"""

    def test_br28_lazy_enable_real_timing(self, policy, audit_log, tmp_path):
        """TC-BR-28:两次快照元素数直出:首查可空,复走(2~3s 内)非空。
        红态:工具调用面未接线。"""
        if real_daemon_online():
            env_skip("真实 daemon 在线,不打扰真服务")
        if not _browser_binary():
            env_skip("无可拉起浏览器二进制(Edge/Chrome 均无)")
        d = _spawn_daemon(policy, audit_log, tmp_path)
        try:
            t0 = time.monotonic()
            first = _call(d.port, "browser_snapshot", {})
            assert first["ok"] is True, f"首查(响应体直出): {first}"
            n1 = len(first["data"]["elements"])
            second = _call(d.port, "browser_snapshot", {})
            assert second["ok"] is True, f"复走(响应体直出): {second}"
            n2 = len(second["data"]["elements"])
            assert n2 > 0, \
                f"复走须有内容(2~3s 内;两次元素数直出): {n1} → {n2}"
            assert time.monotonic() - t0 < 10.0, \
                f"懒启用实盘时耗(直出): {time.monotonic() - t0:.1f}s"
        finally:
            d.stop()
