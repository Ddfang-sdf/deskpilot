"""M1 感知路由器(REQ-005 详设 §3.2):按归属选择通道并归一输出。

路由规则:M1-01 「窗口为空」与「命中归属注册表」是仅有的两条 CDP
路由,其余一律 UIA;M1-02 注册表命中但实例已死 → WINDOW_GONE+重新
拉起指引,不降级;M1-03 渲染窗/内容根定位是 UIA 通道职责。
P1 空壳:仅签名,逻辑未实现。
"""

from __future__ import annotations


def route(window=None, *, allow_pixel_fallback: bool = True,
          manager=None, cdp=None, uia=None, ocr=None):
    """按归属选择通道并返回通道结果。

    入参:window=窗口句柄(可空=默认目标共管实例);
    allow_pixel_fallback=是否允许像素兜底(默认允许);
    manager/cdp/uia/ocr=通道与管理器接缝(缺省=生产装配)。
    输出:通道选择结果 + 归一数据(元素集/坐标)。
    """
    raise NotImplementedError("REQ-005 P1 空壳:route 逻辑未实现")
