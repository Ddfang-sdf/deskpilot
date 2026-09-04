"""ISS-0028 甩角驻留阈值 200→1000ms 测试(TC-COR-01~04,问题单 §4/§5 v0.2)。

层级:单元(策略加载直出 + FakeClock 冻结标志直出)。
入口(设计):load_policy / make_policy 默认 / EstopMonitor.check_corner。
"""

from __future__ import annotations

from pathlib import Path

from deskpilot.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]


class TestCornerThreshold1000:
    def test_cor01_repo_policy_loads_1000(self):
        """TC-COR-01:生产 policy.yml 阈值=1000。"""
        policy = load_policy(str(ROOT / "policy.yml"))
        assert policy.corner_hold_ms == 1000

    def test_cor02_999ms_does_not_freeze(self, estop, clock):
        """TC-COR-02:驻留 999ms 不触发。"""
        estop.check_corner(0, 0)
        clock.advance(0.999)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is False

    def test_cor03_1001ms_freezes(self, estop, clock):
        """TC-COR-03:驻留 1001ms 触发(语义锁定用例,阈值变更后防回退)。"""
        estop.check_corner(0, 0)
        clock.advance(1.001)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is True

    def test_cor04_fixture_default_synced(self, policy):
        """TC-COR-04:测试装配默认阈值与生产策略单源一致。"""
        assert policy.corner_hold_ms == 1000
