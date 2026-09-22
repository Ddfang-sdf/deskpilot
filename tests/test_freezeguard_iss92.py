"""ISS-0092 急停共享状态机写回失败健壮性测试(问题单 §4 v0.1)。

层级:fg02/fg03 单元(允许打桩,断言在桩记录/盘上文件直读/函数行为);
fg04 集成(真实 AuditLogger/FreezeNotifier/EstopMonitor+真实临时目录文件,
禁桩,断言在盘上文件与审计 JSONL 直读)。

入口(设计):FreezeNotifier.on_state_change / sync_local_with_shared_state
与 main._corner_loop 线程体——公开装配入口(模块级函数视为公开入口)。

断言出处:盘上 estop-state.json = Path 直读;审计事件=AuditLogger JSONL
直读(read_audit,集成层)/记录桩直出(单元层);线程存活 =
threading.Thread.is_alive() 直出;调用不抛 = 无 pytest.raises 包装。

ISS-0093 §11 退役登记:fg01(TestResetOrder,req 消费次序)/fg05
(TestEndToEndUnfreeze,req 半链端到端)随 req 邮箱整体删除而退役——
不再探测「req 消费可靠性」,该面缺陷随通道消亡(ISS-0093 §6 已登记,
无被掩盖缺陷);fg05 的端到端防回归由 TC-93-12(新全链,零 req)接替。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from deskpilot.estop import EstopMonitor
from deskpilot.freeze_notify import STATE_FILE, FreezeNotifier
from deskpilot.main import _corner_loop

from .conftest import read_audit


class _AuditRec:
    """审计记录桩(单元层允许打桩;断言直读 records)。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def record_event(self, event: str, detail: str = "") -> None:
        self.records.append((event, detail))

    def events(self) -> list[str]:
        return [e for e, _ in self.records]


class _EstopStub:
    """estop 桩:冻结态可控,dialog_reset 副作用可编排(逐一消费)。"""

    def __init__(self, frozen: bool, reset_effects: list | None = None) -> None:
        self._frozen = frozen
        self._reset_effects = list(reset_effects or [])
        self.reset_calls = 0
        self.corner_calls: list[tuple[int, int]] = []

    def is_frozen(self) -> bool:
        return self._frozen

    def dialog_reset(self) -> None:
        self.reset_calls += 1
        if self._reset_effects:
            effect = self._reset_effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect

    def check_corner(self, x: int, y: int) -> None:
        self.corner_calls.append((x, y))


class _NotifierStub:
    """notifier 桩(fg03 甩角循环用):退出码消费/对账为空调用并记录次数。

    ISS-0093 v0.6 适配登记:消费方法随设计更名 check_reset_request →
    check_dialog_exit(§9.2 监听循环挂点替换),桩接口跟随,计数语义不变。"""

    def __init__(self) -> None:
        self.consume_calls = 0
        self.sync_calls = 0

    def check_dialog_exit(self, estop) -> None:
        self.consume_calls += 1

    def sync_local_with_shared_state(self, estop) -> bool:
        self.sync_calls += 1
        return False


class TestWriteResilience:
    """fg02:整改②写回健壮化——有限重试+终败审计+清孤儿 tmp+不上抛。"""

    def test_fg02_write_failure_audited_no_orphan(self, tmp_path, monkeypatch):
        """fg02(单元,整改②):os.replace 持续抛 OSError → on_state_change
        正常返回+审计「共享状态写失败」+tmp 孤儿清除;frozen 边沿弹窗
        照拉(fail-safe:写失败不吞冻结通知)。

        红态(现状):on_state_change 直调 os.replace(freeze_notify.py:65)
        → OSError 直抛+tmp 孤儿残留+零审计。
        """
        import os

        def _boom(src, dst):
            raise OSError("桩:目标文件被占用")

        monkeypatch.setattr(os, "replace", _boom)
        audit = _AuditRec()
        spawned: list[str] = []
        notifier = FreezeNotifier(str(tmp_path), spawn=spawned.append,
                                  audit=audit)

        notifier.on_state_change(True, "测试")   # 终败不上抛
        assert "共享状态写失败" in audit.events()        # 桩记录直出
        assert (tmp_path / (STATE_FILE + ".tmp")).exists() is False  # 盘上直读
        assert spawned == [str(tmp_path)]        # 冻结边沿弹窗不丢(桩记录直出)


class TestCornerLoopGuard:
    """fg03:整改①甩角线程守卫——单轮异常不杀线程。"""

    def test_fg03_loop_survives_round_exception(self, monkeypatch):
        """fg03(单元,整改①):首轮 pyautogui.position 抛异常 → 线程存活
        继续轮询+审计「甩角轮询异常」;stop 置位后干净收口。

        红态(P1 空壳):_corner_loop 循环体无守卫(main.py 循环体裸奔)
        → 首轮异常即线程死亡,is_alive=False、check_corner 计数停摆。
        """
        import pyautogui

        position_calls = {"n": 0}

        def _flaky_position():
            position_calls["n"] += 1
            if position_calls["n"] == 1:
                raise Exception("桩:首轮爆炸")
            return pyautogui.Point(10, 10)

        monkeypatch.setattr(pyautogui, "position", _flaky_position)
        estop = _EstopStub(frozen=False)
        notifier = _NotifierStub()
        audit = _AuditRec()
        stop = threading.Event()
        t = threading.Thread(
            target=_corner_loop, args=(estop, notifier),
            kwargs={"audit": audit, "sleep": lambda s: None,
                    "stop": stop.is_set},
            daemon=True)
        t.start()
        try:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if estop.corner_calls or not t.is_alive():
                    break
                time.sleep(0.01)
            assert t.is_alive() is True          # 线程不许死(直出)
            assert len(estop.corner_calls) >= 1  # 异常轮之后仍有调用(桩记录)
            assert "甩角轮询异常" in audit.events()
        finally:
            stop.set()
            t.join(timeout=2.0)
        assert t.is_alive() is False             # stop 收口(直出)


class TestSharedReconcile:
    """fg04:整改④双向对账——本地未冻 ∧ 共享 frozen:true → 修复共享。"""

    def test_fg04_repair_shared_frozen_when_local_unfrozen(
            self, tmp_path, policy, audit_log):
        """fg04(集成,禁桩,整改④):共享 state 卡 frozen:true seq=15(事故
        镜像),本地未冻结 → sync 重写共享 frozen:false seq=16(单调+1
        不回退)+审计「共享状态对账修复」。

        红态(现状):sync 单向(仅本地冻→本地复位,freeze_notify.py:100-108),
        本场景返回 False,共享卡死态原样残留。
        断言出处:盘上 state=json.loads(read_text) 直读;审计=read_audit
        JSONL 直读(conftest 公开辅助)。
        """
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        state_path = shared_dir / STATE_FILE
        state_path.write_text(json.dumps(
            {"frozen": True, "seq": 15, "source": "鼠标甩角",
             "ts": datetime.now().astimezone().isoformat()},
            ensure_ascii=False), encoding="utf-8")
        notifier = FreezeNotifier(str(shared_dir), clock=time.monotonic,
                                  spawn=lambda *a, **k: None, audit=audit_log)
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log,
                             on_state_change=notifier.on_state_change)
        assert estop.is_frozen() is False        # 前提:本地未冻结

        r = notifier.sync_local_with_shared_state(estop)

        assert r is True                         # 返回值直出
        st = json.loads(state_path.read_text(encoding="utf-8"))
        assert st["frozen"] is False             # 盘上直读
        assert st["seq"] == 16                   # seq 单调+1 不回退(盘上直读)
        events = [e.get("event") for e in read_audit(str(tmp_path / "audit"))]
        assert "共享状态对账修复" in events       # 审计 JSONL 直读

