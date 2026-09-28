"""M1 感知路由器(REQ-005 详设 §3.2):按归属选择通道并归一输出。

路由规则:M1-01 「窗口为空」与「命中归属注册表」是仅有的两条 CDP
路由,其余一律 UIA;M1-02 注册表命中但实例已死 → WINDOW_GONE+重新
拉起指引,不降级;M1-03 渲染窗/内容根定位是 UIA 通道职责。
"""

from __future__ import annotations

from ..errors import WINDOW_GONE, ExecutorError


def default_manager():
    """生产默认管理器(M4 门面,模块级注册表)。"""
    from .manager import Manager
    return Manager()


def select_channel(window, *, manager=None, cdp=None, uia=None, ocr=None):
    """M1-01/02 通道判定(纯选择,不驱动)。

    返回 (通道名, 通道对象, 目标):通道名 ∈ {"cdp", "uia"};
    目标 = CDP 路由的注册表项 / UIA 路由的窗口句柄。
    显式通道缝:恰一路通道注入且无管理器 = 调用方已定通道(测试缝),
    直接选定不进注册表判定。
    """
    if manager is None and (cdp is not None) != (uia is not None):
        if cdp is not None:
            return "cdp", cdp, window
        return "uia", uia, window
    if manager is None:
        manager = default_manager()
    if window is None:
        instance = manager.ensure_instance()      # M1-01 默认目标;T4-01 幂等
        if cdp is None:
            from .cdp import CdpChannel
            cdp = CdpChannel(instance)            # 注册表项绑通道(生产)
        return "cdp", cdp, instance
    instance = manager.lookup(window)
    if instance is not None:
        if not manager.probe(instance):           # M1-02:死实例不降级
            raise ExecutorError(
                WINDOW_GONE,
                f"共管浏览器实例已死亡(窗口 {window} 不再属于存活实例);"
                "请省略 window 参数重新拉起共管实例")
        if cdp is None:
            from .cdp import CdpChannel
            cdp = CdpChannel(instance)
        return "cdp", cdp, instance
    if uia is None:
        from .uia import UiaChannel
        uia = UiaChannel()
    return "uia", uia, window                      # M1-01:其余一律 UIA


def route(window=None, *, allow_pixel_fallback: bool = True,
          manager=None, cdp=None, uia=None, ocr=None):
    """按归属选择通道并返回通道结果。

    入参:window=窗口句柄(可空=默认目标共管实例);
    allow_pixel_fallback=是否允许像素兜底(默认允许);
    manager/cdp/uia/ocr=通道与管理器接缝(缺省=生产装配)。
    输出:通道选择结果 + 归一数据(元素集/坐标)。
    """
    name, channel, target = select_channel(
        window, manager=manager, cdp=cdp, uia=uia, ocr=ocr)
    return {"source": name, "target": target, "data": channel.snapshot()}
