"""ISS-0029 错误码登记册删除守卫(TC-RM-01,问题单 §4/§5 v0.2 评审通过)。

层级:单元(hasattr 负向断言,形态直出)。
入口(设计):deskpilot.errors 模块(登记册应已不存在)。
"""

from __future__ import annotations


class TestRegistryRemoved:
    def test_rm01_all_reason_codes_gone(self):
        """TC-RM-01:ALL_REASON_CODES 死代码登记册不存在(防复活守卫)。"""
        from deskpilot import errors
        assert not hasattr(errors, "ALL_REASON_CODES")
