"""click_text 的文字→坐标求解纯函数（ISS-0021 A/B,问题单 §3/§5）。

零 I/O:输入 OCR items(契约形态见 main._build_ocr_engine:
{"text": str, "position": [x1,y1,x2,y2]} 图像像素平铺包围盒),
输出 (status, payload) 二元组:

| status         | payload                          | 语义(fail-closed) |
|----------------|----------------------------------|-------------------|
| "ok"           | {"point": (x,y), "matched": str} | 唯一/指定命中,虚拟桌面坐标 |
| "not_found"    | str(OCR 可见文本摘要)            | 零命中,禁止放行 |
| "ambiguous"    | [(x,y), ...](各命中虚拟坐标)     | 多命中未指定 index,禁止放行 |
| "out_of_window"| (x,y)(越界框中心)                | OCR 框越出图像,数据异常 |
| "invalid"      | str(原因)                        | 参数非法(空 text/非法 match/index 越界) |

坐标换算:图像像素框中心 → 虚拟桌面坐标,scale=rect 宽高/图像宽高;
框中心取整数除法(//2)保证跨平台确定性。
"""

from __future__ import annotations

import difflib


def _normalize(s: str) -> str:
    """ISS-0035 C3：命中与建议共用归一化(单源:strip+casefold)。"""
    return str(s).strip().casefold()


def resolve_click(items, query, match, index, img_w, img_h, rect):
    """OCR items 中求 query 的点击点(虚拟桌面坐标)。"""
    if not isinstance(query, str) or not query.strip():
        return ("invalid", "text 为空")
    if match not in ("contains", "exact"):
        return ("invalid", f"match 非法: {match}")

    nq = _normalize(query)
    if match == "exact":
        hits = [it for it in items
                if _normalize(it.get("text", "")) == nq]
    else:
        hits = [it for it in items
                if nq in _normalize(it.get("text", ""))]
    if not hits:
        summary = " ".join(it.get("text", "") for it in items)[:80]
        return ("not_found", summary)
    if len(hits) > 1 and index is None:
        return ("ambiguous", [_virtual_point(it, img_w, img_h, rect)
                              for it in hits])
    i = index if index is not None else 0
    if not (0 <= i < len(hits)):
        return ("invalid", f"index 越界: {i}(命中 {len(hits)} 处)")

    chosen = hits[i]
    box = chosen.get("position") or [0, 0, 0, 0]
    if box[0] < 0 or box[1] < 0 or box[2] > img_w or box[3] > img_h:
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        return ("out_of_window", (cx, cy))
    return ("ok", {"point": _virtual_point(chosen, img_w, img_h, rect),
                   "matched": chosen.get("text", "")})


def suggest_similar(items, query, limit: int = 3,
                    min_ratio: float = 0.5) -> list[str]:
    """ISS-0027 B：OCR 未命中时的相似文本候选(纯函数,difflib)。

    按 SequenceMatcher ratio 降序取前 limit 个(≥min_ratio)。
    仅产出文本建议——无坐标、无动作载荷,"建议即执行"由形态层杜绝。
    """
    nq = _normalize(query)
    scored = sorted(
        ((difflib.SequenceMatcher(None, nq,
                                  _normalize(str(it.get("text", ""))))
          .ratio(), it.get("text", ""))
         for it in items),
        key=lambda p: p[0], reverse=True)
    return [text for r, text in scored if r >= min_ratio][:limit]


def _virtual_point(item, img_w, img_h, rect) -> tuple:
    """item 框中心(图像像素)→ 虚拟桌面坐标(整数除法保确定性)。"""
    box = item["position"]
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    scale_x = (rect[2] - rect[0]) / img_w
    scale_y = (rect[3] - rect[1]) / img_h
    return (int(rect[0] + cx * scale_x), int(rect[1] + cy * scale_y))
