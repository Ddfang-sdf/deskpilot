"""ISS-0002 急停复位通道单元测试（测试设计说明书 §3.8 TC-N-EST-02～06）。

入口：main.main()（瘦代理探活跳过 / --reset）、main._hotkey_loop（重试告警）、
HttpDaemon POST /estop/reset、EstopMonitor 复位方法。
断言值来源：被调方法返回值 / HTTP 响应体 / 审计 JSONL（持久化数据）/ 桩调用记录。
"""

from __future__ import annotations

import json
import urllib.request
from unittest.mock import Mock

import pytest
import yaml

from deskpilot.httpd import HttpDaemon

from .conftest import policy_yaml_dict, read_audit


def _post_empty(port: int, path: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=b"",
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestProxySkipsHotkey:
    """TC-N-EST-02 瘦代理跳过热键注册（P1 / 单测 / F-CORE-05 / ISS-0002）。"""

    def test_proxy_skips_hotkey_registration(self, tmp_path, monkeypatch):
        import deskpilot.main as m

        policy_file = tmp_path / "policy.yml"
        policy_file.write_text(
            yaml.dump(policy_yaml_dict(str(tmp_path / "audit"))),
            encoding="utf-8")
        monkeypatch.setattr(m, "_find_policy_path", lambda: policy_file)
        monkeypatch.setattr(m, "probe_daemon", lambda *a, **k: True)
        starter = Mock()                       # 热键/甩角线程启动桩
        monkeypatch.setattr(m, "_start_estop_listeners", starter)
        monkeypatch.setattr(m, "serve", lambda *a, **k: None)
        rc = m.main()
        assert rc == 0
        assert starter.call_count == 0
        events = read_audit(str(tmp_path / "audit"))
        assert sum(1 for e in events
                   if e["event"] == "瘦代理跳过热键注册") == 1


class TestHotkeyRetry:
    """TC-N-EST-03 热键注册失败重试与告警（P1 / 单测 / ISS-0002）。"""

    def test_retry_backoff_and_alarm(self, estop, audit_log, tmp_path,
                                     monkeypatch, capsys):
        import ctypes

        import deskpilot.main as m

        calls = {"n": 0}

        def fake_register(hwnd, hotkey_id, mods, vk):
            calls["n"] += 1
            return 1 if calls["n"] > 6 else 0   # 前 3 轮（每次 2 个键）失败

        monkeypatch.setattr(ctypes.windll.user32, "RegisterHotKey", fake_register)
        monkeypatch.setattr(ctypes.windll.user32, "GetMessageW", lambda *a: 0)
        sleeps: list[float] = []
        m._hotkey_loop(estop, audit_log, sleep=sleeps.append)
        assert sleeps == [1, 2, 4]
        events = read_audit(str(tmp_path / "audit"))
        assert sum(1 for e in events
                   if e["event"] == "急停热键注册失败") == 3
        assert sum(1 for e in events
                   if e["event"] == "急停热键注册") == 1
        assert capsys.readouterr().err != ""


class TestHttpResetEndpoint:
    """TC-N-EST-04 HTTP 复位端点（P1 / 单测 / INV-10 / ISS-0002）。"""

    @pytest.fixture
    def daemon(self, ctx, estop):
        d = HttpDaemon(ctx, host="127.0.0.1", port=0, estop=estop)
        d.start()
        yield d
        d.stop()

    def test_reset_endpoint(self, daemon, estop, tmp_path):
        estop.on_trigger_hotkey()                # 置位冻结
        assert estop.is_frozen() is True
        status1, body1 = _post_empty(daemon.port, "/estop/reset")
        assert status1 == 200
        assert body1["ok"] is True
        assert body1["data"]["was_frozen"] is True
        assert estop.is_frozen() is False
        status2, body2 = _post_empty(daemon.port, "/estop/reset")
        assert status2 == 200
        assert body2["data"]["was_frozen"] is False
        events = read_audit(str(tmp_path / "audit"))
        assert sum(1 for e in events if e["event"] == "急停复位") == 1
        assert sum(1 for e in events
                   if e["event"] == "复位请求-未冻结") == 1


class TestCliReset:
    """TC-N-EST-05 CLI --reset 入口（P1 / 单测 / INV-10 / ISS-0002）。"""

    def test_reset_online(self, monkeypatch, capsys):
        import deskpilot.main as m

        posts: list[str] = []
        monkeypatch.setattr(m, "probe_daemon", lambda *a, **k: True)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(
                    {"ok": True, "error_code": "", "message": "已复位",
                     "data": {"was_frozen": True, "frozen": False}}
                ).encode("utf-8")

        def fake_urlopen(req, timeout=0):
            posts.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr("sys.argv", ["deskpilot", "--reset"])
        rc = m.main()
        assert rc == 0
        assert len(posts) == 1
        assert posts[0].endswith("/estop/reset")

    def test_reset_offline_errors(self, monkeypatch, capsys):
        import deskpilot.main as m

        monkeypatch.setattr(m, "probe_daemon", lambda *a, **k: False)
        posts: list[str] = []
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda req, timeout=0: posts.append(req.full_url))
        monkeypatch.setattr("sys.argv", ["deskpilot", "--reset"])
        rc = m.main()
        assert rc != 0
        assert posts == []
        assert "无法连接" in capsys.readouterr().err


class TestResetNoopAudited:
    """TC-N-EST-06 复位 no-op 记审计（P1 / 单测 / ISS-0002）。"""

    def test_reset_noop_leaves_audit(self, estop, tmp_path):
        estop.on_reset_hotkey()
        estop.cli_reset()
        assert estop.is_frozen() is False
        events = read_audit(str(tmp_path / "audit"))
        noop = [e for e in events if e["event"] == "复位请求-未冻结"]
        assert len(noop) == 2
        assert all(e["detail"] for e in noop)
