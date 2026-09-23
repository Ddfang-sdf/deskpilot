"""ISS-0019 审批批量授权模型测试（问题单 §4.1）。

层级：单元（FakeApprover/conftest 装配,断言直出）。
入口（设计）：ApprovalManager.issue_token(scope)/session_scope_of /
request_approval / enforcement 闸四批量命中 / 弹窗批量按钮。
范围语义：window_session = 同一绑定窗口+同一工具,会话内后续同类免批;
终端类与 key 类永远逐操作,不适用批量。
"""

from __future__ import annotations

import pytest

from deskpilot.models import OperationRequest


@pytest.fixture(autouse=True)
def _pin_zh(pin_zh_locale):
    """ISS-0111:本族断言中文语义面,显式钉 zh-CN 环境(CI en-US 面免疫)。"""


# ---------- 令牌范围签发与查询（单元） ----------

class TestSessionScope:
    """场景:approve_session → 签发 window_session 令牌;查询接缝返回范围。
    断言:session_scope_of 返回值(直出)。
    ISS-0053 A/B:许可键迁移为 (tool, hwnd, norm_key)——重绑不失忆、
    按键类同键批量;此处为迁移钉(语义不变,键法变)。"""

    def test_approve_session_issues_scoped_token(self, approvals, approver):
        approver.decision = "approve_session"
        r = approvals.request_approval(
            "desc", "fp-1", tool="type_text", window_hwnd=1001)
        assert r == "approve_session"
        assert approvals.session_scope_of("type_text", 1001) == \
            "window_session"

    def test_approve_once_has_no_scope(self, approvals, approver):
        approver.decision = "approve"
        approvals.request_approval("desc", "fp-2", tool="type_text",
                                   window_hwnd=1001)
        assert approvals.session_scope_of("type_text", 1001) is None

    def test_scope_expires(self, approvals, approver, clock):
        approver.decision = "approve_session"
        approvals.request_approval("desc", "fp-3", tool="type_text",
                                   window_hwnd=1001)
        clock.advance(9999.0)
        assert approvals.session_scope_of("type_text", 1001) is None


# ---------- 闸四批量命中（单元,enforcement 直通） ----------

class TestBatchAtGate4:
    """场景:会话批量授权后,同窗口同工具后续同类免批;换工具/终端/key 逐批。
    断言:Decision 与审批通道调用计数(直出)。"""

    def _type(self, enforcement, token):
        return enforcement.submit(
            OperationRequest("type_text", {"text": "x"}, token))

    def test_terminal_still_prompts_every_op(self, bindings, approvals, estop,
                                             executor, audit_log, approver,
                                             tmp_path, probe):
        """按批准约束的现实语义:终端类豁免批量——每个终端操作都逐次弹窗。
        (ISS-0053 D:终端自由文本载荷永不批量,此钉维持;许可键已迁 hwnd)"""
        from .conftest import FIXTURE_HWND_B, FIXTURE_RECT_B, make_policy
        from deskpilot.enforcement import Enforcement
        policy = make_policy(audit_dir=str(tmp_path / "audit"))
        enf = Enforcement(policy, bindings, approvals, estop, executor,
                          audit_log)
        probe.processes[FIXTURE_HWND_B] = "cmd.exe"
        rec = bindings.create(FIXTURE_HWND_B, "cmd.exe", FIXTURE_RECT_B)
        approver.decision = "approve_session"
        d1 = enf.submit(OperationRequest("type_text", {"text": "x"}, rec.token))
        assert d1.allowed is True
        assert len(approver.requests) == 1              # 首次弹窗(直出)
        d2 = enf.submit(OperationRequest("type_text", {"text": "y"}, rec.token))
        assert d2.allowed is True
        assert len(approver.requests) == 2              # 终端豁免:再次弹窗(直出)
        assert approvals.session_scope_of("type_text", rec.hwnd) is None


class TestBatchExclusions:
    """场景:批量不适用面——终端类与 key 类永远逐操作。
    断言:通道调用计数递增(直出)。"""

    def test_terminal_never_batch(self, policy, bindings, approvals, estop,
                                  executor, audit_log, approver):
        from deskpilot.enforcement import Enforcement
        from .conftest import FIXTURE_HWND_B, FIXTURE_RECT_B
        from deskpilot.enforcement import Enforcement as E
        enf = E(policy, bindings, approvals, estop, executor, audit_log)
        rec = bindings.create(FIXTURE_HWND_B, "cmd.exe", FIXTURE_RECT_B)
        approver.decision = "approve_session"
        # 终端类绑定:即便裁决为批量,也不应产生批量令牌
        from deskpilot.models import OperationRequest
        enf.submit(OperationRequest("type_text", {"text": "x"}, rec.token))
        assert approvals.session_scope_of("type_text", rec.hwnd) is None


# ---------- 弹窗批量按钮（单元,fake tk） ----------

class TestBatchButton:
    """场景:常规 L3 审批弹窗含「此后同类允许」按钮,点击写 approve_session。
    断言:按钮文本与结果文件内容(直出)。"""

    def test_batch_button_writes_approve_session(self, monkeypatch, tmp_path):
        """ISS-0059 步骤7:本地 W/Btn 替身收编 tests/faketk.install
        (buttons 观测口=text/command,断言零改动)。"""
        import deskpilot.approval_dialog as ad
        from .faketk import install
        rec = install(monkeypatch, ad.tk)
        rp = tmp_path / "r.txt"
        ad.build_window(object(), "常规审批", str(rp), 5)
        btn = [b for b in rec.buttons if "同类" in b.text]
        assert btn, "缺少批量授权按钮"
        btn[0].command()
        assert rp.read_text(encoding="utf-8") == "approve_session"
