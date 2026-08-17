"""ISS-0001 常驻服务单元测试（问题单 §4.1 测试方案）。

入口：HttpDaemon（start/stop + HTTP 端点）、probe_daemon、remote_call。
断言值来源：HTTP 响应体 / 共享 ctx 的替身调用记录 / 端口监听状态。
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

from deskpilot import errors
from deskpilot.httpd import HttpDaemon, probe_daemon, remote_call

from .conftest import FIXTURE_HWND, FIXTURE_RECT, FakeProbe


def _http_post(base: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict]:
    req = urllib.request.Request(
        base, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestHttpDaemon:
    @pytest.fixture
    def daemon(self, ctx):
        d = HttpDaemon(ctx, host="127.0.0.1", port=0)   # 端口 0 = 临时端口
        d.start()
        yield d
        d.stop()

    def test_health(self, daemon):
        with urllib.request.urlopen(f"http://127.0.0.1:{daemon.port}/health",
                                    timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert body["status"] == "ok"

    def test_call_allowed_goes_through_tools(self, daemon, executor,
                                             bound_record):
        status, body = _http_post(
            f"http://127.0.0.1:{daemon.port}/call",
            {"tool": "type_text",
             "params": {"token": bound_record.token, "text": "hello"}})
        assert status == 200
        assert body["ok"] is True
        assert executor.instructions[0]["tool"] == "type_text"
        assert executor.instructions[0]["params"]["text"] == "hello"

    def test_call_denied_transparent(self, daemon):
        status, body = _http_post(
            f"http://127.0.0.1:{daemon.port}/call",
            {"tool": "click_element", "params": {"token": "nope",
                                                 "name": "保存"}})
        assert status == 200
        assert body["ok"] is False
        assert body["error_code"] == errors.NO_BINDING

    def test_state_persists_across_calls(self, daemon, executor, bound_record):
        """同一 daemon 内两次调用共享 ctx——绑定等内存态不丢。"""
        for text in ("第一次", "第二次"):
            status, body = _http_post(
                f"http://127.0.0.1:{daemon.port}/call",
                {"tool": "type_text",
                 "params": {"token": bound_record.token, "text": text}})
            assert status == 200 and body["ok"] is True
        assert len(executor.instructions) == 2
        assert [i["params"]["text"] for i in executor.instructions] == \
            ["第一次", "第二次"]

    def test_unknown_tool_structured_error(self, daemon):
        status, body = _http_post(
            f"http://127.0.0.1:{daemon.port}/call",
            {"tool": "no_such_tool", "params": {}})
        assert status == 200
        assert body["ok"] is False
        assert body["error_code"] in (errors.INVALID_PARAMS, errors.INTERNAL_ERROR)


class TestProbe:
    def test_reachable(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        try:
            assert probe_daemon("127.0.0.1",
                                srv.getsockname()[1], timeout=0.3) is True
        finally:
            srv.close()

    def test_unreachable_bounded(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                  # 释放端口再探测
        t0 = time.monotonic()
        assert probe_daemon("127.0.0.1", port, timeout=0.3) is False
        assert time.monotonic() - t0 < 1.5


class TestRemoteCall:
    @pytest.fixture
    def fake_server(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                self.server.received.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"ok": True, "error_code": "",
                                "message": "ok", "data": {"status": "ok"}})
                    .encode("utf-8"))

            def log_message(self, *args):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        srv.received = []
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield srv
        srv.shutdown()

    def test_roundtrip(self, fake_server):
        base = f"http://127.0.0.1:{fake_server.server_port}"
        result = remote_call("click", {"x": 1, "y": 2}, base)
        assert result["ok"] is True
        assert result["data"]["status"] == "ok"
        assert len(fake_server.received) == 1
        sent = json.loads(fake_server.received[0].decode("utf-8"))
        assert sent["tool"] == "click"
        assert sent["params"] == {"x": 1, "y": 2}

    def test_failure_not_silent(self):
        """转发失败必须显式报错（禁止静默成功，INV-7 同构要求）。"""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with pytest.raises(Exception) as ei:
            remote_call("click", {"x": 1, "y": 2},
                        f"http://127.0.0.1:{port}")
        assert "无法连接" in str(ei.value) or "Errno" in str(ei.value)


class TestAttachRouting:
    """ISS-0001 验收回归：HTTP 通道的 attach 必须走绑定创建（与 stdio 语义一致）。"""

    def test_call_tool_attach_returns_token(self, policy, approvals, estop,
                                            executor, audit_log, clock):
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.tools import ToolContext, call_tool

        class FakeWinExec:
            def find_windows(self, **kw):
                return [{"hwnd": FIXTURE_HWND, "process": "notepad.exe",
                         "rect": [100, 100, 800, 600]}]

        bindings = BindingManager(FakeProbe(), policy.binding_ttl, clock)
        en = Enforcement(policy, bindings, approvals, estop, executor, audit_log)
        ctx = ToolContext(policy=policy, enforcement=en, bindings=bindings,
                          executor=FakeWinExec(), audit=audit_log)
        r = call_tool(ctx, "attach", {"title": "x"})
        assert r.ok is True
        assert r.data["token"]
        assert r.data["process"] == "notepad.exe"
        assert bindings.validate(r.data["token"]) is not None
