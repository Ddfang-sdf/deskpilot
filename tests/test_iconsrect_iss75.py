"""ISS-0075 桌面图标 graphic_rect 坐标系契约测试(ir01~ir03,单据 §3 方向①)。

层级:单元(ListViewIconProvider 的 _Win32Seam/user32 接缝以同形态替身注入;
被测方法本体不打桩)。入口(设计):ListViewIconProvider.graphic_rects
公开入口。断言出处:返回值直出/异常码直出。

红态预期(现状):graphic_rects 直接透传 LVM_GETITEMRECT 的 client 坐标,
从不调 client_origin——ir01 原点非 (0,0) 时未平移立红;ir02 原点读取
失败不报错立红;ir03 红期即绿(原点 (0,0) 零漂移钉)。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import pytest

from deskpilot.errors import INTERNAL_ERROR, ExecutorError
from deskpilot.executor.desktop_icons import ListViewIconProvider, _RECT


class _FakeOS:
    """跨进程内存接缝替身:read_mem 回填固定 RECT;client_origin 可控。"""

    def __init__(self, rect: _RECT, origin):
        self._rect = rect
        self._origin = origin
        self.origin_calls = 0

    def open_process(self, pid): return 1
    def virtual_alloc(self, hproc, size): return 4096
    def write_mem(self, hproc, addr, buf, size): return True
    def send_itemrect(self, hwnd, index, addr): return 1

    def read_mem(self, hproc, addr, buf, size):
        ctypes.memmove(buf, ctypes.byref(self._rect), size)
        return True

    def virtual_free(self, hproc, addr): pass
    def close_handle(self, h): pass

    def client_origin(self, hwnd):
        """ISS-0075 接缝(单据 §3 ①):客户区原点的屏幕坐标。"""
        self.origin_calls += 1
        return self._origin


class _FakeU32:
    """user32 接缝替身:pid 回填(graphic_rects 只取 pid,不走 SendMessage)。"""

    def GetWindowThreadProcessId(self, hwnd, pid_ref):
        pid_ref._obj.value = 1
        return 1


def _rect(l, t, r, b) -> _RECT:
    rc = _RECT()
    rc.left, rc.top, rc.right, rc.bottom = l, t, r, b
    return rc


class TestGraphicRectVirtualCoords:
    """方向①:client→屏幕坐标的显式平移收口在 graphic_rects。"""

    def test_ir01_nonzero_origin_translated(self):
        """ir01(核心):替身 ListView 原点 (100,50) → 返回 rect 已平移
        到屏幕坐标(巧合变契约)。红态(现状):从不读原点,原样透传。"""
        os_seam = _FakeOS(_rect(10, 20, 110, 60), (100, 50))
        prov = ListViewIconProvider(os_seam=os_seam, u32_seam=_FakeU32())
        out = prov.graphic_rects(999, [0])
        assert os_seam.origin_calls == 1        # 原点被读取(替身记录直出)
        assert out == [[110, 70, 210, 110]]     # 平移后坐标(返回值直出)

    def test_ir02_origin_failure_explicit_error(self):
        """ir02(fail-closed 约束):原点读取失败(句柄失效) → 显式报错,
        不得回退未转换值。红态(现状):无此检查,静默透传。"""
        os_seam = _FakeOS(_rect(10, 20, 110, 60), None)
        prov = ListViewIconProvider(os_seam=os_seam, u32_seam=_FakeU32())
        with pytest.raises(ExecutorError) as ei:
            prov.graphic_rects(999, [0])
        assert ei.value.code == INTERNAL_ERROR  # 异常码直出

    def test_ir03_zero_origin_unchanged(self):
        """ir03(钉):原点 (0,0) → 数值不变(本机巧合形态零漂移回归)。
        红期即绿。"""
        os_seam = _FakeOS(_rect(10, 20, 110, 60), (0, 0))
        prov = ListViewIconProvider(os_seam=os_seam, u32_seam=_FakeU32())
        out = prov.graphic_rects(999, [0])
        assert out == [[10, 20, 110, 60]]       # 零平移(返回值直出)
