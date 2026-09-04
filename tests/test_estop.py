"""急停（EstopMonitor）单元测试。

覆盖：TC-N-EST-01、TC-S-EST-01/02、复位通道（热键 Ctrl+Shift+F11 / CLI）。
断言值来源：is_frozen 返回值与审计 JSONL 持久化数据。
"""

from __future__ import annotations

from .conftest import read_audit


class TestTriggerAndReset:
    def test_hotkey_trigger_freezes(self, estop, audit_log, tmp_path):
        """TC-S-EST-01：热键触发即冻结，审计记录急停事件。"""
        assert estop.is_frozen() is False
        estop.on_trigger_hotkey()
        assert estop.is_frozen() is True
        events = [r for r in read_audit(str(tmp_path / "audit")) if r.get("event") == "急停触发"]
        assert len(events) == 1

    def test_reset_hotkey_unfreezes(self, estop, audit_log, tmp_path):
        """TC-N-EST-01：复位热键解除冻结，触发与复位两条事件齐全。"""
        estop.on_trigger_hotkey()
        estop.on_reset_hotkey()
        assert estop.is_frozen() is False
        events = [r["event"] for r in read_audit(str(tmp_path / "audit")) if r.get("event")]
        assert "急停触发" in events
        assert "急停复位" in events

    def test_cli_reset_unfreezes(self, estop):
        """本地 CLI 复位命令同样解除冻结。"""
        estop.on_trigger_hotkey()
        estop.cli_reset()
        assert estop.is_frozen() is False

    def test_reset_when_not_frozen_is_noop(self, estop, audit_log, tmp_path):
        """未冻结时复位不产生状态变化。"""
        estop.on_reset_hotkey()
        assert estop.is_frozen() is False


class TestCornerDebounce:
    def test_pass_by_does_not_trigger(self, estop, clock):
        """TC-S-EST-02：路过左上角不停留（< 1000ms）不触发。"""
        estop.check_corner(0, 0)                     # 进入角落
        clock.advance(0.1)                           # 停留 100ms
        estop.check_corner(500, 500)                 # 离开
        clock.advance(0.3)
        estop.check_corner(0, 0)                     # 再次进入但随后离开
        clock.advance(0.05)
        estop.check_corner(500, 500)
        assert estop.is_frozen() is False

    def test_sustained_corner_triggers(self, estop, clock):
        """停留 ≥ corner_hold_ms（默认 1000ms）触发。"""
        estop.check_corner(0, 0)
        clock.advance(1.05)                          # 停留 1050ms
        estop.check_corner(0, 0)
        assert estop.is_frozen() is True

    def test_corner_boundary_exactly_threshold(self, estop, clock):
        """恰好达到停留阈值即触发。"""
        estop.check_corner(0, 0)
        clock.advance(1.0)                           # 恰好 1000ms
        estop.check_corner(0, 0)
        assert estop.is_frozen() is True

    def test_leave_corner_resets_timer(self, estop, clock):
        """离开后重新进入，停留时长重新计。"""
        estop.check_corner(0, 0)
        clock.advance(0.5)
        estop.check_corner(500, 500)                 # 离开，计时清零
        clock.advance(0.5)
        estop.check_corner(0, 0)                     # 重新进入
        clock.advance(0.5)                           # 累计 500ms < 1000ms
        estop.check_corner(0, 0)
        assert estop.is_frozen() is False
