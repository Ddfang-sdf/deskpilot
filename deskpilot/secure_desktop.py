"""安全桌面显式检测（ISS-0087 ①，详细设计衔接 §11 急停族）。

「人类不可视 = AI 不可动」（sdfang 2026-09-15 裁定）：锁屏=人不在场，
UAC 同意框=人类裁决面，两者都运行在**安全桌面**上。本模块提供显式
Win32 检测通道（替代「光标读数退化为角点」的副作用达成——该副作用
触发的甩角冻结按裁定保持原状，本通道是叠加的显式机制）。

检测原理：OpenInputDesktop 取当前输入桌面，GetUserObjectInformationW
读其名；非 "Default"（Winlogon/ScreenSaver 等）即安全桌面。
fail-closed：打开失败/读名失败/任何异常一律按安全桌面激活处理
（宁可误禁，不可漏放——单据 §4 尾待确认点，2026-09-17 采纳备案）。

SecureDesktopGuard 持有状态做边沿审计：进入记「安全桌面激活」、退出记
「安全桌面退出」、检测失效记「安全桌面检测失效」——与「急停触发:
鼠标甩角」在审计面可区分（整改③）。拒绝留痕在 tools.call_tool 闸门侧
（「安全桌面拒绝」）。
"""

from __future__ import annotations

from .audit_events import (
    EV_SECURE_DESKTOP_ACTIVATED,
    EV_SECURE_DESKTOP_CHECK_FAILED,
    EV_SECURE_DESKTOP_EXITED)

import ctypes
from ctypes import wintypes
from typing import Callable

_DESKTOP_READOBJECTS = 0x0001
_UOI_NAME = 2


def is_secure_desktop_active() -> bool:
    """当前输入桌面是否为安全桌面（锁屏/UAC）。

    True=安全桌面激活（AI 应全禁）。任何 API 失败按激活处理
    （fail-closed）。
    """
    user32 = ctypes.windll.user32
    hdesk = user32.OpenInputDesktop(0, False, _DESKTOP_READOBJECTS)
    if not hdesk:
        return True                     # 打不开输入桌面:fail-closed
    try:
        needed = wintypes.DWORD(0)
        # 先取所需缓冲长度（返回假但 needed 被置位）
        user32.GetUserObjectInformationW(hdesk, _UOI_NAME, None, 0,
                                         ctypes.byref(needed))
        if needed.value == 0:
            return True                 # 读不出名字:fail-closed
        buf = ctypes.create_unicode_buffer(needed.value // 2 + 1)
        if not user32.GetUserObjectInformationW(
                hdesk, _UOI_NAME, buf, needed.value, ctypes.byref(needed)):
            return True
        return buf.value != "Default"
    finally:
        user32.CloseDesktop(hdesk)


class SecureDesktopGuard:
    """安全桌面态守卫：显式检测 + 边沿审计 + fail-closed。

    check() 返回 True=安全桌面激活（一切 AI 操作应拒，含 L0 感知）。
    detector 可注入（测试接缝，单元层）；audit 可选（边沿留痕）。
    """

    def __init__(self, detector: Callable[[], bool] | None = None,
                 audit=None) -> None:
        self._detector = detector or is_secure_desktop_active
        self._audit = audit
        self._active: bool | None = None    # None=首检未定基线
        self._detect_failed = False

    def check(self) -> bool:
        """当前是否安全桌面激活（True=全禁一切 AI 操作，含 L0 感知）。

        detector 异常 → fail-closed 按激活处理，审计「安全桌面检测失效」
        （节流：失效边沿只记一条）；状态边沿记「安全桌面激活/退出」
        （首检即激活记激活；首检正常不记——基线免噪音）。
        """
        try:
            active = bool(self._detector())
            failed = False
        except Exception as e:                              # noqa: BLE001
            active, failed = True, True
            if not self._detect_failed and self._audit is not None:
                self._audit.record_event(
                    EV_SECURE_DESKTOP_CHECK_FAILED, f"{e!r}（fail-closed 按激活处理）")
        self._detect_failed = failed
        if active != self._active:
            if self._audit is not None and (self._active is not None or active):
                self._audit.record_event(
                    EV_SECURE_DESKTOP_ACTIVATED if active else EV_SECURE_DESKTOP_EXITED, "")
            self._active = active
        return active
