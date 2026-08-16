"""窗口系统探测（ctypes 直读 Win32，无第三方依赖）。

实现 binding.WindowProbe 接口，另提供窗口枚举/前置能力。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SW_RESTORE = 9


def _process_name_of(pid: int) -> str:
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def enum_windows() -> list[dict]:
    """枚举可见顶层窗口：hwnd / title / process / rect / visible。"""
    results: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if not title.strip():
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        results.append({
            "hwnd": hwnd,
            "title": title,
            "process": _process_name_of(pid.value),
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
            "visible": True,
        })
        return True

    user32.EnumWindows(_cb, 0)
    return results


class DesktopProbe:
    """WindowProbe 的真实实现。"""

    def hwnd_alive(self, hwnd: int) -> bool:
        return bool(user32.IsWindow(hwnd))

    def process_of(self, hwnd: int) -> str:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return _process_name_of(pid.value)

    def rect_of(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (0, 0, 0, 0)
        return (rect.left, rect.top, rect.right, rect.bottom)

    def find_windows(self, title: str | None = None, process: str | None = None,
                     hwnd: int | None = None) -> list[dict]:
        """按标题（子串，忽略大小写）/进程名/句柄过滤窗口。"""
        out = []
        for w in enum_windows():
            if hwnd is not None and w["hwnd"] != hwnd:
                continue
            if title is not None and title.lower() not in w["title"].lower():
                continue
            if process is not None and w["process"] != process.strip().lower():
                continue
            out.append(w)
        return out

    def is_foreground(self, hwnd: int) -> bool:
        return user32.GetForegroundWindow() == hwnd

    def activate(self, hwnd: int) -> bool:
        """把窗口提到前台（恢复最小化 + 前台附加线程技巧）。"""
        if not user32.IsWindow(hwnd):
            return False
        user32.ShowWindow(hwnd, _SW_RESTORE)
        foreground = user32.GetForegroundWindow()
        cur_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(foreground, None)
        if fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, True)
        try:
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        finally:
            if fg_thread != cur_thread:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
        return user32.GetForegroundWindow() == hwnd
