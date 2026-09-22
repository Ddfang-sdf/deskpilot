"""按下状态跟踪器与看门狗(REQ-001 鼠标能力补全,详设 §3)。

PressedTracker:button→按下时刻 的单一事实源;五路核销
(mouse_up/hold 完成/看门狗/急停/启动清扫);线程安全(HTTP 多线程处理面)。
不变式:同键至多一条;表外无状态;release_all 后表必为空。
WatchdogThread:周期检测超龄(>30s),强制全抬+审计「悬空按键自愈」
(仅审计不弹窗,D-04);阈值固定常量(安全参数不开放)。
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from ..audit_events import EV_MOUSE_KEY_SELF_HEAL

MOUSE_BUTTONS = ("left", "right", "middle")
MAX_AGE_S = 30.0                     # 看门狗阈值(安全参数,不开放)


class PressedTracker:
    """鼠标按下状态跟踪器(契约见详设 §3.1)。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._pressed: dict[str, float] = {}
        self._lock = threading.Lock()

    def press(self, button: str) -> None:
        """登记按下;同键重复按下幂等(时刻覆盖,不新增条目)。"""
        with self._lock:
            self._pressed[button] = self._clock()

    def release(self, button: str) -> bool:
        """核销;返回是否真有记录(幂等:无记录=False)。"""
        with self._lock:
            return self._pressed.pop(button, None) is not None

    def release_all(self) -> list[str]:
        """强制全抬(estop/看门狗/清扫共用),返回被核销键清单。"""
        with self._lock:
            keys = list(self._pressed)
            self._pressed.clear()
            return keys

    def stale(self, max_age: float = MAX_AGE_S) -> list[str]:
        """返回按下时长超 max_age 的键清单。"""
        now = self._clock()
        with self._lock:
            return [b for b, t in self._pressed.items() if now - t > max_age]

    def snapshot(self) -> list[str]:
        """当前按下键清单(副本)。"""
        with self._lock:
            return list(self._pressed)


class WatchdogThread(threading.Thread):
    """看门狗:周期唤醒,stale 非空则强制全抬+审计「悬空按键自愈」。

    后台线程惰性失效场景正是悬空高发场景(按下后无任何后续调用),
    故必须为独立周期检测(FD-02);线程为 daemon 线程,stop() 置位退出。
    """

    def __init__(self, tracker: PressedTracker,
                 release_fn: Callable[[str], None], audit,
                 interval: float = 1.0):
        super().__init__(daemon=True)
        self._tracker = tracker
        self._release_fn = release_fn           # 物理抬起(button)
        self._audit = audit
        self._interval = interval
        self._stop_event = threading.Event()

    def tick(self) -> None:
        """单轮检测(测试可直接驱动的公开接缝)。"""
        if not self._tracker.stale():
            return
        keys = self._tracker.release_all()
        for b in keys:                          # 逐键独立容错,不阻断余键
            try:
                self._release_fn(b)
            except Exception:                   # noqa: BLE001
                pass
        if self._audit is not None:
            self._audit.record_event(EV_MOUSE_KEY_SELF_HEAL, f"keys={keys}")

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            self.tick()

    def stop(self) -> None:
        self._stop_event.set()
