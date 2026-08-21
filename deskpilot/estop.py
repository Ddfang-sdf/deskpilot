"""急停程序（详细设计 §11）。

独立线程监听热键（Ctrl+Shift+F12）与鼠标甩角；复位仅本地人类通道：
复位热键 Ctrl+Shift+F11 或本地 CLI 命令。复位组合键永不进入任何按键许可表。
持有 shell 的 AI 属威胁模型之外（防 AI 犯错，不防 AI 作恶）。
"""

from __future__ import annotations

from typing import Callable

from .audit import AuditLogger

TRIGGER_HOTKEY = "ctrl+shift+f12"   # 急停热键（规范化形）
RESET_HOTKEY = "ctrl+shift+f11"     # 复位热键（规范化形）
CORNER_X = 0                        # 甩角触发区域左上角
CORNER_Y = 0


class EstopMonitor:
    """冻结标志管理：置位（热键/甩角）与复位（本地人类通道）。"""

    def __init__(self, corner_hold_ms: int, clock: Callable[[], float],
                 audit_log: AuditLogger | None = None,
                 on_state_change: Callable[[bool, str], None] | None = None):
        self._corner_hold_ms = corner_hold_ms
        self._clock = clock
        self._audit = audit_log
        self._on_state_change = on_state_change   # 冻结通知钩子（ISS-0004）
        self._frozen = False
        self._corner_since: float | None = None

    def is_frozen(self) -> bool:
        """冻结查询（强制层与执行层写路径双检查）。"""
        return self._frozen

    def on_trigger_hotkey(self) -> None:
        """急停热键回调（Ctrl+Shift+F12）：置位冻结标志并记审计。"""
        self._trigger("热键 Ctrl+Shift+F12")

    def on_reset_hotkey(self) -> None:
        """复位热键回调（Ctrl+Shift+F11）：复位并记审计。"""
        self._reset("复位热键 Ctrl+Shift+F11")

    def cli_reset(self) -> None:
        """本地 CLI 复位命令入口：复位并记审计。"""
        self._reset("本地 CLI 复位命令")

    def dialog_reset(self) -> None:
        """冻结提示弹窗"立即解冻"入口：复位并记审计（ISS-0004）。"""
        self._reset("冻结提示弹窗")

    def check_corner(self, x: int, y: int) -> None:
        """鼠标位置轮询回调：甩角防抖判定。

        光标进入左上角触发区域且持续停留 ≥ corner_hold_ms 才触发；
        路过不停留不触发（详细设计 §11.6）。
        """
        if x <= CORNER_X and y <= CORNER_Y:
            if self._corner_since is None:
                self._corner_since = self._clock()
            elif self._clock() - self._corner_since >= self._corner_hold_ms / 1000:
                self._trigger("鼠标甩角")
        else:
            self._corner_since = None

    def _trigger(self, source: str) -> None:
        if self._frozen:
            return
        self._frozen = True
        if self._audit is not None:
            self._audit.record_event("急停触发", source)
        if self._on_state_change is not None:
            self._on_state_change(True, source)

    def _reset(self, source: str) -> None:
        if not self._frozen:
            # 复位 no-op 也记审计（ISS-0002）：热键按没按、送到了谁必须可查
            if self._audit is not None:
                self._audit.record_event("复位请求-未冻结", source)
            return
        self._frozen = False
        self._corner_since = None
        if self._audit is not None:
            self._audit.record_event("急停复位", source)
        if self._on_state_change is not None:
            self._on_state_change(False, source)
