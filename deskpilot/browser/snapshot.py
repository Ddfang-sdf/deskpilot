"""browser_snapshot 工具面(REQ-005 详设 §3.3,MCP L0)。

入参 window(可空=默认目标);返回 {title, url, active_tab, source,
truncated, elements:[统一元素…]}。T1-01 元素集截断上限 800;
T1-02 UIA 路由懒启用:首查空 → 等 3s → 复走一次,仍空转兜底/报错;
T1-04 快照不落盘不缓存。P1 空壳:仅签名,逻辑未实现。
"""

from __future__ import annotations

import time  # noqa: F401  # 懒启用等待接缝(T1-02;测试经 monkeypatch 替身)


def browser_snapshot(window=None, *, allow_pixel_fallback: bool = True,
                     manager=None, cdp=None, uia=None, ocr=None) -> dict:
    """统一语义快照(F-01 对外面)。

    入参:window=窗口句柄(可空);allow_pixel_fallback=像素兜底开关;
    manager/cdp/uia/ocr=通道与管理器接缝(缺省=生产装配)。
    返回:快照 dict(详设 §3.3 返回表)。
    """
    raise NotImplementedError("REQ-005 P1 空壳:browser_snapshot 逻辑未实现")
