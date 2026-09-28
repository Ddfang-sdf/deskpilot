"""browser_get_rect 工具面(REQ-005 详设 §3.4,MCP L0)。

元素定位 → 虚拟桌面坐标 + 遮挡真相。T2-01 CDP 换算:渲染窗物理矩形
原点 + 盒模型中心 × devicePixelRatio,三因子每次现取;T2-02 超界
fail-closed;T2-03 遮挡自检=坐标点顶层元素判定,occluded=true 坐标
照给并附 top_element;T2-04 UIA 路由零换算。P1 空壳:仅签名。
"""

from __future__ import annotations


def browser_get_rect(window=None, name=None, control_type=None, index=None,
                     *, manager=None, cdp=None, uia=None, ocr=None,
                     topmost=None) -> dict:
    """元素定位 → {rect, element, occluded, top_element}。

    入参:window=窗口句柄(可空);name=名称子串;control_type=类型过滤;
    index=多命中序号;topmost=顶层判定接缝(缺省=生产装配);其余同
    路由器通道接缝。返回:坐标包 dict(详设 §3.4 返回表)。
    """
    raise NotImplementedError("REQ-005 P1 空壳:browser_get_rect 逻辑未实现")
