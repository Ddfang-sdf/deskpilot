"""M6 UIA 通道(REQ-005 详设 §3.6):渲染窗/内容根定位、懒启用复走、
壳层信息(标签/地址栏/活动标签)。复用 executor 的 UIA/截图/OCR
感知面,不另起 UIA 封装(S-03)。

定位规则(详设):Chromium=窗口内类名 Chrome_RenderWidgetHostHWND;
非 Chromium=窗口内首个 DocumentControl。T6-01 每次现查禁用历史
句柄;T6-02 懒启用:首查空 → 等 3s → 复走一次,仅此一次(复走时序
在 browser_snapshot 工具面,T1-02);T6-04 深度/节点上限沿用 executor
既有(get_ui_tree 同规)。
"""

from __future__ import annotations

from ..errors import ELEMENT_NOT_FOUND, ExecutorError

_CONTENT_CLASS = "Chrome_RenderWidgetHostHWND"   # Chromium 渲染窗类名
_SHELL_EDIT_TYPES = {"Edit", "EditControl"}


def _ctrl_rect(c) -> list:
    try:
        r = c.BoundingRectangle
        return [r.left, r.top, r.right, r.bottom]
    except Exception:
        return None


class UiaChannel:
    """UIA 路由通道(executor 感知面复用;线程 COM 初始化必过
    executor._ensure_com 缝——ISS-0106 教训)。"""

    def __init__(self, executor=None):
        self._ex = executor

    def _executor(self):
        if self._ex is None:
            raise ExecutorError(ELEMENT_NOT_FOUND,
                                "UIA 通道未装配 executor 感知面")
        return self._ex

    def _content_root(self, hwnd):
        """T6-01:渲染窗/内容根每次现查(禁用历史句柄)。"""
        ex = self._executor()
        ex._ensure_com()                     # ISS-0106:线程 COM 缝必过
        import uiautomation
        root = uiautomation.ControlFromHandle(hwnd)
        for c in ex._iter_controls(root, depth=0):
            try:
                if c.ClassName == _CONTENT_CLASS:
                    return c
            except Exception:
                continue
        for c in ex._iter_controls(root, depth=0):
            try:
                if c.ControlTypeName == "DocumentControl":
                    return c                  # 非 Chromium:首 DocumentControl
            except Exception:
                continue
        return None

    def _shell_info(self, hwnd, root) -> dict:
        """T6-03 壳层:标题/活动标签/标签清单/地址栏(取不到置空,
        不报错——T1-03)。"""
        ex = self._executor()
        title, tabs, url = "", [], ""
        try:
            for w in ex._probe.find_windows(hwnd=hwnd):
                if w.get("hwnd") == hwnd:
                    title = w.get("title", "")
                    break
        except Exception:
            pass
        try:
            for c in ex._iter_controls(root, depth=0):
                try:
                    tn = c.ControlTypeName
                except Exception:
                    continue
                if tn == "TabItemControl":
                    tabs.append(c.Name or "")
                elif tn in _SHELL_EDIT_TYPES and not url:
                    url = ex._node_text(c) or ""
        except Exception:
            pass
        return {"title": title, "active_tab": tabs[0] if tabs else "",
                "tabs": tabs, "url": url}

    def snapshot(self, target) -> dict:
        """UIA 路由快照(target=窗口句柄:内容根 → 统一元素集 + 壳层
        信息)。通道接口统一面:所有通道 snapshot(target),CDP 忽略
        target(实盘缺陷一修法)。"""
        ex = self._executor()
        content = self._content_root(target)
        meta = self._shell_info(target, content)
        if content is None:
            return {"elements": [], "meta": meta}
        elements = []
        for c in ex._iter_controls(content, depth=0):
            try:
                name = c.Name or ""
                ct = c.ControlTypeName
                enabled = bool(c.IsEnabled)
            except Exception:
                continue
            if not name:
                continue
            elements.append({"name": name, "control_type": ct,
                             "rect": _ctrl_rect(c),
                             "interactable": enabled, "state": {}})
        return {"elements": elements, "meta": meta}

    def rect_of(self, target, name=None, control_type=None,
                index=None) -> list:
        """UIA 路由坐标(T2-04):target=窗口句柄,内容根树内直查,
        rect 直用零换算。"""
        ex = self._executor()
        if target is None:
            raise ExecutorError(ELEMENT_NOT_FOUND,
                                "UIA 坐标解析缺窗口句柄")
        content = self._content_root(target)
        if content is None:
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                "未找到网页内容区(若非浏览器窗口请用 get_ui_tree)")
        matched = []
        for c in ex._iter_controls(content, depth=0):
            try:
                cname = c.Name or ""
                ctype = c.ControlTypeName
            except Exception:
                continue
            if name and name in cname:
                if control_type and ctype != control_type:
                    continue
                matched.append(c)
        if not matched:
            raise ExecutorError(ELEMENT_NOT_FOUND,
                                f"未找到元素: {name}")
        if len(matched) > 1 and index is None:
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                f"元素命中 {len(matched)} 处,请用 index 指定")
        target = matched[index or 0]
        rect = _ctrl_rect(target)
        if rect is None:
            raise ExecutorError(ELEMENT_NOT_FOUND,
                                f"元素矩形不可得: {name}")
        return rect


class OcrChannel:
    """像素兜底通道(T1-02 兜底,F-01):executor OCR 感知面直用,
    元素标注不可点(interactable=false)。snapshot(target):target=
    窗口句柄(可取 None=全屏)。"""

    def __init__(self, executor=None):
        self._ex = executor

    def snapshot(self, target) -> dict:
        if self._ex is None:
            raise ExecutorError(ELEMENT_NOT_FOUND,
                                "OCR 通道未装配 executor 感知面")
        region = None
        if target is not None:
            rect = self._ex._probe.rect_of(target)
            region = {"left": rect[0], "top": rect[1],
                      "width": rect[2] - rect[0],
                      "height": rect[3] - rect[1]}
        out = self._ex.ocr(region)
        elements = [{"name": it.get("text", ""), "control_type": "Text",
                     "rect": list(it.get("rect", [])), "interactable": False,
                     "state": {}}
                    for it in out.get("items", [])]
        return {"elements": elements,
                "meta": {"url": "", "title": "", "active_tab": ""}}


# ---- 模块级函数面(设计接口表:通道 snapshot(hwnd)/rect(element)) ----

def snapshot(hwnd, *, executor=None, allow_pixel_fallback: bool = True,
             ocr=None) -> dict:
    """UIA 路由快照(渲染窗/内容根 → 统一元素集 + 壳层信息)。"""
    return UiaChannel(executor).snapshot(hwnd)


def rect(hwnd, element, *, executor=None) -> dict:
    """UIA 路由坐标(T2-04):rect 直用零换算 + 遮挡自检。"""
    name = element if isinstance(element, str) else (element or {}).get(
        "name")
    return {"rect": UiaChannel(executor).rect_of(hwnd, name=name)}
