"""browser_get_rect 工具面(REQ-005 详设 §3.4,MCP L0)。

元素定位 → 虚拟桌面坐标 + 遮挡真相。T2-01 CDP 换算:渲染窗物理矩形
原点 + 盒模型中心 × devicePixelRatio,三因子每次现取;T2-02 超界
fail-closed;T2-03 遮挡自检=坐标点顶层元素判定,occluded=true 坐标
照给并附 top_element;T2-04 UIA 路由零换算。
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


def _topmost_at(point) -> str:
    """生产顶层判定:坐标点顶层窗口标题(失败置空=不判遮挡)。"""
    import ctypes
    x, y = point
    try:
        hwnd = ctypes.windll.user32.WindowFromPoint(
            ctypes.wintypes.POINT(x, y))
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def _uia_locate(channel, name, control_type, index):
    """UIA 路由元素定位:枚举面非空时工具面做命中/歧义/候选判定;
    枚举面为空(懒启用空/通道未供清单)由信道 rect_of 直查定位
    (信道自持树检索与 fail-closed)。"""
    elems = (channel.snapshot() or {}).get("elements") or []
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
    rect = channel.rect_of(name=name, control_type=control_type,
                           index=index)
    return (list(rect),
            {"name": name or "", "control_type": control_type or ""})


def browser_get_rect(window=None, name=None, control_type=None, index=None,
                     *, manager=None, cdp=None, uia=None, ocr=None,
                     topmost=None) -> dict:
    """元素定位 → {rect, element, occluded, top_element}。

    入参:window=窗口句柄(可空);name=名称子串;control_type=类型过滤;
    index=多命中序号;topmost=顶层判定接缝(缺省=生产装配);其余同
    路由器通道接缝。返回:坐标包 dict(详设 §3.4 返回表)。
    """
    from .router import select_channel
    chname, channel, _target = select_channel(
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
        rect, element = _uia_locate(channel, name, control_type, index)
    # T2-03:遮挡自检(坐标点顶层元素判定;照给坐标,判断归 AI)
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    if topmost is None:
        topmost = _topmost_at
    top = topmost((cx, cy))
    occluded = bool(top) and top != element["name"]
    return {"rect": rect, "element": element,
            "occluded": occluded,
            "top_element": top if occluded else ""}
