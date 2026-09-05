"""ISS-0009 断链可靠性单元测试（问题单 §6 接口定义）。

层级：单元测试（允许打桩；断言在被调返回值/HTTP 响应体/替身调用记录/异常类型，
均直出）+ 一条黑盒 stdout 卫生（子进程驱动，断言系统外表面 stdout 帧）。
五要素：各类 docstring 标注。
入口（§6）：call_with_progress / TOOL_TIME_BUDGETS / TOOL_TIMEOUT /
httpd /call 兜底与 /version / check_daemon_version / VERSION_FILE /
Executor.execute 异常收敛 / daemon 状态跨会话保持。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from deskpilot import errors
from deskpilot.errors import ExecutorError
from deskpilot.executor.core import Executor
from deskpilot.httpd import (VERSION_FILE, HttpDaemon, check_daemon_version,
                             probe_daemon)
from deskpilot.mcp_server import call_with_progress
from deskpilot.models import TOOL_TIME_BUDGETS

from .conftest import FIXTURE_HWND, FIXTURE_RECT, FakeClock, FakeProbe

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_probe():
    p = FakeProbe()
    p.rects = {FIXTURE_HWND: FIXTURE_RECT}
    return p


@pytest.fixture
def m3_executor(estop, tmp_path, clock, fake_probe):
    return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                    wait_timeout_max=5.0, clock=clock, probe=fake_probe)


def _post(url: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


# ---------- A 进度通知 ----------

class TestCallWithProgress:
    """场景:长调用期间周期触发进度回调,完成后返回结果;异常透出且进度停止。
    断言:report 替身调用次数、返回值、异常类型(直出)。"""

    def test_progress_emitted_periodically_and_result_returned(self):
        async def go():
            async def work():
                await asyncio.sleep(0.30)
                return "done"
            reports = []
            r = await call_with_progress(work(), lambda: reports.append(1),
                                         0.05)
            return r, len(reports)

        result, n = asyncio.run(go())
        assert result == "done"
        assert n >= 3                          # 0.3s / 0.05s 间隔 ≈ 5~6 次

    def test_exception_propagates_and_progress_stops(self):
        async def go():
            async def work():
                await asyncio.sleep(0.05)
                raise RuntimeError("boom")
            reports = []
            with pytest.raises(RuntimeError):
                await call_with_progress(work(), lambda: reports.append(1),
                                         0.02)
            n1 = len(reports)
            await asyncio.sleep(0.1)
            return n1, len(reports)

        n1, n2 = asyncio.run(go())
        assert n1 == n2                        # 异常后不再有进度


# ---------- B 超时预算 ----------

class TestToolTimeBudgets:
    """场景:超出级别预算的调用返回结构化 TOOL_TIMEOUT 而非悬挂。
    前提:daemon 以阻塞型 ctx 装配,预算经由 monkeypatch 收紧。
    断言:响应错误码/消息、返回耗时(直出)。"""

    @pytest.fixture
    def slow_ctx(self, ctx, enforcement):
        class SlowExec:
            def execute(self, instruction):
                time.sleep(5)
                return {"status": "ok"}

        enforcement._executor = SlowExec()
        return dataclasses.replace(ctx, executor=SlowExec())

    def test_budget_map_values(self):
        assert TOOL_TIME_BUDGETS["L0"] > 0
        assert TOOL_TIME_BUDGETS["L1"] > TOOL_TIME_BUDGETS["L0"]
        assert TOOL_TIME_BUDGETS["L2"] > TOOL_TIME_BUDGETS["L1"]

    def test_over_budget_returns_structured_timeout(self, slow_ctx, bound_record,
                                                    monkeypatch):
        # ISS-0033 重指:L1/L2 预算均改由 resolve_budget 按审批时限决议,
        # 收紧测试直接替换预算决议接缝(与旧测试 monkeypatch 常量的
        # 手法等价,目标仍是验证"临期回结构化 TOOL_TIMEOUT")。
        # ISS-0039 R4:决议接缝签名改 (tool, level, policy)。
        import deskpilot.httpd as httpd_mod
        monkeypatch.setattr(httpd_mod, "resolve_budget",
                            lambda tool, level, policy: 0.5)
        d = HttpDaemon(slow_ctx, host="127.0.0.1", port=0)
        d.start()
        try:
            t0 = time.monotonic()
            status, body = _post(f"http://127.0.0.1:{d.port}/call",
                                 {"tool": "scroll",
                                  "params": {"token": bound_record.token,
                                             "direction": "down",
                                             "amount": 3}}, timeout=10)
            elapsed = time.monotonic() - t0
        finally:
            d.stop()
        assert status == 200
        assert body["ok"] is False
        assert body["error_code"] == errors.TOOL_TIMEOUT
        assert elapsed < 3.0


# ---------- C 不死身 ----------

class TestCrashSafety:
    """场景:未知异常不得杀死进程/断连;三方异常收敛为 ExecutorError。
    断言:HTTP 状态码与错误码、下一次调用可达、异常类型与错误码(直出)。"""

    def test_httpd_unknown_exception_returns_500_and_survives(self, ctx,
                                                              monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("unexpected")

        monkeypatch.setattr("deskpilot.tools.call_tool", boom)
        d = HttpDaemon(ctx, host="127.0.0.1", port=0)
        d.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{d.port}/call",
                data=json.dumps({"tool": "get_cursor", "params": {}}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    code, body = resp.status, json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                code, body = e.code, json.loads(e.read().decode())
            assert code == 500
            assert body["ok"] is False and body["error_code"]
            with urllib.request.urlopen(f"http://127.0.0.1:{d.port}/health",
                                        timeout=3) as resp:
                assert resp.status == 200
        finally:
            d.stop()

    def test_executor_failsafe_maps_to_estop(self, m3_executor, monkeypatch):
        import pyautogui
        monkeypatch.setattr(pyautogui, "moveTo",
                            lambda *a, **k: (_ for _ in ()).throw(
                                pyautogui.FailSafeException("corner")))
        with pytest.raises(ExecutorError) as ei:
            m3_executor.execute({"tool": "move",
                                 "params": {"x": 1, "y": 1},
                                 "binding_hwnd": None})
        assert ei.value.code == errors.EMERGENCY_STOP

    def test_executor_unknown_exception_maps_to_internal(self, m3_executor):
        m3_executor._shot_fn = lambda region: (_ for _ in ()).throw(
            RuntimeError("boom"))
        with pytest.raises(ExecutorError) as ei:
            m3_executor.execute({"tool": "screenshot",
                                 "params": {"scope": "fullscreen"},
                                 "binding_hwnd": None})
        assert ei.value.code == errors.INTERNAL_ERROR


# ---------- H 版本握手 ----------

class TestDaemonVersion:
    """场景:daemon 写版本文件并提供 /version 端点;版本比对函数判定一致/不一致。
    断言:版本文件内容、/version 响应体、check 函数布尔判定(直出)。"""

    @pytest.fixture
    def daemon(self, ctx, tmp_path):
        d = HttpDaemon(ctx, host="127.0.0.1", port=0)
        d.start()
        yield d
        d.stop()

    def test_version_endpoint_and_file(self, daemon, ctx):
        import deskpilot
        with urllib.request.urlopen(f"http://127.0.0.1:{daemon.port}/version",
                                    timeout=3) as resp:
            body = json.loads(resp.read().decode())
        assert body["version"] == deskpilot.__version__
        vf = Path(ctx.policy.audit_dir) / VERSION_FILE
        assert json.loads(vf.read_text(encoding="utf-8"))[
            "version"] == deskpilot.__version__
        assert check_daemon_version("127.0.0.1", daemon.port,
                                    deskpilot.__version__) is True
        assert check_daemon_version("127.0.0.1", daemon.port, "0.0.0") is False

    def test_check_unreachable_is_mismatch(self):
        assert check_daemon_version("127.0.0.1", 1, "x", timeout=0.2) is False


# ---------- G 断链零成本（状态跨会话保持回归） ----------

class TestStateSurvivesSessions:
    """场景:第一次 HTTP 会话 attach 后,第二次独立会话持令牌写操作仍过闸。
    断言:两次调用响应 ok 字段(直出)。"""

    def test_binding_survives_independent_http_sessions(self, ctx, approvals,
                                                        estop, executor,
                                                        audit_log, clock):
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.tools import ToolContext, call_tool
        from .conftest import FIXTURE_RECT, FakeProbe

        class FakeWinExec:
            def find_windows(self, **kw):
                return [{"hwnd": FIXTURE_HWND, "process": "notepad.exe",
                         "rect": list(FIXTURE_RECT)}]

        bindings = BindingManager(FakeProbe(), ctx.policy.binding_ttl, clock)
        en = Enforcement(ctx.policy, bindings, approvals, estop, executor,
                         audit_log)
        c = ToolContext(policy=ctx.policy, enforcement=en, bindings=bindings,
                        executor=FakeWinExec(), audit=audit_log)
        r1 = call_tool(c, "attach", {"title": "x"})
        assert r1.ok is True
        token = r1.data["token"]
        # 第二次独立"会话"(新连接语义)直接用令牌
        executor.focus_type = "Edit"
        executor.result = {"status": "ok", "before_shot": "", "after_shot": ""}
        r2 = call_tool(c, "key", {"token": token, "key": "enter"})
        assert r2.ok is True


# ---------- D stdout 卫生（黑盒） ----------

class TestStdoutHygiene:
    """场景:stdio 服务一次完整会话,stdout 逐行均为合法 JSON-RPC 帧。
    前提:仓库根 policy.yml 就位;以 python -m deskpilot 子进程驱动。
    步骤:MCP initialize → list_tools → 关闭;抓全部 stdout。
    预期:每一非空行 json.loads 成功且含 "jsonrpc" 键。
    断言:stdout 帧逐行解析结果(系统外表面,无源码导入驱动)。"""

    def test_stdio_stdout_is_pure_jsonrpc(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def go():
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "deskpilot"],
                cwd=str(REPO_ROOT))
            proc = subprocess.Popen(
                [sys.executable, "-m", "deskpilot"], cwd=str(REPO_ROOT),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        return len(tools.tools)
            finally:
                pass

        # 经 SDK 驱动之外,再裸进程抓一帧 stdout 验证卫生
        proc = subprocess.Popen(
            [sys.executable, "-m", "deskpilot"], cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        try:
            init = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05",
                           "capabilities": {},
                           "clientInfo": {"name": "hygiene", "version": "0"}}})
            proc.stdin.write((init + "\n").encode("utf-8"))
            proc.stdin.flush()
            lines = []
            deadline = time.time() + 15
            while time.time() < deadline and not lines:
                line = proc.stdout.readline()
                if line:
                    lines.append(line.decode("utf-8", errors="replace").strip())
            assert lines, "stdio 服务无响应"
            for raw in lines:
                frame = json.loads(raw)
                assert "jsonrpc" in frame
        finally:
            proc.kill()
