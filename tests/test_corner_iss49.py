"""ISS-0049 甩角边沿触发单元测试(TC-49-01~05,问题单 §3 方向①)。

层级:单元(FakeClock + 冻结标志直出)。
入口(设计):EstopMonitor.check_corner / on_reset_hotkey(公开入口)。
断言值来源:is_frozen 返回值直出。

语义钉(ISS-0049 方向①):
- 首采定基线:启动时光标已在角落=压角残留,不视为恐慌,不启 hold;
- 边沿触发:仅"区域外→区域内"跳变起计 hold,hold ≥ corner_hold_ms 触发;
- 复位再基线:复位后光标仍压角不自动再冻结,须离开再进入才再武装。

测试设计(五要素):
- TC-49-01 场景=启动压角残留(核心);前提=首采即在角落;
  步骤=check(0,0)→advance 5s→check(0,0)×2;预期=不冻结;断言=is_frozen 直出。
- TC-49-02 场景=正常甩角语义保留;前提=首采在外;
  步骤=check(500,500)→check(0,0)→advance 1.05→check(0,0);预期=冻结。
- TC-49-03 场景=压角残留→离开→再闯入;前提=首采在角落;
  步骤=check(0,0)→check(500,500)→check(0,0)→advance 1.05→check(0,0);
  预期=冻结(离开后再武装)。
- TC-49-04 场景=复位后再基线;前提=已触发且复位,光标仍压角;
  步骤=正常触发→on_reset_hotkey→advance 2s→check(0,0);预期=不冻结;
  再离开再进→预期=可再触发(复位不永久缴械)。
- TC-49-05 场景=路过防抖不变;前提=首采在外;
  步骤=进 0.1s→出→进 0.05s→出;预期=不冻结。
"""

from __future__ import annotations


class TestCornerEdgeTrigger:
    def test_tc49_01_startup_parked_corner_does_not_freeze(self, estop, clock):
        """TC-49-01:启动压角残留——首采即在角落,常驻不触发。"""
        estop.check_corner(0, 0)                     # 首采基线:压角
        clock.advance(5.0)
        estop.check_corner(0, 0)
        clock.advance(5.0)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is False

    def test_tc49_02_normal_slam_still_freezes(self, estop, clock):
        """TC-49-02:首采在外→闯入角落→hold 到期→触发(恐慌语义不损)。"""
        estop.check_corner(500, 500)                 # 首采基线:在外
        estop.check_corner(0, 0)                     # 边沿:外→内,起计 hold
        clock.advance(1.05)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is True

    def test_tc49_03_parked_then_leave_then_slam_freezes(self, estop, clock):
        """TC-49-03:压角基线→离开→再闯入→触发(再武装有效)。"""
        estop.check_corner(0, 0)                     # 基线:压角
        clock.advance(2.0)                           # 压角多久都不触发
        estop.check_corner(0, 0)
        assert estop.is_frozen() is False
        estop.check_corner(500, 500)                 # 离开
        estop.check_corner(0, 0)                     # 边沿再进入
        clock.advance(1.05)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is True

    def test_tc49_04_reset_rebaselines_corner(self, estop, clock):
        """TC-49-04:复位后光标仍压角→不再冻结;离开再进→可再触发。"""
        estop.check_corner(500, 500)
        estop.check_corner(0, 0)
        clock.advance(1.05)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is True
        estop.on_reset_hotkey()                      # 复位,光标仍压角
        assert estop.is_frozen() is False
        clock.advance(2.0)
        estop.check_corner(0, 0)                     # 压角残留不复活恐慌
        clock.advance(2.0)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is False
        estop.check_corner(500, 500)                 # 离开→再武装
        estop.check_corner(0, 0)
        clock.advance(1.05)
        estop.check_corner(0, 0)
        assert estop.is_frozen() is True

    def test_tc49_05_pass_by_still_safe(self, estop, clock):
        """TC-49-05:边沿语义下路过防抖不变(短驻留不触发)。"""
        estop.check_corner(500, 500)                 # 基线:在外
        estop.check_corner(0, 0)
        clock.advance(0.1)
        estop.check_corner(500, 500)
        clock.advance(0.3)
        estop.check_corner(0, 0)
        clock.advance(0.05)
        estop.check_corner(500, 500)
        assert estop.is_frozen() is False
