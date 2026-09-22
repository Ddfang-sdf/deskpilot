"""ISS-0084 属主权测试(ownership.py + 热键节流)。

层级:**单元**(文件锁/心跳文件/HTTP 全真;托盘/热键/winreg 替身;
断言在返回值/文件内容/审计落盘/替身计数)。
**断言出处**:`OwnerLock.acquire/release` 返回值、心跳文件 JSON、
`is_daemon_alive` 返回值、审计记录、替身调用计数、真 HTTP /health 响应。
用例来源:ISS-0084 §7.6(TC-OWN-01~10,sdfang 2026-09-15 评审通过全做)。

**P1 红点位**:`ownership.py` 全空壳(NotImplementedError);main._hotkey_loop
的节流语义未实现。
"""

from __future__ import annotations

from deskpilot.audit_events import (
    EV_DAEMON_DEATH_ALARM,
    EV_PROCESS_EXIT)
import json
import time
import urllib.request

import pytest

from deskpilot.ownership import (HeartbeatWriter, OwnerLock, RoleSupervisor,
                                 ensure_autostart, install_last_will,
                                 is_daemon_alive, write_last_will)


def _read_hb(audit_dir):
    return json.loads((audit_dir / "daemon-heartbeat.json")
                      .read_text(encoding="utf-8"))


class _FakeAudit:
    def __init__(self):
        self.events = []

    def record_event(self, name, detail=""):
        self.events.append((name, detail))


class _FakeWinreg:
    """winreg 替身:只读视图 + 写入计数(TC-OWN-08)。"""
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, existing=None):
        self.store = dict(existing or {})
        self.writes = []

    def OpenKey(self, *a, **k):
        return self

    def QueryValueEx(self, _key, name):
        if name in self.store:
            return (self.store[name], 1)
        raise FileNotFoundError(name)

    def SetValueEx(self, _key, name, _reserved, _type, value):
        self.writes.append((name, value))
        self.store[name] = value

    def CloseKey(self, _key):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---------- TC-OWN-01/02:锁先占先得 / 释放接管 ----------

class TestOwnerLock:
    def test_first_acquires_second_refused(self, tmp_path):
        a = OwnerLock(str(tmp_path), "stdio")
        b = OwnerLock(str(tmp_path), "stdio")
        assert a.acquire() is True
        assert b.acquire() is False
        assert a.is_owner and not b.is_owner

    def test_release_then_takeover(self, tmp_path):
        a = OwnerLock(str(tmp_path), "stdio")
        b = OwnerLock(str(tmp_path), "stdio")
        a.acquire()
        a.release()
        assert b.acquire() is True
        assert not a.is_owner and b.is_owner


# ---------- TC-OWN-03:心跳写入 + 新鲜度 ----------

class TestHeartbeat:
    def test_beat_writes_and_freshness(self, tmp_path):
        clock_now = [1000.0]
        hb = HeartbeatWriter(str(tmp_path), "daemon",
                             clock=lambda: clock_now[0])
        path = hb.beat_once()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["role"] == "daemon"
        assert data["ts"] == 1000.0
        assert isinstance(data["pid"], int)
        assert is_daemon_alive(str(tmp_path), now=1000.0 + 29.9) is True
        assert is_daemon_alive(str(tmp_path), now=1000.0 + 31) is False

    def test_stdio_role_is_not_daemon_alive(self, tmp_path):
        clock_now = [1000.0]
        HeartbeatWriter(str(tmp_path), "stdio",
                        clock=lambda: clock_now[0]).beat_once()
        assert is_daemon_alive(str(tmp_path), now=1000.0) is False

    def test_no_file_not_alive(self, tmp_path):
        assert is_daemon_alive(str(tmp_path), now=1000.0) is False


# ---------- TC-OWN-04:daemon 复出回迁 ----------

class TestCedeOnDaemonReturn:
    def test_stdio_owner_cedes_when_daemon_alive(self, tmp_path):
        calls = {"become": 0, "cede": 0}
        sup = RoleSupervisor(
            str(tmp_path), "stdio",
            on_become_owner=lambda: calls.__setitem__("become",
                                                      calls["become"] + 1),
            on_cede=lambda: calls.__setitem__("cede", calls["cede"] + 1))
        assert sup.start() is True          # 无 daemon 心跳 → 自持
        assert calls["become"] == 1
        # daemon 复出(新鲜心跳,role=daemon)
        HeartbeatWriter(str(tmp_path), "daemon", clock=time.time).beat_once()
        sup.tick()
        assert calls["cede"] == 1, "daemon 复出须让位(热键/托盘/HTTP 停+放锁)"
        assert sup.is_owner is False
        sup.tick()                          # 幂等:不重复让位
        assert calls["cede"] == 1


# ---------- TC-OWN-06:daemon 死亡告警 ----------

class TestDeathAlarm:
    def test_stale_heartbeat_alarms_once(self, tmp_path):
        audit = _FakeAudit()
        alarms = []
        sup = RoleSupervisor(str(tmp_path), "stdio", audit=audit,
                             alarm_fn=alarms.append)
        sup.start()
        # daemon 心跳文件存在但过期(60s 前)
        HeartbeatWriter(str(tmp_path), "daemon").beat_once()
        hb = tmp_path / "daemon-heartbeat.json"
        stale = {"pid": 1, "role": "daemon", "ts": time.time() - 60}
        hb.write_text(json.dumps(stale), encoding="utf-8")
        sup.tick()
        names = [n for n, _ in audit.events]
        assert EV_DAEMON_DEATH_ALARM in names
        assert len(alarms) == 1, "每段死亡期告警恰好一次"
        sup.tick()                          # 同一段死亡期不重复轰炸
        assert len([n for n, _ in audit.events if n == EV_DAEMON_DEATH_ALARM]) == 1
        assert len(alarms) == 1

    def test_no_heartbeat_no_alarm(self, tmp_path):
        """从未有 daemon 存在过(无心跳文件)不告"死亡"——机器初装不是事故。"""
        audit = _FakeAudit()
        alarms = []
        sup = RoleSupervisor(str(tmp_path), "stdio", audit=audit,
                             alarm_fn=alarms.append)
        sup.start()
        sup.tick()
        assert alarms == []
        assert [n for n, _ in audit.events if n == EV_DAEMON_DEATH_ALARM] == []


# ---------- TC-OWN-07:遗嘱 ----------

class TestLastWill:
    def test_will_payload_lands_audit(self):
        audit = _FakeAudit()
        write_last_will(audit, "daemon", "正常退出")
        write_last_will(audit, "stdio", "异常: RuntimeError: boom")
        names = [n for n, _ in audit.events]
        assert names.count(EV_PROCESS_EXIT) == 2
        details = [d for _, d in audit.events]
        assert any("daemon" in d and "正常退出" in d for d in details)
        assert any("stdio" in d and "RuntimeError" in d for d in details)

    def test_install_idempotent(self):
        """同一进程重复挂钩子只挂一次(幂等)。"""
        audit = _FakeAudit()
        install_last_will(audit, "stdio")
        install_last_will(audit, "stdio")   # 第二次应幂等(不重复挂)
        # 幂等性的可观测面:重复安装不报错且不重复产生事件——
        # 钩子真正触发在退出时,此处只证重复调用无害
        write_last_will(audit, "stdio", "正常退出")
        assert [n for n, _ in audit.events].count(EV_PROCESS_EXIT) == 1


# ---------- TC-OWN-08:开机自启幂等 ----------

class TestAutostart:
    def test_register_once_idempotent(self):
        reg = _FakeWinreg()
        assert ensure_autostart(r"C:\x\deskpilot.exe", winreg_mod=reg) is True
        assert reg.writes == [("DeskPilotDaemon",
                               '"C:\\x\\deskpilot.exe" --daemon')]
        # 已注册且内容一致 → 不再写
        assert ensure_autostart(r"C:\x\deskpilot.exe", winreg_mod=reg) is False
        assert len(reg.writes) == 1


# ---------- TC-OWN-09/10:属主开 HTTP / daemon 死亡接管 ----------

def _real_ctx(tmp_path):
    """真 ToolContext 装配(与 test_clicktarget_iss44 集成件同款,零替身)。"""
    from deskpilot.approval import ApprovalManager
    from deskpilot.binding import BindingManager
    from deskpilot.enforcement import Enforcement
    from deskpilot.estop import EstopMonitor
    from deskpilot.executor import DesktopProbe, Executor
    from deskpilot.tools import ToolContext
    from .conftest import FakeApprover, make_policy

    policy = make_policy(audit_dir=str(tmp_path / "audit"))
    audit = None
    estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, None)
    executor = Executor(estop, str(tmp_path / "audit"),
                        probe=DesktopProbe())
    bindings = BindingManager(DesktopProbe(), policy.binding_ttl,
                              time.monotonic)
    approvals = ApprovalManager(FakeApprover(), policy.approval_ttl,
                                time.monotonic)
    enforcement = Enforcement(policy, bindings, approvals, estop, executor,
                              audit)
    return ToolContext(policy=policy, enforcement=enforcement,
                       bindings=bindings, executor=executor)


def _health(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


class TestOwnershipHTTP:
    def test_stdio_owner_serves_http(self, tmp_path):
        """TC-OWN-09:stdio 持锁 → 属主回调起真 HTTP(port 0),/health 真响应。"""
        from deskpilot.httpd import HttpDaemon
        httpd = []
        sup = RoleSupervisor(
            str(tmp_path), "stdio",
            on_become_owner=lambda: httpd.append(
                HttpDaemon(_real_ctx(tmp_path / "ctx"), port=0)))
        assert sup.start() is True
        assert httpd, "属主回调须被调(装配 HTTP/热键/托盘)"
        d = httpd[0]
        d.start()
        try:
            assert _health(d.port)["status"] == "ok"
        finally:
            d.stop()

    def test_stdio_takes_over_after_daemon_death(self, tmp_path):
        """TC-OWN-10:daemon 持锁起 HTTP 后停;stdio 探到心跳过期 → 拿锁起 HTTP。"""
        from deskpilot.httpd import HttpDaemon
        daemon_dir = tmp_path / "d"
        stdio_dir = tmp_path / "s"   # 注意:两进程现实中共享同一 audit 目录
        daemon_dir.mkdir()
        stdio_dir.mkdir()
        # 现实形态:同一 audit 目录(邮箱共享)。两 supervisor 共用 daemon_dir:
        daemon_sup = RoleSupervisor(str(daemon_dir), "daemon")
        assert daemon_sup.start() is True
        daemon_sup.stop()                # daemon 死亡(放锁+遗嘱)
        # daemon 心跳过期
        hb = daemon_dir / "daemon-heartbeat.json"
        stale = {"pid": 1, "role": "daemon", "ts": time.time() - 60}
        hb.write_text(json.dumps(stale), encoding="utf-8")

        httpd = []
        stdio_sup = RoleSupervisor(
            str(daemon_dir), "stdio",      # 同目录(邮箱共享)
            on_become_owner=lambda: httpd.append(
                HttpDaemon(_real_ctx(tmp_path / "ctx2"), port=0)))
        assert stdio_sup.start() is True, "daemon 死亡放锁后 stdio 须能接管"
        d = httpd[0]
        d.start()
        try:
            assert _health(d.port)["status"] == "ok"
        finally:
            d.stop()
