"""M5 CDP 通道(REQ-005 详设 §3.5):共管实例的 AXTree 快照/盒模型坐标/
实例探活。唯读依赖 websocket-client。

命令面:Target.getTargets/attachToTarget(flatten)、Accessibility.enable/
getFullAXTree、DOM.getDocument/querySelector/getBoxModel、
Runtime.evaluate(仅 dpr/URL 读取)。T5-01 连接参数必须
suppress_origin=True;T5-02 每命令带 sessionId(flatten);
T5-04 快照超时预算 5s。R-MAP(AX role → control_type 映射表)随
P3 实现落地。P1 空壳:仅签名,逻辑未实现。
"""

from __future__ import annotations


class CdpClient:
    """CDP 协议客户端(flatten 会话;命令带 sessionId)。"""

    def __init__(self, ws_url: str, *, ws_factory=None):
        """入参:ws_url=DevTools ws 地址;ws_factory=ws 连接工厂接缝
        (生产=websocket.create_connection,握手 suppress_origin=True)。"""
        raise NotImplementedError("REQ-005 P1 空壳:CdpClient 逻辑未实现")

    def attach(self):
        """Target.getTargets → Target.attachToTarget(flatten)。"""
        raise NotImplementedError("REQ-005 P1 空壳:attach 逻辑未实现")

    def snapshot(self):
        """Accessibility.enable → Accessibility.getFullAXTree(AX 全树)。"""
        raise NotImplementedError("REQ-005 P1 空壳:snapshot 逻辑未实现")

    def box_model(self, node_id):
        """DOM.getDocument → DOM.querySelector → DOM.getBoxModel。"""
        raise NotImplementedError("REQ-005 P1 空壳:box_model 逻辑未实现")


def connect(ws_url: str, *, ws_factory=None) -> CdpClient:
    """建立 CDP 连接(握手 suppress_origin=True,T5-01)。"""
    raise NotImplementedError("REQ-005 P1 空壳:connect 逻辑未实现")
