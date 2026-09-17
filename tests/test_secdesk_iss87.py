"""ISS-0087 安全桌面显式检测与全禁测试(sd01~sd07,问题单 §6 v0.2 补立)。

层级:sd01~sd05/sd07 单元(detector/executor/enforcement 桩,允许打桩,
断言在返回值/桩记录直出);sd06 集成(真实 SecureDesktopGuard=真 Win32
检测通道+真 Executor mss 截屏,禁桩,断言在返回值与盘上 PNG 直读)。

入口(设计):tools.call_tool 统一调度(安全桌面闸门所在公开入口);
SecureDesktopGuard.check()(单据 §6 裁定:闸门落点 tools.call_tool 顶部)。

断言出处:ok/error_code/message=ToolResult 返回值直出;调用计数=桩记录
直出;审计事件=记录桩直出(单元)/AuditLogger JSONL 直读(集成);
盘上 PNG=Path.exists() 直读。

红态预期(P1 空壳 check() 恒 False):sd01/sd02/sd04/sd05 红(禁令未启用,
操作照常执行);sd03/sd06/sd07 绿(放行/边界钉,防过修与验证链属性)。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from deskpilot import errors
from deskpilot.enforcement import Enforcement
from deskpilot.estop import EstopMonitor
from deskpilot.models import Decision
from deskpilot.secure_desktop import SecureDesktopGuard
from deskpilot.tools import ToolContext, call_tool

from .conftest import FakeExecutor


class _AuditRec:
    """审计记录桩(单元层允许打桩;断言直读 events/entries)。"""

    def __init__(self) -> None:
        self._events: list[str] = []
        self.entries: list = []

    def record_event(self, event: str, detail: str = "") -> None:
        self._events.append(event)

    def record(self, entry) -> None:
        self.entries.append(entry)

    def events(self) -> list[str]:
        return list(self._events)


class _ExecStub:
    """executor 桩:L0 调用记录并返回固定 dict;find_windows 供 attach 前置。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def screenshot(self, *a, **k) -> dict:
        self.calls.append("screenshot")
        return {"path": "stub.png", "width": 1, "height": 1}

    def find_windows(self, *a, **k) -> list:
        self.calls.append("find_windows")
        return []


class _EnfStub:
    """enforcement 桩:记录 submit 接触(闸门生效时断言零接触)。"""

    def __init__(self) -> None:
        self.submits: list = []

    def submit(self, request) -> Decision:
        self.submits.append(request)
        return Decision(True, "", "ok", "L2")


def _ctx(policy, guard, ex, enf, audit) -> ToolContext:
    return ToolContext(policy=policy, enforcement=enf, executor=ex,
                       audit=audit, secure_guard=guard)


class TestSecureDesktopBan:
    """sd01/sd02:激活态全禁(L0/写/attach),拒绝结构化+审计留痕。"""

    def test_sd01_secure_desktop_bans_l0_sensing(self, policy):
        """sd01(单元,整改②):detector=True → screenshot 拒 SECURE_DESKTOP,
        执行层零接触,审计含「安全桌面激活」+「安全桌面拒绝」。
        红态(P1 空壳):闸门不放禁令 → 截图照常执行 → ok=True 立红。"""
        rec = _AuditRec()
        guard = SecureDesktopGuard(detector=lambda: True, audit=rec)
        ex = _ExecStub()
        ctx = _ctx(policy, guard, ex, _EnfStub(), rec)
        r = call_tool(ctx, "screenshot", {"scope": "fullscreen"})
        assert r.ok is False                    # 返回值直出
        assert r.error_code == errors.SECURE_DESKTOP
        assert "稍后" in r.message or "重试" in r.message   # AI 自愈指引
        assert ex.calls == []                   # 截图未执行(桩记录直出)
        assert "安全桌面激活" in rec.events()    # 进入边沿(桩记录直出)
        assert "安全桌面拒绝" in rec.events()    # 拒绝留痕(桩记录直出)

    def test_sd02_secure_desktop_bans_write_and_attach(self, policy):
        """sd02(单元,整改②):detector=True → click(写)/attach 均拒
        SECURE_DESKTOP,强制层零接触(闸门在路由之前)。
        红态(P1 空壳):click 流经桩返回 ok=True;attach 走 find_windows
        → TARGET_NOT_FOUND——均非 SECURE_DESKTOP 立红。"""
        rec = _AuditRec()
        guard = SecureDesktopGuard(detector=lambda: True, audit=rec)
        enf = _EnfStub()
        ctx = _ctx(policy, guard, _ExecStub(), enf, rec)
        r1 = call_tool(ctx, "click", {"token": "t", "x": 1, "y": 2})
        r2 = call_tool(ctx, "attach", {"title": "x"})
        assert r1.error_code == errors.SECURE_DESKTOP   # 返回值直出
        assert r2.error_code == errors.SECURE_DESKTOP
        assert enf.submits == []                # 强制层零接触(桩记录直出)


class TestNormalDesktopFlows:
    """sd03/sd06:正常桌面放行(防过修+真实检测通道无误禁)。"""

    def test_sd03_normal_desktop_allows_sensing(self, policy):
        """sd03(单元,防过修):detector=False → screenshot 正常执行。
        红期即绿(放行回归守卫)。"""
        rec = _AuditRec()
        guard = SecureDesktopGuard(detector=lambda: False, audit=rec)
        ex = _ExecStub()
        ctx = _ctx(policy, guard, ex, _EnfStub(), rec)
        r = call_tool(ctx, "screenshot", {"scope": "fullscreen"})
        assert r.ok is True                     # 返回值直出
        assert ex.calls == ["screenshot"]       # 桩记录直出

    def test_sd06_real_detector_no_false_ban(self, policy, tmp_path,
                                             bindings, approvals):
        """sd06(集成,禁桩):真实 Win32 检测通道在活动未锁屏桌面不误禁;
        真实 Executor 截屏落盘。红期即绿(验证链:若真检测误判激活,
        本用例立红——防「全禁常态桌面」过修事故)。"""
        from deskpilot.audit import AuditLogger
        from deskpilot.executor import DesktopProbe, Executor

        audit = AuditLogger(str(tmp_path / "audit"))
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit)
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      probe=DesktopProbe())
        enf = Enforcement(policy, bindings, approvals, estop, ex, audit)
        guard = SecureDesktopGuard(audit=audit)     # 真实检测通道
        ctx = ToolContext(policy=policy, enforcement=enf, bindings=bindings,
                          executor=ex, audit=audit, secure_guard=guard)
        r = call_tool(ctx, "screenshot", {"scope": "fullscreen"})
        assert r.ok is True, r.message          # 活动桌面不得误判(返回值直出)
        assert Path(r.data["path"]).exists()    # 盘上 PNG 直读(数据层)


class TestFailClosedAndRecovery:
    """sd04/sd05:检测失效 fail-closed + 退出自动恢复 + 边沿审计序列。"""

    def test_sd04_detector_failure_fails_closed(self, policy):
        """sd04(单元,整改②+§4 fail-closed):detector 抛 OSError →
        按激活拒绝 SECURE_DESKTOP + 审计「安全桌面检测失效」。
        红态(P1 空壳):检测不被调用 → 截图照常 → ok=True 立红。"""
        rec = _AuditRec()

        def _boom():
            raise OSError("桩:OpenInputDesktop 失败")

        guard = SecureDesktopGuard(detector=_boom, audit=rec)
        ex = _ExecStub()
        ctx = _ctx(policy, guard, ex, _EnfStub(), rec)
        r = call_tool(ctx, "screenshot", {"scope": "fullscreen"})
        assert r.ok is False
        assert r.error_code == errors.SECURE_DESKTOP
        assert ex.calls == []
        assert "安全桌面检测失效" in rec.events()   # 桩记录直出

    def test_sd05_exit_auto_recovers_with_edge_audit(self, policy):
        """sd05(单元,整改②③+§4 自动恢复):detector 序列 [True,False,True]
        → 拒→通→拒,无需人工复位;审计边沿序列精确:
        激活→拒绝→退出→激活→拒绝。
        红态(P1 空壳):三次全通 → ok 序列 [True,True,True] 立红。"""
        rec = _AuditRec()
        seq = iter([True, False, True])
        guard = SecureDesktopGuard(detector=lambda: next(seq), audit=rec)
        ex = _ExecStub()
        ctx = _ctx(policy, guard, ex, _EnfStub(), rec)
        results = [call_tool(ctx, "screenshot", {"scope": "fullscreen"})
                   for _ in range(3)]
        assert [r.ok for r in results] == [False, True, False]   # 直出
        assert rec.events() == ["安全桌面激活", "安全桌面拒绝",
                                "安全桌面退出",
                                "安全桌面激活", "安全桌面拒绝"]  # 桩记录直出


class TestOrdinaryFreezeBoundaryUnchanged:
    """sd07:普通(甩角/热键)冻结的既有边界不回退——写拒 L0 放行。"""

    def test_sd07_ordinary_freeze_boundary(self, policy, bindings, approvals,
                                           audit_log, bound_record, clock):
        """sd07(单元,整改④不弱化既有):estop 经热键入口真冻结 +
        detector=False → click 仍 EMERGENCY_STOP(写禁),
        screenshot 仍放行(ISS-0003 冻结期 L0 边界不回退)。
        红期即绿(边界钉:本单不得改变普通冻结语义)。"""
        estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log)
        estop.on_trigger_hotkey()               # 真实冻结(公开入口)
        assert estop.is_frozen() is True        # 前提:已冻结
        fake_ex = FakeExecutor()
        enf = Enforcement(policy, bindings, approvals, estop, fake_ex,
                          audit_log)
        ex = _ExecStub()
        guard = SecureDesktopGuard(detector=lambda: False, audit=audit_log)
        ctx = ToolContext(policy=policy, enforcement=enf, bindings=bindings,
                          executor=ex, audit=audit_log, secure_guard=guard)
        r_click = call_tool(ctx, "click",
                            {"token": bound_record.token, "x": 300, "y": 300})
        assert r_click.ok is False
        assert r_click.error_code == errors.EMERGENCY_STOP   # 写仍拒(直出)
        r_ss = call_tool(ctx, "screenshot", {"scope": "fullscreen"})
        assert r_ss.ok is True                  # L0 仍放行(直出)
        assert ex.calls == ["screenshot"]
