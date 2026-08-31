"""显示器枚举与几何判定（ISS-0007 §6，方案 A）。

enum_monitors：枚举显示器（rect/work_area/is_primary，mss 优先、Win32 兜底，含负坐标）。
screen_of_point / screen_of_rect：点/矩形归属屏判定（矩形取交集面积最大者）。
"""

from __future__ import annotations


def enum_monitors() -> list[dict]:
    """ISS-0007 §6：枚举显示器。

    返回 [{"rect": (l,t,r,b), "work_area": (l,t,r,b), "is_primary": bool}]。
    优先 mss（自带每屏几何）；失败回退 Win32 EnumDisplayMonitors。
    """
    try:
        import mss
        with mss.MSS() as sct:
            mons = sct.monitors[1:]           # [0] 为虚拟桌面聚合,跳过
            if mons:
                return [_norm(m, i) for i, m in enumerate(mons)]
    except Exception:
        pass
    return _enum_win32()


def _norm(m: dict, idx: int) -> dict:
    l, t = int(m["left"]), int(m["top"])
    r = l + int(m["width"])
    b = t + int(m["height"])
    return {"rect": (l, t, r, b),
            "work_area": (l, t, r, b - _taskbar_h(m)),
            "is_primary": l == 0 and t == 0}


def _taskbar_h(m: dict) -> int:
    return 0 if not (m["left"] == 0 and m["top"] == 0) else 48


def _enum_win32() -> list[dict]:
    """Win32 EnumDisplayMonitors 兜底枚举（含负坐标）。"""
    import ctypes
    from ctypes import wintypes

    out: list[dict] = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT), ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR,
                            wintypes.HDC, wintypes.LPRECT, wintypes.LPARAM)

    def _cb(hmon, hdc, lprect, lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            m, w = info.rcMonitor, info.rcWork
            out.append({
                "rect": (m.left, m.top, m.right, m.bottom),
                "work_area": (w.left, w.top, w.right, w.bottom),
                "is_primary": bool(info.dwFlags & 1),
            })
        return True

    user32.EnumDisplayMonitors(None, None, cb(_cb), 0)
    return out


def screen_of_point(monitors: list[dict], x: int, y: int) -> dict | None:
    """ISS-0007 §6：返回含点 (x,y) 的显示器 dict；无命中 None。"""
    for m in monitors:
        l, t, r, b = m["rect"]
        if l <= x < r and t <= y < b:
            return m
    return None


def screen_of_rect(monitors: list[dict], rect: tuple) -> dict | None:
    """ISS-0007 §6：返回与矩形交集面积最大的显示器 dict；无交集 None。"""
    l1, t1, r1, b1 = rect
    best = None
    best_area = 0
    for m in monitors:
        l2, t2, r2, b2 = m["rect"]
        iw = min(r1, r2) - max(l1, l2)
        ih = min(b1, b2) - max(t1, t2)
        if iw > 0 and ih > 0:
            area = iw * ih
            if area > best_area:
                best_area = area
                best = m
    return best
