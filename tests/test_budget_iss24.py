"""ISS-0024 L3 预算决议测试(TC-BT-01~05,问题单 §4/§5 v0.2 评审通过)。

层级:TC-BT-01~03 单元(resolve_budget 纯函数直出);
TC-BT-04/05 集成(真 HttpDaemon+慢审批通道,断言在 HTTP 响应体)。
入口(设计):httpd.resolve_budget(level, policy) / 真 POST /call。
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from deskpilot import errors
from deskpilot.httpd import resolve_budget


class TestResolveBudgetUnit:
    """TC-BT-01~03:预算决议按级别与审批时限(返回值直出)。"""

    def test_bt01_l2_write_gets_approval_budget(self, policy):
        """TC-BT-01:L2 写工具(可升级 L3) → approval_ttl+5。
        (ISS-0039 R4:签名改 (tool, level, policy),断言值不变)"""
        assert resolve_budget("click", "L2", policy) == policy.approval_ttl + 5

    def test_bt02_l0_unchanged(self, policy):
        """TC-BT-02:L0 → 静态预算 5s。"""
        assert resolve_budget("find_window", "L0", policy) == 5.0

    def test_bt03_l1_escalation_tier(self, policy):
        """TC-BT-03(ISS-0033 A3 重指):L1 可升级(attach 入白/终端绑定)
        → 与 L2 同档 approval_ttl+5。"""
        assert resolve_budget("wait_for_window", "L1", policy) == policy.approval_ttl + 5


class SlowApproveChannel:
    """审批通道接缝(设计注入点):真实睡眠 35s 后批准。

    判别点:旧预算 30s 会先到期返回 TOOL_TIMEOUT;新预算 65s
    (fixture approval_ttl=60+5)可通过——同一装配区分新旧行为。
    """

    def __init__(self, decision: str = "approve", sleep_s: float = 35.0):
        self.decision = decision
        self.sleep_s = sleep_s
        self.requests: list[dict] = []

    def request(self, description, fingerprint, image_path=None,
                target_rect=None, enroll=None) -> str:
        self.requests.append({"description": description,
                              "fingerprint": fingerprint})
        time.sleep(self.sleep_s)
        return self.decision


class TestBudgetAssembly:
    """TC-BT-04/05 装配(assembly)测试(ISS-0033 C2 重分类)。

    真实部件:HttpDaemon / Enforcement / BindingManager / ApprovalManager /
    审批链闸门;替身:SlowApproveChannel(审批通道 sleep 接缝)/FakeExecutor/
    FakeProbe/FakeClock(共 4 处)。断层面:HTTP 响应体。按三层定义含替身
    不授 integration 标签,降级 assembly 并如实列明。"""

    def _make_daemon(self, policy, audit_log, tmp_path, channel):
        from deskpilot.approval import ApprovalManager
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.estop import EstopMonitor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext

        from .conftest import (FIXTURE_HWND, FIXTURE_RECT, FakeClock,
                               FakeExecutor, FakeProbe)

        probe = FakeProbe()
        clock = FakeClock()
        estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log)
        bindings = BindingManager(probe, policy.binding_ttl, clock)
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        approvals = ApprovalManager(channel, policy.approval_ttl, clock)
        enforcement = Enforcement(policy, bindings, approvals, estop,
                                  FakeExecutor(), audit_log)
        ctx = ToolContext(policy=policy, enforcement=enforcement,
                          bindings=bindings, executor=enforcement._executor,
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
        return d, rec

    def _call(self, port, tool, params, timeout=90):
        body = json.dumps({"tool": tool, "params": params}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/call",
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_bt04_approval_35s_completes(self, policy, audit_log, tmp_path):
        """TC-BT-04:审批 35s 完成不超时(判别性:旧预算 30s 必 TOOL_TIMEOUT)。"""
        channel = SlowApproveChannel()
        d, rec = self._make_daemon(policy, audit_log, tmp_path, channel)
        try:
            r = self._call(d.port, "key",
                           {"key": "alt+f4", "token": rec.token}, timeout=90)
            assert r["ok"] is True, r.get("message")
            assert channel.requests, "审批通道未被请求"
        finally:
            d.stop()

    def test_bt05_approval_timeout_semantics(self, policy, audit_log,
                                             tmp_path):
        """TC-BT-05:审批超时仍走 APPROVAL_TIMEOUT(语义锁定,回归守护)。"""
        channel = SlowApproveChannel(decision="timeout", sleep_s=1.0)
        d, rec = self._make_daemon(policy, audit_log, tmp_path, channel)
        try:
            r = self._call(d.port, "key",
                           {"key": "alt+f4", "token": rec.token}, timeout=90)
            assert r["ok"] is False
            assert r["error_code"] == errors.APPROVAL_TIMEOUT
        finally:
            d.stop()
