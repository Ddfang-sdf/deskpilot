"""守卫族(ISS-0055 S1):边界/遮挡/前置/窗口几何守卫——自 Executor 外迁。

搬函数留委托(strangler fig):函数体与迁移前逐字一致(self→ex 首参);
跨族调用一律经 ex 委托门面回 core(本模块不 import 任何兄弟族模块,
依赖图无环)。`_occlusion_user32` 接缝留在 core,函数体内延迟
`from . import core` 读属性——test_elevation_iss17/test_occlusion_iss42
对 core 的赋值在调用前发生,语义等价(ISS-0055 §6 风险 1 处置)。
"""

from __future__ import annotations

from ..errors import (INTERNAL_ERROR, INVALID_PARAMS, OUT_OF_BOUNDS,
                      WINDOW_GONE, WINDOW_OCCLUDED, ExecutorError)
from .probe import set_window_rect as _os_set_window_rect


def _binding_rect(ex, hwnd) -> tuple | None:
    """绑定窗口矩形（无绑定或探测失败回退 None → 证据图转全桌面）。"""
    if hwnd is None:
        return None
    try:
        return ex._probe.rect_of(hwnd)
    except Exception:
        return None


def _activate_if_needed(ex, hwnd: int) -> bool:
    """仅当目标窗口不在前台时才前置——避免重激活导致弹出的菜单/画廊被销毁。
    返回是否已处前台（fail-closed：写路径调用方必须检查）。"""
    if hwnd is None:
        return True
    if ex._probe.is_foreground(hwnd):
        return True
    return bool(ex._probe.activate(hwnd))


def _set_window_rect(ex, params: dict, hwnd: int) -> dict:
    """窗口几何摆放（ISS-0101 §4.2，物理层原语）。

    rect=[l,t,r,b] 四点式（虚拟桌面坐标,PMv2 全链物理像素零换算——
    与 screenshot scope=region 的 [x,y,w,h] 不同,实现内自解为
    MoveWindow 的 (l,t,r-l,b-t)）；几何非法（r<=l 或 b<=t）fail-closed
    拒（user32 零调用）；动作序=SW_RESTORE 恒定先发再 MoveWindow
    （probe 接缝）；MoveWindow 返 False→WINDOW_GONE；
    返回新 rect（probe.rect_of 直出,GetWindowRect 同口径）。
    不做吸附/屏幕归属/避让判定（§4.4,落点合理性 AI screenshot 自核）。
    """
    l, t, r, b = (int(v) for v in params["rect"])
    if r <= l or b <= t:
        raise ExecutorError(
            INVALID_PARAMS,
            f"窗口矩形非法（须 r>l 且 b>t）: {params['rect']}")
    if not _os_set_window_rect(hwnd, l, t, r - l, b - t):
        raise ExecutorError(WINDOW_GONE,
                            "MoveWindow 失败（目标窗口已消失）")
    return {"status": "ok", "rect": list(ex._probe.rect_of(hwnd))}


def _check_point(ex, hwnd: int, x: int, y: int) -> None:
    rect = ex._probe.rect_of(hwnd)     # 执行时刻矩形
    if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
        raise ExecutorError(OUT_OF_BOUNDS, "落点在绑定窗口矩形外")


def _enum_monitors(ex) -> list[dict]:
    """ISS-0047:显示器枚举接缝(测试替身入口;生产=monitors.enum_monitors)。"""
    from ..monitors import enum_monitors
    return enum_monitors()


def _check_drag_end(ex, x: int, y: int) -> None:
    """ISS-0047:drag 终点校验=虚拟桌面全域。

    移动窗口类拖拽的终点合法地在绑定窗当前矩形外(跨屏移动必越窗),
    两类拖拽语义分离:起点仍限绑定窗(防误射),终点放宽到虚拟桌面。
    逐屏矩形判定(非并集包围盒——错位排列的虚空死角仍拒);
    枚举失败/为空 fail-closed,绝不静默放行。
    """
    try:
        rects = [m["rect"] for m in ex._enum_monitors()]
    except Exception as e:
        raise ExecutorError(INTERNAL_ERROR,
                            f"显示器枚举失败,终点校验无法执行: {e}") from e
    if not rects:
        raise ExecutorError(INTERNAL_ERROR, "显示器枚举为空,终点校验无法执行")
    if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in rects):
        raise ExecutorError(
            OUT_OF_BOUNDS,
            f"终点 ({x},{y}) 不在任何显示器矩形内: {rects}")


def _check_occlusion(ex, hwnd: int, x: int, y: int) -> None:
    """ISS-0017 C：遮挡判定（激活后调用）——落点处顶层窗口非目标/
    非其子窗口则拒绝（fail-closed,绝不盲打）。
    ISS-0042：错误附遮挡者进程名与标题（AI 一轮可诊断,免自行侦查）。"""
    from . import core
    u32 = core._occlusion_user32
    if u32 is None:
        import ctypes
        u32 = ctypes.windll.user32
    from ctypes import wintypes
    pt_hwnd = u32.WindowFromPoint(wintypes.POINT(x, y))
    if pt_hwnd != hwnd and not u32.IsChild(hwnd, pt_hwnd):
        proc = ""
        title = ""
        try:
            proc = ex._probe.process_of(pt_hwnd) or ""
        except Exception:                           # noqa: BLE001
            pass
        try:
            n = u32.GetWindowTextLengthW(pt_hwnd)
            if n:
                import ctypes
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(pt_hwnd, buf, n + 1)
                title = buf.value
        except Exception:                           # noqa: BLE001
            pass
        who = proc or "未知进程"
        if title:
            who = f"{who}({title})"
        raise ExecutorError(
            WINDOW_OCCLUDED,
            f"落点被 {who} 遮挡,请先前置目标窗口或请人类处理遮挡程序")


def _resolve_window(ex, window) -> int:
    if isinstance(window, int):
        hwnd = window
    else:
        found = ex._probe.find_windows(title=str(window))
        if not found:
            raise ExecutorError(WINDOW_GONE, f"找不到窗口: {window}")
        hwnd = found[0]["hwnd"]
    if not ex._probe.hwnd_alive(hwnd):
        raise ExecutorError(WINDOW_GONE, "目标窗口已消失")
    return hwnd
