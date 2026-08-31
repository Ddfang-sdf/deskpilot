"""ISS-0012 E1 实盘缺陷修复测试：tray Win32 调用签名与菜单模型。

层级：单元（直出断言：函数签名/无 OverflowError/菜单模型）。
入口（§6）：tray.menu_items / TrayIcon（消息分发经 DefWindowProcW 高 lParam 直调）。

红→绿：修复前 DefWindowProcW 未声明签名，lParam>2^31 的指针型参数
触发 ctypes OverflowError（窗口过程消息分发被破坏 → 菜单渲染空白）。
"""

from __future__ import annotations

from ctypes import wintypes

from deskpilot import tray as t


class TestWin32Signatures:
    """场景:全部 Win32 调用声明 restype/argtypes(64 位句柄/指针不截断)。
    断言:restype 与关键 argtypes(直出)。"""

    def test_defwindowproc_signature(self):
        assert t._user32.DefWindowProcW.restype == wintypes.LPARAM

    def test_handle_restypes_not_truncated(self):
        """返回句柄的函数不得按默认 int 截断（64 位值安全）。"""
        assert t._user32.CreatePopupMenu.restype in (wintypes.HMENU,
                                                     __import__("ctypes").c_void_p)
        assert t._user32.CreateWindowExW.restype in (wintypes.HWND,
                                                     __import__("ctypes").c_void_p)
        assert t._user32.LoadImageW.restype in (wintypes.HICON,
                                                __import__("ctypes").c_void_p)

    def test_defwindowproc_high_lparam_no_overflow(self):
        """指针型 lParam(>2^31)调用 DefWindowProcW 不得抛 OverflowError。"""
        r = t._user32.DefWindowProcW(None, 0, 0, 2 ** 62)
        assert isinstance(r, int)


class TestTrayMenuModel:
    """场景:菜单模型只含管理入口(运行状态半成品已按用户指令撤除);
    左键与右键均弹菜单(实盘"点击没有反应"教训)。
    断言:menu_items 直出;源码含左键处理(直出)。"""

    def test_menu_only_manage(self):
        assert t.menu_items() == (("manage", "白名单管理…"),)

    def test_left_click_also_pops(self):
        import inspect
        src = inspect.getsource(t.TrayIcon._wnd_proc)
        assert "_WM_LBUTTONUP" in src


class TestMainAssemblyGuard:
    """场景(R3 装配守门):main 装配所需的 os 模块必须已导入——
    实盘"白名单管理没有反应"根因:frozen 分支引 os.environ 而 main 未 import os。
    断言:模块属性存在(直出)。"""

    def test_main_imports_os(self):
        import deskpilot.main as m
        assert hasattr(m, "os")
