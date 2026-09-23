"""ISS-0056/0057/0061 cleancode 三单钉测试(五要素见各单据)。

层级:单元(形态扫描=源码文本直读;纯函数/枚举接缝替身,允许打桩)。
入口(设计):core.py 源码形态 / monitors.enum_monitors /
monitors.TASKBAR_RESERVE 单源常量 / freeze_notify 源码形态。
断言出处:源码文本计数直读;enum_monitors 返回 dict 直出;常量值直出。

红态说明(ISS-0056 顺序认账):_failsafe_guard 收敛实现先于本钉落地
(会话内顺序偏差)——行为红绿证据由 t52b(test_startcall_iss52,红→绿)
与 test_reliability_iss9/test_mouse_req01 既有 FAILSAFE 钉承担;
本文件 f56 为防漂移形态钉(到即绿,价值=日后有人再复制模板立红)。
f57a/f57b/f61 为正常先红后绿(写本钉时未实现)。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

import deskpilot.monitors as mon

ROOT = Path(__file__).resolve().parent.parent


class TestFailSafeSinglePoint:
    """ISS-0056:FAILSAFE 收敛模板单点化,复制面清零。"""

    def test_f56_template_single_sourced(self):
        """f56(形态):executor 包(core.py+input.py)内
        「except pyautogui.FailSafeException」仅余 2 处(=_failsafe_guard
        单点 + 启动清扫容错变体——语义不同保留);_failsafe_guard 调用点
        ≥7。红态(未收敛):7+ 处复制。
        ISS-0055 S5 登记(单据 v0.3,裁决 v0.2①):写入族外迁 input.py,
        扫描面由 core.py 单文件扩为包级两文件合计,五要素不动。"""
        base = ROOT / "deskpilot" / "executor"
        src = (base / "core.py").read_text(encoding="utf-8") + \
            (base / "input.py").read_text(encoding="utf-8")
        assert src.count("except pyautogui.FailSafeException") == 2  # 直读计数
        assert src.count("_failsafe_guard(") >= 7      # 单点调用面(直读)


class TestTaskbarReserveSingleSource:
    """ISS-0057:避让边距单源 + work_area/is_primary 真查不再猜。"""

    def test_f57a_margin_constant_single_sourced(self):
        """f57a(形态):三处避让边距同源 monitors.TASKBAR_RESERVE;
        toast_placement 默认 taskbar 即该常量。"""
        from deskpilot.approval_dialog import _TASKBAR
        from deskpilot.freeze_dialog import MARGIN_BOTTOM
        assert _TASKBAR is mon.TASKBAR_RESERVE          # 同一对象(直出)
        assert MARGIN_BOTTOM is mon.TASKBAR_RESERVE
        sig = inspect.signature(mon.toast_placement)
        assert sig.parameters["taskbar"].default is mon.TASKBAR_RESERVE

    def test_f57b_work_area_real_query(self, monkeypatch):
        """f57b(单元):mss 路枚举的 work_area/is_primary 由 Win32
        GetMonitorInfoW 真查回填(_win32_info 缝替身),副屏不再吃 0 猜值,
        主屏不再吃「原点即主屏」猜。红态(现状):_taskbar_h 纯猜——
        副屏 work_area=rect(零避让)、主屏=原点判定。"""
        class _Sct:
            monitors = [None,
                        {"left": 0, "top": 0, "width": 1920, "height": 1080},
                        {"left": -1920, "top": 0, "width": 1920,
                         "height": 1080}]  # 副屏在左(主屏非原点)

            def __enter__(self): return self
            def __exit__(self, *a): return False

        class _FakeMss:
            MSS = lambda self: _Sct()

        monkeypatch.setitem(sys.modules, "mss", _FakeMss())
        monkeypatch.setattr(mon, "_win32_info", lambda: {
            (0, 0, 1920, 1080): ((0, 0, 1920, 1032), False),   # 原点屏非主屏
            (-1920, 0, 0, 1080): ((-1920, 0, 0, 1080), True),  # 主屏在左副屏位
        }, raising=False)
        out = mon.enum_monitors()
        by_rect = {m["rect"]: m for m in out}       # ISS-0096 排序后按 rect 查
        assert by_rect[(0, 0, 1920, 1080)]["work_area"] == (0, 0, 1920, 1032)
        assert by_rect[(0, 0, 1920, 1080)]["is_primary"] is False
        assert by_rect[(-1920, 0, 0, 1080)]["work_area"] == (-1920, 0, 0, 1080)
        assert by_rect[(-1920, 0, 0, 1080)]["is_primary"] is True
        # ISS-0096 顺带钉:主屏(is_primary)排第一
        assert out[0]["is_primary"] is True


class TestHeartbeatLockDeadCodeGone:
    """ISS-0061:心跳锁孤儿死代码清零。"""

    def test_f61_lock_constants_removed(self):
        """f61(形态):freeze_notify 无 LOCK_FILE/LOCK_MAX_AGE;
        详细设计说明书不再把 estop-dialog.lock 列为现存机制。
        红态(现状):两常量零消费点在架。"""
        src = (ROOT / "deskpilot" / "freeze_notify.py").read_text(
            encoding="utf-8")
        assert "LOCK_FILE" not in src and "LOCK_MAX_AGE" not in src
        design = (ROOT / "docs" / "详细设计说明书.md").read_text(
            encoding="utf-8")
        assert "弹窗进程写入 pid 并每秒刷新心跳" not in design   # 机制描述翻页
