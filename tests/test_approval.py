"""审批管理（ApprovalManager / compute_fingerprint）单元测试。

覆盖：TC-N-APR-01/02、TC-S-TOK-01/02/04、TC-E-ST-04、DDS §7.12（M1 恒拒绝）。
断言值来源：compute_fingerprint / request_approval / verify_and_consume / count 的返回值。
"""

from __future__ import annotations

from deskpilot.approval import DenyAllChannel, compute_fingerprint


class TestFingerprint:
    """compute_fingerprint 为设计文档定义的模块级公开纯函数（DDS §7.6）。"""

    def test_deterministic(self):
        fp1 = compute_fingerprint("key", {"key": "alt+f4", "token": "t1"})
        fp2 = compute_fingerprint("key", {"key": "alt+f4", "token": "t1"})
        assert fp1 == fp2
        assert len(fp1) == 32                       # 摘要十六进制前 32 位

    def test_param_order_invariant(self):
        """规范化消除参数顺序差异。"""
        fp1 = compute_fingerprint("key", {"key": "alt+f4", "token": "t1"})
        fp2 = compute_fingerprint("key", {"token": "t1", "key": "alt+f4"})
        assert fp1 == fp2

    def test_whitespace_normalized(self):
        """规范化消除首尾空白差异。"""
        fp1 = compute_fingerprint("type_text", {"text": "abc"})
        fp2 = compute_fingerprint("type_text", {"text": "  abc  "})
        assert fp1 == fp2

    def test_one_char_difference_changes_fingerprint(self):
        """TC-S-TOK-03 基础：一个字符不同即指纹不同。"""
        fp1 = compute_fingerprint("key", {"key": "delete"})
        fp2 = compute_fingerprint("key", {"key": "delete " + "x"})
        assert fp1 != fp2


class TestRequestAndConsume:
    def test_approve_issues_token_and_consumed_once(self, approvals, approver):
        """TC-N-APR-01（manager 层）：裁决批准 → 服务内部签发；按指纹查证通过一次；
        再次查证拒绝（一次性）。"""
        approver.decision = "approve"
        fp = compute_fingerprint("key", {"key": "alt+f4", "token": "t1"})
        decision = approvals.request_approval("按键 alt+f4 作用于测试窗口", fp)
        assert decision == "approve"

        assert approvals.verify_and_consume(fp) is True     # 第一次通过并消费
        assert approvals.verify_and_consume(fp) is False    # TC-S-TOK-01：复用拒绝
        assert approvals.count() == 0

    def test_request_carries_description_and_fingerprint(self, approvals, approver):
        """TC-N-APR-02：送达审批通道的内容含操作描述与指纹。"""
        approver.decision = "deny"
        fp = compute_fingerprint("key", {"key": "delete"})
        approvals.request_approval("按键 delete 作用于记事本", fp)
        assert len(approver.requests) == 1
        assert approver.requests[0]["description"] == "按键 delete 作用于记事本"
        assert approver.requests[0]["fingerprint"] == fp

    def test_deny_or_timeout_issues_nothing(self, approvals, approver):
        """TC-E-ST-04：拒绝/超时 → 无授权签发，裁决原样返回。"""
        fp = compute_fingerprint("key", {"key": "delete"})
        approver.decision = "deny"
        assert approvals.request_approval("desc", fp) == "deny"
        approver.decision = "timeout"
        assert approvals.request_approval("desc", fp) == "timeout"
        assert approvals.count() == 0

    def test_expired_token_rejected(self, approvals, approver, clock):
        """TC-S-TOK-02：超过 approval_ttl 后查证拒绝（内部兜底路径）。"""
        approver.decision = "approve"
        fp = compute_fingerprint("key", {"key": "delete"})
        assert approvals.request_approval("desc", fp) == "approve"
        clock.advance(61)                                   # ttl = 60s
        assert approvals.verify_and_consume(fp) is False
        assert approvals.count() == 0

    def test_failed_verify_does_not_consume(self, approvals, approver):
        """TC-S-TOK-04：指纹不匹配查证失败不消耗授权，匹配指纹查证仍通过。"""
        approver.decision = "approve"
        fp = compute_fingerprint("key", {"key": "delete"})
        approvals.request_approval("desc", fp)

        wrong_fp = compute_fingerprint("key", {"key": "shift+delete"})
        assert approvals.verify_and_consume(wrong_fp) is False   # 变形失败
        assert approvals.verify_and_consume(fp) is True          # 授权仍在，可消费
        assert approvals.count() == 0

    def test_fingerprint_mismatch_not_consumed_repeatedly(self, approvals, approver):
        """多次变形尝试均不消耗授权。"""
        approver.decision = "approve"
        fp = compute_fingerprint("key", {"key": "delete"})
        approvals.request_approval("desc", fp)
        for i in range(3):
            assert approvals.verify_and_consume(f"wrong-{i}") is False
        assert approvals.verify_and_consume(fp) is True


class TestM1DenyAll:
    def test_deny_all_channel_always_denies(self, clock):
        """DDS §7.11 / §7.12：M1 生产通道恒拒绝。"""
        from deskpilot.approval import ApprovalManager
        mgr = ApprovalManager(DenyAllChannel(), 60.0, clock)
        fp = compute_fingerprint("key", {"key": "alt+f4"})
        assert mgr.request_approval("desc", fp) == "deny"
        assert mgr.verify_and_consume(fp) is False
