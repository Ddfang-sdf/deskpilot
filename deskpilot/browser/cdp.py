"""M5 CDP 通道(REQ-005 详设 §3.5):共管实例的 AXTree 快照/盒模型坐标/
实例探活。唯读依赖 websocket-client。

命令面:Target.getTargets/attachToTarget(flatten)、Accessibility.enable/
getFullAXTree、DOM.getDocument/querySelector/getBoxModel、
Runtime.evaluate(仅 dpr/URL 读取,T5-03 v1 不开放任意脚本)。
T5-01 连接参数必须 suppress_origin=True;T5-02 每命令带 sessionId
(flatten);T5-04 快照超时预算 5s。
"""

from __future__ import annotations

import json

from ..errors import ELEMENT_NOT_FOUND, INTERNAL_ERROR, ExecutorError

# AX role → control_type 映射(R-MAP,详设 §3.5);未映射 role 原样透传
# 并标注 raw_role(不丢信息)
R_MAP = {
    "button": "ButtonControl",
    "link": "HyperlinkControl",
    "textbox": "EditControl",
    "searchbox": "EditControl",
    "checkbox": "CheckBoxControl",
    "combobox": "ComboBoxControl",
    "StaticText": "TextControl",
    "image": "ImageControl",
    "list": "ListControl",
    "listitem": "ListItemControl",
    "heading": "TextControl",          # 另在 state.heading 标注
    "dialog": "WindowControl",
}

SNAPSHOT_TIMEOUT_S = 5.0               # T5-04:快照超时预算


class CdpClient:
    """CDP 协议客户端(flatten 会话;命令带 sessionId)。"""

    def __init__(self, ws_url: str, *, ws_factory=None,
                 timeout: float = SNAPSHOT_TIMEOUT_S):
        """入参:ws_url=DevTools ws 地址;ws_factory=ws 连接工厂接缝
        (生产=websocket.create_connection,握手 suppress_origin=True);
        timeout=单命令收答预算(T5-04)。"""
        if ws_factory is None:
            import websocket
            ws_factory = websocket.create_connection
        self._ws = ws_factory(ws_url, suppress_origin=True)   # T5-01
        if hasattr(self._ws, "settimeout"):   # 替身工厂可返回裸对象(测试缝)
            self._ws.settimeout(timeout)
        self._next_id = 0
        self._session_id = None

    # ---- 协议骨架 ----

    def _cmd(self, method: str, params: dict | None = None) -> dict:
        """发一条命令并等同 id 应答(跳过事件帧);sessionId 自动携带
        (T5-02,attach 后)。"""
        self._next_id += 1
        mid = self._next_id
        msg: dict = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        if self._session_id:
            msg["sessionId"] = self._session_id
        self._ws.send(json.dumps(msg))
        while True:
            reply = json.loads(self._ws.recv())
            if reply.get("id") == mid:
                break                       # 事件帧跳过
        if "error" in reply:
            raise ExecutorError(INTERNAL_ERROR,
                                f"CDP {method} 失败: {reply['error']}")
        return reply.get("result", {})

    # ---- 命令面 ----

    def attach(self):
        """Target.getTargets → Target.attachToTarget(flatten)。"""
        targets = self._cmd("Target.getTargets")
        page = next((t for t in targets.get("targetInfos", [])
                     if t.get("type") == "page"), None)
        if page is None:
            raise ExecutorError(ELEMENT_NOT_FOUND, "共管实例无页面目标")
        res = self._cmd("Target.attachToTarget",
                        {"targetId": page["targetId"], "flatten": True})
        self._session_id = res["sessionId"]
        return self._session_id

    def snapshot(self):
        """Accessibility.enable → Accessibility.getFullAXTree(AX 全树)。"""
        self._cmd("Accessibility.enable")
        return self._cmd("Accessibility.getFullAXTree").get("nodes", [])

    def box_model(self, node_id):
        """DOM.getDocument → DOM.querySelector → DOM.getBoxModel。"""
        doc = self._cmd("DOM.getDocument", {"depth": 1})
        root_id = doc["root"]["nodeId"]
        q = self._cmd("DOM.querySelector",
                      {"nodeId": root_id, "selector": str(node_id)})
        return self._cmd("DOM.getBoxModel", {"nodeId": q["nodeId"]})

    # ---- Runtime.evaluate 只读两点(T5-03) ----

    def _eval_value(self, expression: str):
        r = self._cmd("Runtime.evaluate",
                      {"expression": expression, "returnByValue": True})
        return r.get("result", {}).get("value")

    def dpr(self) -> float:
        """devicePixelRatio 现取(T2-01 三因子之一)。"""
        return float(self._eval_value("window.devicePixelRatio") or 1.0)

    def url(self) -> str:
        """页面 URL 真值(T1-03 CDP 路由)。"""
        return str(self._eval_value("location.href") or "")


def connect(ws_url: str, *, ws_factory=None) -> CdpClient:
    """建立 CDP 连接(握手 suppress_origin=True,T5-01)。"""
    return CdpClient(ws_url, ws_factory=ws_factory)


# ---------- 生产通道适配(工具面三因子+快照) ----------

def _ax_prop(node: dict, name: str):
    for p in node.get("properties", []):
        if p.get("name") == name:
            return p.get("value", {}).get("value")
    return None


def _ax_unified(node: dict) -> dict:
    """AX 节点 → 通道原始元素(role 保留,归一在 snapshot 工具面)。"""
    return {"role": (node.get("role") or {}).get("value", ""),
            "name": (node.get("name") or {}).get("value", ""),
            "rect": node.get("rect"),
            "focusable": bool(_ax_prop(node, "focusable")),
            "state": {"checked": _ax_prop(node, "checked"),
                      "expanded": _ax_prop(node, "expanded")}}


class CdpChannel:
    """M5→工具面适配:snapshot/element_box/render_origin/dpr(T2-01 三因子
    每次现取)。"""

    def __init__(self, instance: dict | None = None, *, probe=None):
        self._instance = instance or {}
        if probe is None:
            from ..executor.probe import DesktopProbe
            probe = DesktopProbe()
        self._probe = probe
        self._client: CdpClient | None = None

    def _cli(self) -> CdpClient:
        if self._client is None:
            port = self._instance.get("port")
            ws_path = self._instance.get("ws_path", "")
            self._client = connect(f"ws://127.0.0.1:{port}{ws_path}")
            self._client.attach()
        return self._client

    def snapshot(self, target) -> dict:
        """CDP 路由快照(通道接口统一面:target=注册表项,忽略——
        读已 attach 的 target;实盘缺陷一修法)。"""
        nodes = self._cli().snapshot()
        elements = [_ax_unified(n) for n in nodes]
        return {"elements": elements,
                "meta": {"url": self._cli().url(), "title": "",
                         "active_tab": ""}}

    def element_box(self, name=None, control_type=None, index=None) -> dict:
        """按名称定位元素 → CSS box {left,top,right,bottom}。"""
        nodes = self._cli().snapshot()
        matched = [n for n in nodes
                   if name and name in ((n.get("name") or {})
                                        .get("value", ""))]
        if not matched:
            raise ExecutorError(ELEMENT_NOT_FOUND,
                                f"页面未找到元素: {name}")
        if len(matched) > 1 and index is None:
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                f"元素命中 {len(matched)} 处,请用 index 指定")
        node = matched[index or 0]
        backend = node.get("backendDOMNodeId")
        box = self._cli()._cmd("DOM.getBoxModel", {"backendNodeId": backend})
        quad = box["model"]["content"]
        xs, ys = quad[0::2], quad[1::2]
        return {"left": min(xs), "top": min(ys),
                "right": max(xs), "bottom": max(ys)}

    def render_origin(self) -> tuple[int, int]:
        """渲染窗物理矩形原点(T2-01 因子,现取)。"""
        rect = self._probe.rect_of(self._instance["hwnd"])
        return rect[0], rect[1]

    def dpr(self) -> float:
        return self._cli().dpr()
