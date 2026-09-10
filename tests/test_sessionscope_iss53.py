"""ISS-0053 批量授权生效面修复测试(TC-53-01~04,问题单 §4)。

层级:单元(Enforcement 真闸链 + FakeApprover 通道计数)。
入口(设计):Enforcement.submit(OperationRequest)(公开入口)。
断言值来源:approver.requests 计数 / Decision.allowed / session_scope_of
返回值——直出。

语义钉(sdfang 2026-09-10 批准 A~D):
- A 许可键=hwnd+tool:重绑(新 binding_token 同 hwnd)不失忆;
- B key 类同键批量:esc 免批不捎带 delete;终端类维持逐操作
  (既有钉 test_terminal_* 在 test_batch_iss19 就地迁移=TC-53-05);
- C 弹窗提示随语义更新(迁移 TC-43-01,见 test_sessionscope_iss43);
- D 令牌仅内存,执行前复核照常;过期/once 钉迁移=TC-53-07/08
  (test_batch_iss19 TestSessionScope)。

测试设计(五要素):
- TC-53-01 场景=同键同窗批量命中;前提=记事本绑定+裁决 approve_session;
  步骤=esc→esc;预期=通道计数恒 1 双放行;断言=计数/allowed 直出。
- TC-53-02 场景=同窗异键不串;前提=esc 已批量;步骤=delete;
  预期=再弹(计数 2);断言=计数直出+session_scope_of(delete)=None(机制核对)。
- TC-53-03 场景=同键异窗不串;前提=窗 A 已批量;步骤=窗 B esc;
  预期=再弹(计数 2);断言=计数直出+session_scope_of(窗 B)=None。
- TC-53-04 场景=重绑不失效(ISS-0043 B① 核心);前提=窗 A 批量后同 hwnd
  再 attach(新令牌);步骤=esc;预期=不再弹(计数恒 1);断言=计数直出。
"""

from __future__ import annotations

from deskpilot.models import OperationRequest

from .conftest import FIXTURE_HWND, FIXTURE_HWND_B, FIXTURE_RECT, FIXTURE_RECT_B


def _esc(enforcement, token):
    return enforcement.submit(OperationRequest("key", {"key": "escape"}, token))


class TestKeyBatchByHwnd:
    def test_tc53_01_same_key_same_window_no_reprompt(
            self, enforcement, bindings, approver, approvals):
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        approver.decision = "approve_session"
        assert _esc(enforcement, rec.token).allowed is True
        assert len(approver.requests) == 1              # 首弹(直出)
        assert _esc(enforcement, rec.token).allowed is True
        assert len(approver.requests) == 1              # 同键同窗:不再弹
        assert approvals.session_scope_of(
            "key", FIXTURE_HWND, "escape") == "window_session"

    def test_tc53_02_different_key_still_prompts(
            self, enforcement, bindings, approver, approvals):
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        approver.decision = "approve_session"
        assert _esc(enforcement, rec.token).allowed is True
        assert len(approver.requests) == 1
        # 机制核对(delete 自身获批前):esc 的批量令牌不捎带 delete(直出)
        assert approvals.session_scope_of(
            "key", FIXTURE_HWND, "delete") is None
        d = enforcement.submit(
            OperationRequest("key", {"key": "delete"}, rec.token))
        assert d.allowed is True
        assert len(approver.requests) == 2              # 异键:再弹(直出)

    def test_tc53_03_different_window_still_prompts(
            self, enforcement, bindings, approver, approvals):
        rec_a = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        rec_b = bindings.create(FIXTURE_HWND_B, "notepad.exe", FIXTURE_RECT_B)
        approver.decision = "approve_session"
        assert _esc(enforcement, rec_a.token).allowed is True
        assert len(approver.requests) == 1
        # 机制核对(窗 B 获批前):窗 A 的批量令牌不跨窗(直出)
        assert approvals.session_scope_of(
            "key", FIXTURE_HWND_B, "escape") is None
        assert _esc(enforcement, rec_b.token).allowed is True
        assert len(approver.requests) == 2              # 异窗:再弹(直出)

    def test_tc53_04_reattach_same_hwnd_keeps_scope(
            self, enforcement, bindings, approver):
        rec1 = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        approver.decision = "approve_session"
        assert _esc(enforcement, rec1.token).allowed is True
        assert len(approver.requests) == 1
        # 重绑:同 hwnd 新令牌(模拟 TTL 到期/重新 attach)
        rec2 = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        assert rec2.token != rec1.token                 # 前提:确实是新令牌
        assert _esc(enforcement, rec2.token).allowed is True
        assert len(approver.requests) == 1              # 重绑不失忆(直出)
