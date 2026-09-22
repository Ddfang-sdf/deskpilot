"""ISS-0094 心跳写健壮性+tmp pid 化测试(TC-94-01~05,问题单 §4.5 ①②/§5 裁决)。

背景:冻结形态 heartbeat 间歇不写——B-2 静默写失败(ownership._loop
except 全吞,无重试无审计,对照 freeze_notify ISS-0092 ② 防护不对称)+
B-3 复出窗口双 HeartbeatWriter 共用 daemon-heartbeat.tmp 互踩丢拍。
批准范围:①beat_once OSError 三段退避重试+终败节流审计「心跳写失败」
(连续失败只记首败,恢复另记;不上抛不阻断主功能);②tmp 按 pid 区分
+预清孤儿;③观测面消歧文档;端口加固不做(ISS-0108 另案)。

层级分布:
- 单元:TC-94-01/02/03(os.replace/sleep 桩+审计桩+真临时目录,仿 fg 系列)
- 单元(行为保持):TC-94-04(抢锁失败停心跳语义不回退,P1 即绿属正确落点)
- 集成形态(进程内驱动 main.main):TC-94-05(stdio 属主持锁时起 --daemon
  →退出码 4+审计「daemon 单例退出」+heartbeat 归当前属主;LOCALAPPDATA
  重定向 tmp,不触真共享目录;语义多系既有,P1 可能即绿=防回归钉)

入口(设计):HeartbeatWriter(beat_once/start/stop)/OwnerLock/
RoleSupervisor.start/main.main(--daemon 路径)。
断言出处:桩 sleep 序列直出/审计桩记录直读/盘上 glob 与 JSON 直读/
替身 os.replace 记录直出/main() 返回值与审计 JSONL 直读——均直出。

P1 红态预期:TC-94-01 红(现状无重试,首次 OSError 即上抛);TC-94-02 红
(同上);TC-94-03 红(现状 tmp 无 pid 区分);TC-94-04/05 绿(行为保持面)。
"""

from __future__ import annotations

import json
import threading
import time

import pytest
import yaml

from deskpilot.ownership import (HeartbeatWriter, OwnerLock, RoleSupervisor)

from .conftest import policy_yaml_dict, read_audit


class _FakeAudit:
    """审计记录桩(单元层允许打桩;断言直读 records)。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def record_event(self, event: str, detail: str = "") -> None:
        self.records.append((event, detail))

    def count(self, event: str) -> int:
        return sum(1 for e, _ in self.records if e == event)


def _boom_replace(src, dst):
    raise OSError("桩:目标文件被占用(杀软拦截模拟)")


class TestBeatWriteResilience:
    """TC-94-01/02(§4.5 ①):重试退避+终败节流审计+不上抛不阻断。"""

    def test_tc94_01_beat_retry_backoff_terminal_audit(self, tmp_path,
                                                       monkeypatch):
        """TC-94-01(单元,①):os.replace 持续 OSError → beat_once 重试 3 次
        (退避序列 0.05/0.15/0.45 直出)→终败审计恰 1 条「心跳写失败」→
        返回 None 不上抛;心跳线程在持续失败下存活。
        断言:桩 sleep 序列直出;审计桩记录直读;is_alive 直出。
        红态:现状无重试,首次 OSError 即沿 beat_once 上抛(零审计)。"""
        import deskpilot.ownership as ow

        sleeps: list[float] = []
        monkeypatch.setattr(ow.time, "sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(ow.os, "replace", _boom_replace)
        audit = _FakeAudit()
        hb = HeartbeatWriter(str(tmp_path), "daemon", interval=0.05,
                             audit=audit)
        r = hb.beat_once()
        assert r is None, "终败返回 None 不上抛(返回值直出)"
        assert sleeps == [0.05, 0.15, 0.45], \
            f"三段退避序列(桩记录直出): {sleeps}"
        assert audit.count("心跳写失败") == 1, \
            f"终败审计恰 1 条(桩记录直读): {audit.records}"

        hb.start()                           # 持续失败下线程不许死
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and (
                hb._thread is None or not hb._thread.is_alive()):
            time.sleep(0.02)
        try:
            assert hb._thread is not None and hb._thread.is_alive(), \
                "心跳线程在持续写失败下必须存活(is_alive 直出)"
        finally:
            hb.stop()
        assert not hb._thread.is_alive() if hb._thread else True

    def test_tc94_02_throttle_first_failure_and_recovery(self, tmp_path,
                                                         monkeypatch):
        """TC-94-02(单元,①节流):连续失败两轮只记首败(「心跳写失败」
        恰 1 条);恢复(写盘转成功)后另记一条恢复事件;再失败重新计首败。
        断言:审计桩记录直读。
        红态:现状无审计无节流(首次 OSError 即上抛)。"""
        import deskpilot.ownership as ow

        monkeypatch.setattr(ow.time, "sleep", lambda s: None)
        audit = _FakeAudit()
        hb = HeartbeatWriter(str(tmp_path), "daemon", audit=audit)
        real_replace = ow.os.replace
        monkeypatch.setattr(ow.os, "replace", _boom_replace)
        hb.beat_once()
        hb.beat_once()                         # 连续第二轮失败:节流不记
        assert audit.count("心跳写失败") == 1, \
            f"连续失败只记首败(桩记录直读): {audit.records}"
        monkeypatch.setattr(ow.os, "replace", real_replace)
        hb.beat_once()                         # 恢复:另记一条
        assert audit.count("心跳写失败") == 1
        recovery = [e for e, _ in audit.records if "恢复" in e]
        assert len(recovery) == 1, \
            f"恢复另记一条(桩记录直读): {audit.records}"


class TestTmpPerPid:
    """TC-94-03(§4.5 ②):tmp 按 pid 区分,并发双写无互踩无残留。"""

    def test_tc94_03_concurrent_writers_pid_tmp_no_residue(self, tmp_path,
                                                           monkeypatch):
        """TC-94-03(单元,②):双 HeartbeatWriter 同目录(pid 111111/222222,
        构造期 getpid 桩)并发 beat 各 30 轮 → 盘上零 .tmp 残留;替身
        os.replace 记录显示 tmp 名各含自身 pid;最终 heartbeat.json 为
        合法 JSON 且 pid/role 自洽(无交叉内容)。
        断言:盘上 glob 直读;替身 replace 记录直出;JSON 直读。
        红态:现状 tmp 统一 daemon-heartbeat.tmp(无双 pid 名)。"""
        import deskpilot.ownership as ow

        with monkeypatch.context() as m:
            m.setattr(ow.os, "getpid", lambda: 111111)
            hb1 = HeartbeatWriter(str(tmp_path), "daemon")
        with monkeypatch.context() as m:
            m.setattr(ow.os, "getpid", lambda: 222222)
            hb2 = HeartbeatWriter(str(tmp_path), "stdio")

        replaced: list[str] = []
        real_replace = ow.os.replace

        def _rec_replace(src, dst):
            replaced.append(str(src))
            return real_replace(src, dst)

        monkeypatch.setattr(ow.os, "replace", _rec_replace)
        threads = [threading.Thread(
            target=lambda h: [h.beat_once() for _ in range(30)], args=(h,))
            for h in (hb1, hb2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        for t in threads:
            assert not t.is_alive()

        leftovers = list(tmp_path.glob("daemon-heartbeat*.tmp"))
        assert leftovers == [], f"并发后零 .tmp 残留(盘上 glob 直读): {leftovers}"
        names = {p.replace("\\", "/").rsplit("/", 1)[-1] for p in replaced}
        assert "daemon-heartbeat.111111.tmp" in names, \
            f"tmp 名须含各自 pid(替身记录直出): {names}"
        assert "daemon-heartbeat.222222.tmp" in names
        assert "daemon-heartbeat.tmp" not in names, \
            "统一 tmp 名已废(②落地,替身记录直出)"
        data = json.loads((tmp_path / "daemon-heartbeat.json")
                          .read_text(encoding="utf-8"))
        pair = {111111: "daemon", 222222: "stdio"}
        assert data["pid"] in pair and data["role"] == pair[data["pid"]], \
            f"最终心跳内容须 pid/role 自洽无交叉(JSON 直读): {data}"


class TestLockFailStopsHeartbeat:
    """TC-94-04(行为保持,§4.5 ①约束):抢锁失败停心跳语义不回退。"""

    def test_tc94_04_lock_fail_stops_heartbeat(self, tmp_path):
        """TC-94-04(单元,约束保留):属主锁被持 → RoleSupervisor.start
        返回 False 且心跳已停(_heartbeat 置 None,无心跳线程)。
        断言:返回值直出;内部状态直读。
        P1 即绿(正确落点):该语义为既有设计(ownership.py:254-257),
        批准范围明令保留——本钉防实现误伤。"""
        holder = OwnerLock(str(tmp_path), "stdio")
        assert holder.acquire() is True
        try:
            sup = RoleSupervisor(str(tmp_path), "daemon")
            assert sup.start() is False            # 抢锁失败(返回值直出)
            assert sup._heartbeat is None, \
                "抢锁失败须停心跳(状态直读,语义不回退)"
        finally:
            holder.release()


class TestDaemonSingleExit:
    """TC-94-05(集成形态,§4.5 ⑤):stdio 属主持锁时起 --daemon。"""

    def test_tc94_05_daemon_exits_4_heartbeat_stays_owner(self, tmp_path,
                                                          monkeypatch):
        """TC-94-05(集成形态,进程内驱动 main.main;LOCALAPPDATA 重定向
        tmp 不触真共享目录):stdio 属主持锁+快心跳 → main --daemon
        12 次抢锁全败 → 退出码 4;审计恰 1 条「daemon 单例退出」;
        heartbeat 最终归当前属主(role=stdio,败者内容被覆盖)。
        断言:main() 返回值直出;审计 JSONL 直读;heartbeat JSON 直读。
        P1 预期绿(防回归钉):退出码/单例审计/心跳归属均系既有语义。"""
        import deskpilot.main as m

        shared = tmp_path / "DeskPilot"
        shared.mkdir()
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        policy_file = tmp_path / "policy.yml"
        policy_file.write_text(
            yaml.dump(policy_yaml_dict(str(tmp_path / "audit"))),
            encoding="utf-8")
        monkeypatch.setattr(m, "_find_policy_path", lambda: policy_file)

        holder = OwnerLock(str(shared), "stdio")
        assert holder.acquire() is True
        owner_hb = HeartbeatWriter(str(shared), "stdio", interval=0.05)
        owner_hb.beat_once()
        owner_hb.start()
        monkeypatch.setattr(m.time, "sleep", lambda s: None)  # 重试不等
        monkeypatch.setattr("sys.argv", ["deskpilot", "--daemon"])
        try:
            rc = m.main()
            threading.Event().wait(0.3)        # 属主下一轮心跳覆盖败者
        finally:
            owner_hb.stop()
            holder.release()
        assert rc == 4                           # 返回值直出
        events = read_audit(str(tmp_path / "audit"))
        assert sum(1 for e in events
                   if e.get("event") == "daemon 单例退出") == 1, \
            "审计恰 1 条「daemon 单例退出」(JSONL 直读)"
        data = json.loads((shared / "daemon-heartbeat.json")
                          .read_text(encoding="utf-8"))
        assert data["role"] == "stdio", \
            f"heartbeat 归当前属主(败者不占有,JSON 直读): {data}"
