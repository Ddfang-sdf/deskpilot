"""系统托盘图标（ISS-0012 §6 E1）：ctypes Shell_NotifyIconW，零第三方依赖。

menu_items：菜单模型纯函数（动作ID, 显示名），单元可测。
TrayIcon：隐藏消息窗口 + 托盘图标 + 右键菜单；on_manage 打开白名单管理窗口。
同时解决 daemon 运行不可见的潜伏问题（托盘即在跑）。
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

_WM_APP = 0x8000
_WM_TRAY = _WM_APP + 1
_WM_RBUTTONUP = 0x0205
_WM_COMMAND = 0x0111
_WM_DESTROY = 0x0002
_NIM_ADD = 0x0
_NIM_DELETE = 0x2
_NIF_MESSAGE = 0x1
_NIF_ICON = 0x2
_NIF_TIP = 0x4
_IDI_APPLICATION = 32512
_IMAGE_ICON = 1
_LR_SHARED = 0x8000
_LR_DEFAULTSIZE = 0x40
_TPM_RETURNCMD = 0x100
_MF_STRING = 0x0

_user32 = ctypes.windll.user32
_shell32 = ctypes.windll.shell32
_kernel32 = ctypes.windll.kernel32


def menu_items() -> tuple[tuple[str, str], ...]:
    """ISS-0012 §6 E1：托盘菜单模型纯函数——(动作ID, 显示名)。"""
    return (("manage", "白名单管理…"),
            ("status", "运行状态…"))


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON)]


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


_WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)


class TrayIcon:
    """ISS-0012 §6 E1：托盘图标（后台线程跑消息循环）。"""

    def __init__(self, on_manage: Callable[[], None],
                 on_status: Callable[[], None] | None = None,
                 tooltip: str = "DeskPilot 运行中"):
        self._on_manage = on_manage
        self._on_status = on_status or (
            lambda: _user32.MessageBoxW(None, tooltip, "DeskPilot", 0x40))
        self._tooltip = tooltip
        self._thread: threading.Thread | None = None
        self._hwnd = None
        self._actions = {0x100 + i: action
                         for i, (action, _label) in enumerate(menu_items())}

    def start(self) -> None:
        """启动托盘（幂等）。"""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="deskpilot-tray")
        self._thread.start()

    def stop(self) -> None:
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, _WM_DESTROY, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    # ---- 内部 ----

    def _loop(self) -> None:
        class_name = "DeskPilotTrayWnd"
        wndproc = _WNDPROC(self._wnd_proc)       # 必须持有引用防 GC
        wc = _WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(wndproc, ctypes.c_void_p).value
        wc.lpszClassName = class_name
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        if not _user32.RegisterClassW(ctypes.byref(wc)):
            err = _kernel32.GetLastError()
            if err != 1410:                      # 1410=类已存在（同进程重复注册）
                return
        self._hwnd = _user32.CreateWindowExW(
            0, class_name, class_name, 0, 0, 0, 0, 0,
            None, None, wc.hInstance, None)
        if not self._hwnd:
            return

        icon = _user32.LoadImageW(None, _IDI_APPLICATION, _IMAGE_ICON,
                                  0, 0, _LR_SHARED | _LR_DEFAULTSIZE)
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        nid.uCallbackMessage = _WM_TRAY
        nid.hIcon = icon
        nid.szTip = self._tooltip[:127]
        _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid))

        msg = _MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        nid2 = _NOTIFYICONDATAW()
        nid2.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid2.hWnd = self._hwnd
        nid2.uID = 1
        _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(nid2))
        self._hwnd = None

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == _WM_TRAY and lparam == _WM_RBUTTONUP:
            self._popup(hwnd)
            return 0
        if msg == _WM_COMMAND:
            action = self._actions.get(wparam & 0xFFFF)
            if action == "manage":
                try:
                    self._on_manage()
                except Exception:
                    pass
            elif action == "status":
                try:
                    self._on_status()
                except Exception:
                    pass
            return 0
        if msg == _WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup(self, hwnd) -> None:
        menu = _user32.CreatePopupMenu()
        for cmd_id, action in sorted(self._actions.items()):
            label = dict(menu_items())[action]
            _user32.AppendMenuW(menu, _MF_STRING, cmd_id, label)
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        _user32.SetForegroundWindow(hwnd)        # 菜单失焦自收的既有怪癖处理
        cmd = _user32.TrackPopupMenu(menu, _TPM_RETURNCMD, pt.x, pt.y,
                                     0, hwnd, None)
        _user32.PostMessageW(hwnd, 0, 0, 0)
        _user32.DestroyMenu(menu)
        if cmd:
            _user32.PostMessageW(hwnd, _WM_COMMAND, cmd, 0)
