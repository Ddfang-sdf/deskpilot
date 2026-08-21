"""冻结人类通知（ISS-0004）单元测试。

覆盖：TC-N-EST-07～12（测试设计说明书 §3.8）。
入口：FreezeNotifier（on_state_change / check_reset_request）、
freeze_dialog 纯逻辑函数（read_state / write_reset_request / should_remind /
next_action / slide_in_xs / slide_out_xs）、EstopMonitor 公开复位入口。
断言值来源：文件邮箱持久化内容 / 桩调用记录 / 审计 JSONL / 纯函数返回值。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from deskpilot.estop import EstopMonitor
from deskpilot.freeze_dialog import (next_action, should_remind, slide_in_xs,
                                     slide_out_xs)
from deskpilot.freeze_notify import LOCK_FILE, REQ_FILE, STATE_FILE, FreezeNotifier

from .conftest import FakeClock, read_audit


@pytest.fixture
def spawn_log():
    return []


@pytest.fixture
def notifier(tmp_path, spawn_log):
    return FreezeNotifier(str(tmp_path), clock=time.monotonic,
                          spawn=spawn_log.append)


@pytest.fixture
def estop_n(policy, clock, audit_log, notifier):
    """挂接冻结通知钩子的 estop（按 main 装配形态）。"""
    return EstopMonitor(policy.corner_hold_ms, clock, audit_log,
                        on_state_change=notifier.on_state_change)


def _read_state(tmp_path) -> dict:
    return json.loads((tmp_path / STATE_FILE).read_text(encoding="utf-8"))


class TestStateFile:
    """TC-N-EST-07 冻结状态文件翻转。"""

    def test_state_file_flips_on_trigger_and_reset(self, tmp_path, notifier,
                                                   estop_n):
        estop_n.on_trigger_hotkey()
        s1 = _read_state(tmp_path)
        assert s1["frozen"] is True
        assert s1["seq"] == 1
        assert "热键" in s1["source"]

        estop_n.on_reset_hotkey()
        s2 = _read_state(tmp_path)
        assert s2["frozen"] is False
        assert s2["seq"] == 2

    def test_state_file_atomic_valid_json(self, tmp_path, estop_n):
        """原子写：每次状态变化后文件均为完整合法 JSON。"""
        estop_n.on_trigger_hotkey()
        raw1 = (tmp_path / STATE_FILE).read_text(encoding="utf-8")
        estop_n.cli_reset()
        raw2 = (tmp_path / STATE_FILE).read_text(encoding="utf-8")
        assert json.loads(raw1)["frozen"] is True
        assert json.loads(raw2)["frozen"] is False


class TestResetRequestGuard:
    """TC-N-EST-08 解冻请求消费守卫。"""

    def _write_req(self, tmp_path, seq):
        (tmp_path / REQ_FILE).write_text(json.dumps({"seq": seq}),
                                         encoding="utf-8")

    def test_matching_seq_consumed(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # seq=1, frozen
        self._write_req(tmp_path, 1)
        notifier.check_reset_request(estop_n)
        assert estop_n.is_frozen() is False
        assert not (tmp_path / REQ_FILE).exists()
        records = read_audit(str(tmp_path / "audit"))
        resets = [r for r in records
                  if r.get("event") == "急停复位" and "冻结提示弹窗" in r["detail"]]
        assert len(resets) == 1

    def test_stale_seq_discarded(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # seq=1
        estop_n.cli_reset()                        # seq=2, 未冻结
        estop_n.on_trigger_hotkey()                # seq=3, 新一轮冻结
        self._write_req(tmp_path, 1)               # 陈旧请求（对着 seq=1 的冻结）
        notifier.check_reset_request(estop_n)
        assert estop_n.is_frozen() is True         # 不误解冻新冻结
        assert not (tmp_path / REQ_FILE).exists()

    def test_request_when_unfrozen_discarded(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # seq=1
        estop_n.cli_reset()                        # seq=2, 未冻结
        self._write_req(tmp_path, 2)
        notifier.check_reset_request(estop_n)
        assert estop_n.is_frozen() is False
        assert not (tmp_path / REQ_FILE).exists()
        records = read_audit(str(tmp_path / "audit"))
        resets = [r for r in records
                  if r.get("event") == "急停复位" and "冻结提示弹窗" in r["detail"]]
        assert resets == []


class TestDialogSingleton:
    """TC-N-EST-09 弹窗单例守卫。"""

    def test_no_respawn_while_lock_alive(self, tmp_path, notifier, estop_n,
                                         spawn_log):
        estop_n.on_trigger_hotkey()
        assert len(spawn_log) == 1                 # 首次置位拉起弹窗
        (tmp_path / LOCK_FILE).write_text("pid=1", encoding="utf-8")  # 活心跳
        estop_n.cli_reset()
        estop_n.on_trigger_hotkey()
        assert len(spawn_log) == 1                 # 心跳存活 → 不重复拉起

    def test_respawn_when_lock_stale(self, tmp_path, notifier, estop_n,
                                     spawn_log):
        estop_n.on_trigger_hotkey()
        assert len(spawn_log) == 1
        lock = tmp_path / LOCK_FILE
        lock.write_text("pid=1", encoding="utf-8")
        old = time.time() - 4                      # 心跳龄 4s > LOCK_MAX_AGE
        os.utime(lock, (old, old))
        estop_n.cli_reset()
        estop_n.on_trigger_hotkey()
        assert len(spawn_log) == 2                 # 心跳陈旧 → 允许再拉起


class TestRemindLogic:
    """TC-N-EST-10 稍后提醒重弹判定。"""

    def test_remind_only_after_interval_and_still_frozen(self):
        t0 = 1000.0
        assert should_remind(t0, t0 + 179, True, 180.0) is False
        assert should_remind(t0, t0 + 180, True, 180.0) is True
        assert should_remind(t0, t0 + 180, False, 180.0) is False


class TestDismissLogic:
    """TC-N-EST-11 复位后弹窗收尾判定（热键解冻自动消窗的逻辑层）。"""

    def test_shown_state_unfrozen_slides_out_and_exits(self):
        assert next_action("SHOWN", False) == "slide_out_exit"

    def test_shown_state_frozen_waits(self):
        assert next_action("SHOWN", True) == "wait"


class TestSlideSymmetry:
    """TC-N-EST-12 滑入滑出动画对称。"""

    def test_slide_out_is_reverse_of_slide_in(self):
        in_xs = slide_in_xs(2560, 440)
        out_xs = slide_out_xs(2560, 440)
        assert out_xs == list(reversed(in_xs))
        assert len(in_xs) * 16 == 240              # 16ms × 15 帧 = 240ms

    def test_slide_in_starts_offscreen_ends_at_margin(self):
        in_xs = slide_in_xs(2560, 440)
        assert in_xs[0] >= 2560                    # 起点：屏外右缘
        assert in_xs[-1] == 2560 - 440 - 16        # 终点：右下角右边距 16
