"""ISS-0002 急停复位通道单元测试（测试设计说明书 §3.8 TC-N-EST-02/03/06）。

入口：main.main()（瘦代理探活跳过）、main._hotkey_loop（重试告警）、
EstopMonitor 复位方法。
断言值来源：被调方法返回值 / 审计 JSONL（持久化数据）/ 桩调用记录。

ISS-0093 §11 退役登记:TC-N-EST-04(TestHttpResetEndpoint)/TC-N-EST-05
(TestCliReset)随 /estop/reset 端点与 --reset CLI 一并删除(sdfang 裁定)
——不再探测「HTTP/CLI 复位」,通道本身不复存在。
TC-N-EST-06(TestResetNoopAudited)适配:cli_reset 半改热键,载体收口,
noop 审计语义保留。
"""

from __future__ import annotations

from unittest.mock import Mock

import yaml

from deskpilot.audit_events import (
    EV_HOTKEY_REGISTERED,
    EV_HOTKEY_REGISTER_FAILED,
    EV_PROXY_SKIPS_HOTKEY,
    EV_RESET_NOOP_NOT_FROZEN)
from .conftest import policy_yaml_dict, read_audit


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
                   if e["event"] == EV_PROXY_SKIPS_HOTKEY) == 1


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
        # ISS-0084 ②节流:失败审计只记**首次**——逐次审计正是 2026-09-14 实机的
        # 每分钟刷屏之源;恢复时记一条带「恢复」的成功事件。退避节奏不变。
        assert sum(1 for e in events
                   if e["event"] == EV_HOTKEY_REGISTER_FAILED) == 1
        ok_events = [e for e in events if e["event"] == EV_HOTKEY_REGISTERED]
        assert len(ok_events) == 1 and "恢复" in ok_events[0]["detail"]
        assert capsys.readouterr().err != ""


class TestResetNoopAudited:
    """TC-N-EST-06 复位 no-op 记审计（P1 / 单测 / ISS-0002）。

    ISS-0093 §11 适配:原「热键+cli_reset」两半随 CLI 通道删除收口为
    纯热键——noop 审计语义不变,载体为人类独占通道。"""

    def test_reset_noop_leaves_audit(self, estop, tmp_path):
        estop.on_reset_hotkey()
        estop.on_reset_hotkey()
        assert estop.is_frozen() is False
        events = read_audit(str(tmp_path / "audit"))
        noop = [e for e in events if e["event"] == EV_RESET_NOOP_NOT_FROZEN]
        assert len(noop) == 2
        assert all(e["detail"] for e in noop)
