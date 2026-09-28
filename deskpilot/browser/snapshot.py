"""browser_snapshot 工具面(REQ-005 详设 §3.3,MCP L0)。

入参 window(可空=默认目标);返回 {title, url, active_tab, source,
truncated, elements:[统一元素…]}。T1-01 元素集截断上限 800;
T1-02 UIA 路由懒启用:首查空 → 等 3s → 复走一次,仍空转兜底/报错;
T1-04 快照不落盘不缓存。
"""

from __future__ import annotations

import time

from ..errors import ELEMENT_NOT_FOUND, ExecutorError
from .cdp import R_MAP

LAZY_ENABLE_WAIT_S = 3.0               # T1-02/T6-02:懒启用等待(仅此一次)
MAX_ELEMENTS = 800                     # T1-01:截断上限(与 get_ui_tree 同规)


def _normalize_element(e: dict) -> dict:
    """通道原始元素 → 统一元素(详设 §3.1 数据结构)。

    CDP 来源带 role:R-MAP 映射 control_type;未映射原样透传并标注
    raw_role。UIA/OCR 来源已为统一形态,字段直用。
    """
    out = {"name": e.get("name", ""),
           "rect": e.get("rect"),
           "interactable": bool(e.get("interactable", e.get("focusable",
                                                            False))),
           "state": dict(e.get("state") or {})}
    role = e.get("role")
    if role is not None:
        mapped = R_MAP.get(role)
        if mapped is None:
            out["control_type"] = role
            out["raw_role"] = role            # 未映射透传(不丢信息)
        else:
            out["control_type"] = mapped
            if role == "heading":
                out["state"]["heading"] = True      # 标注 heading
    else:
        out["control_type"] = e.get("control_type", "")
    return out


def _normalize_snapshot(raw: dict, source: str) -> dict:
    elements = [_normalize_element(e) for e in raw.get("elements", [])]
    truncated = len(elements) > MAX_ELEMENTS          # T1-01
    elements = elements[:MAX_ELEMENTS]
    meta = raw.get("meta", {})
    return {"title": meta.get("title", ""),
            "url": meta.get("url", ""),
            "active_tab": meta.get("active_tab", ""),
            "source": source, "truncated": truncated,
            "elements": elements}


def browser_snapshot(window=None, *, allow_pixel_fallback: bool = True,
                     manager=None, cdp=None, uia=None, ocr=None) -> dict:
    """统一语义快照(F-01 对外面)。

    入参:window=窗口句柄(可空);allow_pixel_fallback=像素兜底开关;
    manager/cdp/uia/ocr=通道与管理器接缝(缺省=生产装配)。
    返回:快照 dict(详设 §3.3 返回表)。
    """
    from .router import select_channel
    name, channel, target = select_channel(
        window, manager=manager, cdp=cdp, uia=uia, ocr=ocr)
    if name == "cdp":
        return _normalize_snapshot(channel.snapshot(target), "cdp")
    # UIA 路由:懒启用(T1-02/T6-02)——首查空 → 等 3s → 复走一次
    raw = channel.snapshot(target)
    if not raw.get("elements"):
        time.sleep(LAZY_ENABLE_WAIT_S)
        raw = channel.snapshot(target)              # 复走,仅此一次
    if not raw.get("elements"):
        if allow_pixel_fallback:
            if ocr is None:
                from .uia import OcrChannel
                ocr = OcrChannel()
            return _normalize_snapshot(ocr.snapshot(target), "ocr")
        raise ExecutorError(
            ELEMENT_NOT_FOUND,
            "页面暂不可读(初始化未完成),请稍后重试或省略 window "
            "走共管浏览器")
    return _normalize_snapshot(raw, "uia")
