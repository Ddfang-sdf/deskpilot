"""绑定管理程序（详细设计 §6）。

绑定记录仅存内存；校验是强制层闸一的实际执行者（INV-1）。
OS 探测（句柄存活、进程名、矩形）通过注入的 probe 完成，便于测试。
"""

from __future__ import annotations

import secrets
from typing import Callable, Protocol

from .models import BindingRecord


class WindowProbe(Protocol):
    """窗口系统探测接口（执行层只读面提供）。"""

    def hwnd_alive(self, hwnd: int) -> bool: ...
    def process_of(self, hwnd: int) -> str: ...
    def rect_of(self, hwnd: int) -> tuple[int, int, int, int]: ...


class BindingManager:
    """绑定记录的创建、校验、回收、解绑。"""

    def __init__(self, probe: WindowProbe, ttl_seconds: float, clock: Callable[[], float]):
        self._probe = probe
        self._ttl = ttl_seconds
        self._clock = clock
        self._records: dict[str, BindingRecord] = {}

    def create(self, hwnd: int, process_name: str,
               window_rect: tuple[int, int, int, int],
               window_title: str = "") -> BindingRecord:
        """创建绑定记录并返回（令牌为密码学强度随机串）。"""
        now = self._clock()
        record = BindingRecord(
            token=secrets.token_urlsafe(24),
            hwnd=hwnd,
            process_name=process_name.strip().lower(),   # 进程名归一（§6.6）
            window_rect=tuple(window_rect),
            bound_at=now,
            last_active_at=now,
            window_title=window_title,
        )
        self._records[record.token] = record
        return record

    def validate(self, token: str | None) -> BindingRecord | None:
        """四校验：令牌存在 ∧ 未超时 ∧ 句柄存活 ∧ 进程一致。

        通过则刷新 last_active_at 并返回记录；任一不过则移除绑定并返回 None。
        """
        if not token:
            return None
        record = self._records.get(token)
        if record is None:
            return None
        if self._is_stale(record):
            del self._records[token]
            return None
        record.last_active_at = self._clock()
        return record

    def detach(self, token: str) -> bool:
        """主动解绑，原令牌立即失效。返回是否解绑了存在的绑定。"""
        return self._records.pop(token, None) is not None

    def reap(self) -> int:
        """回收超时/失效绑定，返回回收数量。"""
        stale = [t for t, r in self._records.items() if self._is_stale(r)]
        for t in stale:
            del self._records[t]
        return len(stale)

    def count(self) -> int:
        """当前绑定数量（测试观测口）。"""
        return len(self._records)

    def _is_stale(self, record: BindingRecord) -> bool:
        if self._clock() - record.last_active_at > self._ttl:
            return True
        if not self._probe.hwnd_alive(record.hwnd):
            return True
        current = (self._probe.process_of(record.hwnd) or "").strip().lower()
        return current != record.process_name
