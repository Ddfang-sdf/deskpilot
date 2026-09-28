"""M6 UIA 通道(REQ-005 详设 §3.6):渲染窗/内容根定位、懒启用复走、
壳层信息(标签/地址栏/活动标签)。复用 executor 的 UIA/截图/OCR
感知面,不另起 UIA 封装(S-03)。

定位规则(详设):Chromium=窗口内类名 Chrome_RenderWidgetHostHWND;
非 Chromium=窗口内首个 DocumentControl。T6-01 每次现查禁用历史
句柄;T6-02 懒启用:首查空 → 等 3s → 复走一次,仅此一次。
P1 空壳:仅签名,逻辑未实现。
"""

from __future__ import annotations


def snapshot(hwnd, *, executor=None, allow_pixel_fallback: bool = True,
             ocr=None) -> dict:
    """UIA 路由快照(渲染窗/内容根 → 统一元素集 + 壳层信息)。

    入参:hwnd=浏览器窗口句柄;executor=executor 感知面接缝;
    allow_pixel_fallback/ocr=像素兜底开关与 OCR 通道接缝。
    返回:快照 dict(同 browser_snapshot 返回表)。
    """
    raise NotImplementedError("REQ-005 P1 空壳:uia.snapshot 逻辑未实现")


def rect(hwnd, element, *, executor=None) -> dict:
    """UIA 路由坐标(T2-04):rect 直用零换算 + 遮挡自检。

    入参:hwnd=浏览器窗口句柄;element=目标元素(名称/定位条件);
    executor=executor 感知面接缝。返回:坐标包 dict。
    """
    raise NotImplementedError("REQ-005 P1 空壳:uia.rect 逻辑未实现")
