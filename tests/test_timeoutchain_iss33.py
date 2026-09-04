"""ISS-0033【修改引入】超时链一致性测试(TC-TC-01~05,问题单 §3 v0.1)。

层级:单元(纯函数/字段直出)+源码形态静态断言。
入口(设计):httpd.client_timeout(policy) / httpd.resolve_budget / remote_call 调用点。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestClientTimeout:
    """TC-TC-01/02:客户端超时由策略推导,调用点接线,无魔法 90。"""

    def test_tc01_derived_from_policy(self, policy):
        from deskpilot.httpd import client_timeout
        assert client_timeout(policy) == policy.approval_ttl + 15

    def test_tc02_wired_no_magic(self):
        mcp_src = (ROOT / "deskpilot" / "mcp_server.py").read_text(
            encoding="utf-8")
        httpd_src = (ROOT / "deskpilot" / "httpd.py").read_text(
            encoding="utf-8")
        assert "client_timeout" in mcp_src          # 调用点接线(形态直出)
        assert "timeout: float = 90" not in httpd_src   # 魔法默认已删(形态直出)


class TestResolveBudgetL1:
    """TC-TC-03/04:L1 升级档与 L0 回归(返回值直出)。"""

    def test_tc03_l1_escalation_budget(self, policy):
        from deskpilot.httpd import resolve_budget
        assert resolve_budget("L1", policy) == policy.approval_ttl + 5

    def test_tc04_l0_unchanged(self, policy):
        from deskpilot.httpd import resolve_budget
        assert resolve_budget("L0", policy) == 5.0


class TestAssemblyLabel:
    """TC-TC-05:预算测试降级 assembly,标签按三层定义判定(形态直出)。"""

    def test_tc05_assembly_label(self):
        src = (ROOT / "tests" / "test_budget_iss24.py").read_text(
            encoding="utf-8")
        assert "@pytest.mark.integration" not in src
        assert "Assembly" in src
        assert "替身" in src or "fake" in src.lower()  # docstring 列明替身清单
