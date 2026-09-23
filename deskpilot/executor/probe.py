"""窗口系统探测（ctypes 直读 Win32，无第三方依赖）。

实现 binding.WindowProbe 接口，另提供窗口枚举/前置能力。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SW_RESTORE = 9
_SW_SHOWMAXIMIZED = 3                     # ISS-0041:最大化窗激活且保持最大化
_SW_SHOW = 5                              # ISS-0041:普通窗按当前尺寸显示(不恢复)


def set_window_rect(hwnd: int, left: int, top: int,
                    width: int, height: int) -> bool:
    """ISS-0101 §4.2：窗口几何摆放 OS 接缝（模块级 user32 单层,
    测试 monkeypatch 替身,同 iss41 先例）。

    动作序：ShowWindow(SW_RESTORE) 恒定先发（最大化/最小化先还原再摆
    防打回;与 DesktopProbe.activate 的 IsZoomed→SW_SHOWMAXIMIZED 命令
    选择语义相反,不复用）→ MoveWindow（坐标=虚拟桌面物理像素,
    PMv2 零换算）。返回 MoveWindow 成功布尔（False=死窗,调用方判
    WINDOW_GONE）。
    """
    user32.ShowWindow(hwnd, _SW_RESTORE)         # 恒定先发
    return bool(user32.MoveWindow(hwnd, left, top, width, height, True))


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


def enum_windows(include_hidden: bool = False) -> list[dict]:
    """枚举顶层窗口：hwnd / title / process / rect / visible。

    include_hidden=True 时含隐藏(托盘/最小化)窗口——审批反查实拍专用
    (ISS-0020 补:西柚隐藏托盘被误拍全屏的根因)。
    """
    results: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        if not include_hidden and not user32.IsWindowVisible(hwnd):
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
                     hwnd: int | None = None,
                     include_hidden: bool = False) -> list[dict]:
        """按标题（子串，忽略大小写）/进程名/句柄过滤窗口；
        include_hidden=True 含隐藏窗（ISS-0020 审批反查用）。"""
        out = []
        for w in enum_windows(include_hidden=include_hidden):
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
        """把窗口提到前台（按窗口状态选显示命令 + 前台附加线程技巧 + 短退避重试）。

        ISS-0017 A：前台锁瞬时失败按 ≤3 次短退避重试；最终失败返回 False
        （fail-closed，调用方必须检查，绝不成功假象）。
        ISS-0041：ShowWindow 命令按执行时刻窗口状态选择——IsIconic（最小化,
        含最小化的最大化窗优先）→ SW_RESTORE（恢复原意图）;IsZoomed（最大化）
        → SW_SHOWMAXIMIZED（激活且保持最大化,修复最大化被打回原始尺寸的缺陷）;
        其余 → SW_SHOW（按当前尺寸显示,不做任何恢复）。状态判定在重试循环外
        取一次,各轮重试命令不漂移。
        """
        if not user32.IsWindow(hwnd):
            return False
        if user32.IsIconic(hwnd):
            cmd = _SW_RESTORE
        elif user32.IsZoomed(hwnd):
            cmd = _SW_SHOWMAXIMIZED
        else:
            cmd = _SW_SHOW
        for attempt in range(3):
            user32.ShowWindow(hwnd, cmd)
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
            if user32.GetForegroundWindow() == hwnd:
                return True
            if attempt < 2:
                time.sleep(0.08)
        return False
