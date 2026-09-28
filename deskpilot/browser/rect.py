"""browser_get_rect 工具面(REQ-005 详设 §3.4,MCP L0)。

元素定位 → 虚拟桌面坐标 + 遮挡真相。T2-01 CDP 换算:渲染件物理矩形
原点 + 盒模型中心 × devicePixelRatio,三因子每次现取(ISS-0116:原点
=渲染件子窗口,非顶层窗口);T2-02 超界 fail-closed;T2-03 遮挡自检=
坐标点顶层窗口与目标窗的根归属比对(ISS-0117:同根=未遮挡,异根=
遮挡并报根窗口标题,判定失败不判遮挡),occluded=true 坐标照给;
T2-04 UIA 路由零换算。
"""

from __future__ import annotations

from ..errors import (ELEMENT_NOT_FOUND, INVALID_PARAMS, OUT_OF_BOUNDS,
                      ExecutorError)


def _check_in_desktop(rect) -> None:
    """T2-02:元素中心越出虚拟桌面(渲染窗必在其中)即 fail-closed。"""
    from ..monitors import enum_monitors
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    for m in enum_monitors():
        l, t, r, b = m["rect"]
        if l <= cx < r and t <= cy < b:
            return
    raise ExecutorError(
        OUT_OF_BOUNDS,
        f"元素中心越出渲染窗(虚拟桌面全域不含此点,fail-closed): {rect}")


_GA_ROOT = 2


def _occluder_at(point, target_hwnd):
    """坐标点遮挡判定(ISS-0117):顶层窗口与目标窗同根=未遮挡,
    返回 None;异根=遮挡,返回遮挡根窗口标题(可空串);判定失败
    (取窗口失败/目标句柄未知)返回 None=不判遮挡。"""
    import ctypes
    from ctypes import wintypes
    if not target_hwnd:
        return None
    x, y = point
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
        if not hwnd:
            return None
        root = user32.GetAncestor(hwnd, _GA_ROOT)
        if root and root == user32.GetAncestor(target_hwnd, _GA_ROOT):
            return None                       # 同根:自家渲染件,未遮挡
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(root or hwnd, buf, 256)
        return buf.value or "(无标题窗口)"
    except Exception:
        return None


def _uia_locate(channel, target, name, control_type, index):
    """UIA 路由元素定位:枚举面非空时工具面做命中/歧义/候选判定;
    枚举面为空(懒启用空/通道未供清单)由信道 rect_of 直查定位
    (信道自持树检索与 fail-closed)。"""
    elems = (channel.snapshot(target) or {}).get("elements") or []
    matched = [e for e in elems
               if name and name in str(e.get("name", ""))]
    if control_type:
        typed = [e for e in matched
                 if e.get("control_type") == control_type]
        if matched and typed:
            matched = typed
    if len(matched) > 1 and index is None:
        raise ExecutorError(
            INVALID_PARAMS,
            f"元素命中 {len(matched)} 处,请用 index 指定: "
            f"{[e.get('name') for e in matched]}")
    if matched:
        el = matched[index] if index is not None else matched[0]
        return (list(el["rect"]),
                {"name": el.get("name", ""),
                 "control_type": el.get("control_type", "")})
    if elems:
        from ..executor.textclick import suggest_similar
        near = suggest_similar([{"text": str(e.get("name", ""))}
                                for e in elems], str(name), limit=5)
        hint = f"。相似候选: {' / '.join(near)}" if near else ""
        raise ExecutorError(ELEMENT_NOT_FOUND,
                            f"未找到元素: {name}{hint}")
    rect = channel.rect_of(target, name=name, control_type=control_type,
                           index=index)
    return (list(rect),
            {"name": name or "", "control_type": control_type or ""})


def browser_get_rect(window=None, name=None, control_type=None, index=None,
                     *, manager=None, cdp=None, uia=None, ocr=None,
                     occluder=None) -> dict:
    """元素定位 → {rect, element, occluded, top_element}。

    入参:window=窗口句柄(可空);name=名称子串;control_type=类型过滤;
    index=多命中序号;occluder=遮挡判定接缝(签名 (point, target_hwnd)
    → 遮挡者标题/None,缺省=生产装配);其余同路由器通道接缝。
    返回:坐标包 dict(详设 §3.4 返回表)。
    """
    from .router import select_channel
    chname, channel, target = select_channel(
        window, manager=manager, cdp=cdp, uia=uia, ocr=ocr)
    if chname == "cdp":
        # T2-01:三因子每次现取
        box = channel.element_box(name=name, control_type=control_type,
                                  index=index)
        ox, oy = channel.render_origin()
        d = channel.dpr()
        rect = [round(ox + box["left"] * d), round(oy + box["top"] * d),
                round(ox + box["right"] * d), round(oy + box["bottom"] * d)]
        _check_in_desktop(rect)               # T2-02:超界 fail-closed
        element = {"name": name or "", "control_type": control_type or ""}
    else:
        rect, element = _uia_locate(channel, target, name, control_type,
                                    index)
    # T2-03:遮挡自检(ISS-0117:根窗口归属比对;照给坐标,判断归 AI)
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    if occluder is None:
        occluder = _occluder_at
    target_hwnd = target if isinstance(target, int) \
        else (target or {}).get("hwnd")
    top = occluder((cx, cy), target_hwnd)
    occluded = top is not None
    return {"rect": rect, "element": element,
            "occluded": occluded,
            "top_element": top or ""}
