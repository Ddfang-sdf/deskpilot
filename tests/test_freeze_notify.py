"""冻结人类通知（ISS-0004 / ISS-0005 / ISS-0006）单元测试。

覆盖：TC-N-EST-07、10～15（测试设计说明书 §3.8）、
TC-ISS6-04～07（ISS-0006 §6：解冻请求协议 / spawn 不猜测 / seq 共享 / 全局同步）。
入口：FreezeNotifier（on_state_change / check_reset_request /
sync_local_with_shared_state）、freeze_dialog 纯逻辑函数（read_state /
should_remind / next_action / slide_*）、样式常量表 STYLE 与色键 CHROMA、
EstopMonitor 公开复位入口。
断言值来源：文件邮箱持久化内容 / 桩调用记录 / 审计 JSONL / 纯函数返回值。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from deskpilot.estop import EstopMonitor
from deskpilot.freeze_dialog import (CHROMA, STYLE, next_action, should_remind,
                                     slide_in_frames, slide_in_xs,
                                     slide_out_frames, slide_out_xs)
from deskpilot.freeze_notify import STATE_FILE, FreezeNotifier

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


class TestResetRequestProtocol:
    """TC-ISS6-04 解冻请求协议（方案 B：seq 命名 + 先验后删）。"""

    def _write_req(self, tmp_path, seq):
        (tmp_path / f"estop-reset-{seq}.req").write_text(
            json.dumps({"seq": seq}), encoding="utf-8")

    def _req_files(self, tmp_path):
        return sorted(tmp_path.glob("estop-reset-*.req"))

    def test_matching_frozen_owner_consumes(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # 共享 seq=1, frozen
        self._write_req(tmp_path, 1)
        notifier.check_reset_request(estop_n)
        assert estop_n.is_frozen() is False
        assert self._req_files(tmp_path) == []
        records = read_audit(str(tmp_path / "audit"))
        resets = [r for r in records
                  if r.get("event") == "急停复位" and "冻结提示弹窗" in r["detail"]]
        assert len(resets) == 1

    def test_stale_seq_deleted(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # seq=1
        estop_n.cli_reset()                        # seq=2
        estop_n.on_trigger_hotkey()                # seq=3, 新一轮冻结
        self._write_req(tmp_path, 1)               # 陈旧请求（对着 seq=1 的冻结）
        notifier.check_reset_request(estop_n)
        assert estop_n.is_frozen() is True         # 不误解冻新冻结
        assert self._req_files(tmp_path) == []     # 陈旧请求清理

    def test_req_for_unfrozen_shared_deleted(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # seq=1
        estop_n.cli_reset()                        # seq=2, 未冻结
        self._write_req(tmp_path, 2)
        notifier.check_reset_request(estop_n)
        assert estop_n.is_frozen() is False
        assert self._req_files(tmp_path) == []     # 已解冻,请求作废删除
        records = read_audit(str(tmp_path / "audit"))
        resets = [r for r in records
                  if r.get("event") == "急停复位" and "冻结提示弹窗" in r["detail"]]
        assert resets == []

    def test_non_frozen_owner_leaves_req_for_frozen_one(self, tmp_path, notifier,
                                                        estop_n, policy, clock,
                                                        audit_log):
        """先验后删（R1 修复）：共享冻结中，未冻结进程的 tick 不吞请求。"""
        estop_n.on_trigger_hotkey()                # 共享 seq=1 frozen
        self._write_req(tmp_path, 1)
        other = EstopMonitor(policy.corner_hold_ms, clock, audit_log)  # 未冻结进程
        notifier.check_reset_request(other)
        assert other.is_frozen() is False
        assert len(self._req_files(tmp_path)) == 1          # 请求保留给冻结 owner
        notifier.check_reset_request(estop_n)               # 冻结 owner 消费
        assert estop_n.is_frozen() is False
        assert self._req_files(tmp_path) == []

    def test_future_seq_kept(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # seq=1 frozen
        self._write_req(tmp_path, 5)               # N > 共享 seq（异常时序）
        notifier.check_reset_request(estop_n)
        assert len(self._req_files(tmp_path)) == 1
        assert estop_n.is_frozen() is True


class TestSpawnOnEveryFrozenEdge:
    """TC-ISS6-05 owner 不做存活猜测（方案 A：子进程互斥兜底）。"""

    def test_each_frozen_edge_spawns(self, tmp_path, notifier, estop_n,
                                     spawn_log):
        estop_n.on_trigger_hotkey()
        estop_n.cli_reset()
        estop_n.on_trigger_hotkey()
        estop_n.cli_reset()
        estop_n.on_trigger_hotkey()
        assert len(spawn_log) == 3


class TestSharedSeq:
    """TC-ISS6-06 seq 共享单调（方案 C）。"""

    def test_seq_monotonic_across_notifier_instances(self, tmp_path, spawn_log):
        n1 = FreezeNotifier(str(tmp_path), clock=time.monotonic,
                            spawn=spawn_log.append)
        n1.on_state_change(True, "a")
        assert _read_state(tmp_path)["seq"] == 1
        n2 = FreezeNotifier(str(tmp_path), clock=time.monotonic,
                            spawn=spawn_log.append)
        n2.on_state_change(False, "b")
        assert _read_state(tmp_path)["seq"] == 2
        n1.on_state_change(True, "c")
        assert _read_state(tmp_path)["seq"] == 3


class TestSharedSyncReset:
    """TC-ISS6-07 解冻全局同步（方案 E）。"""

    def _write_shared(self, tmp_path, frozen, seq, source):
        (tmp_path / STATE_FILE).write_text(json.dumps(
            {"frozen": frozen, "seq": seq, "source": source, "ts": "t"}),
            encoding="utf-8")

    def test_sync_resets_frozen_local(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # 本地 frozen, 共享 seq=1 frozen
        self._write_shared(tmp_path, False, 2, "另一进程")  # 另一进程已全局解冻
        assert notifier.sync_local_with_shared_state(estop_n) is True
        assert estop_n.is_frozen() is False
        records = read_audit(str(tmp_path / "audit"))
        syncs = [r for r in records
                 if r.get("event") == "急停复位" and "共享同步" in r["detail"]]
        assert len(syncs) == 1

    def test_sync_noop_when_shared_frozen(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()
        assert notifier.sync_local_with_shared_state(estop_n) is False
        assert estop_n.is_frozen() is True

    def test_sync_noop_when_local_unfrozen(self, tmp_path, notifier, estop_n):
        self._write_shared(tmp_path, False, 1, "x")
        assert notifier.sync_local_with_shared_state(estop_n) is False


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


class TestSlideFadeFrames:
    """TC-N-EST-13 滑入滑出透明度复合动画（ISS-0005）。"""

    def test_alpha_ramps_0_to_1_monotonic(self):
        frames = slide_in_frames(2560, 440)
        assert frames[0][1] == 0.0                 # 首帧全透明
        assert frames[-1][1] == 1.0                # 末帧不透明
        alphas = [a for _, a in frames]
        assert all(0.0 <= a <= 1.0 for a in alphas)
        assert all(b >= a for a, b in zip(alphas, alphas[1:]))  # 单调不减

    def test_slide_out_frames_is_reverse(self):
        assert slide_out_frames(2560, 440) == list(
            reversed(slide_in_frames(2560, 440)))

    def test_duration_unchanged_240ms(self):
        assert len(slide_in_frames(2560, 440)) * 16 == 240

    def test_x_regression_matches_legacy_trajectory(self):
        """位移回归：动画升级不改变轨迹与落位。"""
        assert [x for x, _ in slide_in_frames(2560, 440)] == slide_in_xs(2560, 440)
        assert [x for x, _ in slide_out_frames(2560, 440)] == slide_out_xs(2560, 440)


class TestStyleConstants:
    """TC-N-EST-14 样式常量完整性与可区分性（ISS-0005）。"""

    _HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

    def test_required_keys_complete(self):
        for k in ("card_bg", "card_border", "accent", "title_fg",
                  "source_fg", "body_fg", "hint_fg"):
            assert k in STYLE
        for k in ("bg", "fg", "hover_bg", "pressed_bg",
                  "disabled_bg", "disabled_fg"):
            assert k in STYLE["primary"]
        for k in ("bg", "fg", "border", "hover_bg"):
            assert k in STYLE["secondary"]

    def test_button_states_distinguishable(self):
        p = STYLE["primary"]
        assert len({p["bg"], p["hover_bg"], p["pressed_bg"],
                    p["disabled_bg"]}) == 4        # 主按钮四态可区分
        s = STYLE["secondary"]
        assert s["bg"] != s["hover_bg"]            # 次按钮悬停有反馈

    def test_all_colors_valid_hex(self):
        groups = [STYLE, STYLE["primary"], STYLE["secondary"]]
        colors = [v for g in groups for v in g.values() if isinstance(v, str)]
        assert colors and all(self._HEX.match(c) for c in colors)


class TestChromaKeyCollision:
    """TC-N-EST-15 色键透明冲突守卫（ISS-0005）。"""

    def test_chroma_not_used_by_any_style_color(self):
        colors = {v for v in STYLE.values() if isinstance(v, str)}
        colors |= set(STYLE["primary"].values()) | set(STYLE["secondary"].values())
        assert CHROMA not in colors
