"""OCR/检测/SoM 桥接族(ISS-0055 S3):OCR 懒初始化/检测器懒装填与
记忆化口径/模板匹配/SoM 标注——自 Executor 外迁。

搬函数留委托(self→ex 首参;跨族调用经 ex 委托门面回 core,本模块
不 import 任何兄弟族模块)。懒加载状态与装配位(ocr_factory/
detector_factory/weight_manifest/detector_threshold)留实例不动。
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ..errors import (DETECTOR_UNAVAILABLE, INTERNAL_ERROR, ExecutorError)
from .detector import resolve, screened, to_virtual, verify

# REQ-003 D-20(2026-09-15 sdfang 裁定):去重判据集合排除**结构容器类**节点——
# 容器是结构不是元素,字面全量会让整窗 Pane/画布 Group 把候选全灭(TC-INT-02
# 实测暴露);禁用/零面积元素仍全量参与(D-17 五理由不动)。
_DEDUP_EXCLUDE_TYPES = frozenset({
    "WindowControl", "PaneControl", "GroupControl",
    "ScrollBarControl", "TitleBarControl", "MenuBarControl",
})


def ocr(ex, source) -> dict:
    """文字识别（§12.6）：图像路径来源直读；区域来源实拍后识别。

    ISS-0008 P2 懒加载：引擎首次使用时经 ocr_factory 恰好初始化一次
    （线程安全）；初始化失败记忆化，后续调用直接显式报错（INV-7）。
    ISS-0021：source 接受区域 dict（left/top/width/height）直通——
    调用方已持区域时无需再转元组（click_text 实拍链路复用）。
    """
    if ex._ocr_engine is None:
        ex._ensure_ocr_engine()
    if isinstance(source, str):
        try:
            img = Image.open(source)
        except OSError as e:
            raise ExecutorError(INTERNAL_ERROR, f"OCR 源图像不可读: {e}") from e
    elif isinstance(source, dict):
        img = ex._capture(source)
    else:
        img = ex._capture(ex._region_dict(source))
    items = ex._ocr_engine(img)
    return {"items": items, "count": len(items)}


def _ensure_ocr_engine(ex) -> None:
    """懒初始化 OCR 引擎（ISS-0008 §6）：恰好一次；失败记忆化。"""
    if ex._ocr_failed is not None:
        raise ExecutorError(INTERNAL_ERROR,
                            f"OCR 引擎不可用: {ex._ocr_failed}")
    with ex._ocr_lock:
        if ex._ocr_engine is not None:
            return
        if ex._ocr_failed is not None:
            raise ExecutorError(INTERNAL_ERROR,
                                f"OCR 引擎不可用: {ex._ocr_failed}")
        if ex.ocr_factory is None:
            ex._ocr_failed = ("未装配 ocr_factory"
                              "（请安装 rapidocr-onnxruntime）")
            raise ExecutorError(INTERNAL_ERROR,
                                f"OCR 引擎不可用: {ex._ocr_failed}")
        try:
            ex._ocr_engine = ex.ocr_factory()
        except Exception as e:
            ex._ocr_failed = str(e)
            raise ExecutorError(INTERNAL_ERROR,
                                f"OCR 引擎不可用: {e}") from e


def _ensure_detector(ex):
    """懒装填检测器（REQ-003 §9.1，承 `_ensure_ocr_engine` 形态）：
    恰好一次；**记忆化口径 §8.1**——`未装配` 与 `装填失败` 记忆化
    （重试无益），校验失败**不**记忆化（人类按指引放下权重后，下一次
    调用必须立即可用），推理异常不记忆化（瞬态，在调用点归约）。

    校验在工厂之前：缺权重时不进入后端加载路径，错误更早更准。
    """
    if ex._detector is not None:
        return ex._detector
    if ex._detector_failed is not None:
        raise ExecutorError(DETECTOR_UNAVAILABLE,
                            f"检测器不可用: {ex._detector_failed}")
    with ex._detector_lock:
        # 锁内复检:多线程服务面下两个并发 detect=true 会同时通过首查
        if ex._detector is not None:
            return ex._detector
        if ex._detector_failed is not None:
            raise ExecutorError(DETECTOR_UNAVAILABLE,
                                f"检测器不可用: {ex._detector_failed}")
        if ex.detector_factory is None:
            ex._detector_failed = ("未装配 detector_factory"
                                   "（检测器选型待 D-12 终裁）")
            raise ExecutorError(
                DETECTOR_UNAVAILABLE,
                f"检测器不可用: {ex._detector_failed}。"
                f"下一步: 等待出厂检测器落地,或由装配方注入 detector_factory")
        configured = ex._weights_dir_configured
        manifest = ex.weight_manifest or {}
        if manifest:
            # 清单非空才有权重可验;空清单(CV 线零权重,D-12 终裁)
            # = 无权重可验,跳过目录解析与校验,直接装填(详设 §13
            # 「空清单 = ok 是真实语义」的编排落点)
            if not configured:
                # 有清单却未配置目录——**不记忆化**(配置补上后即应生效)
                raise ExecutorError(
                    DETECTOR_UNAVAILABLE,
                    "未配置检测权重目录（policy.yml 顶层 detector_weights_dir "
                    "缺省）。下一步: 在 policy.yml 设置 detector_weights_dir, "
                    "并把权重文件放入该目录")
            wdir = resolve(configured)
            report = verify(wdir, manifest)
            conclusion = report["conclusion"]
            if conclusion == "dir_missing":
                raise ExecutorError(
                    DETECTOR_UNAVAILABLE,
                    f"检测权重目录不存在: {report['dir']};期望文件清单: "
                    f"{sorted(manifest)}。下一步: 创建该目录并按"
                    f"清单放入权重文件（校验不记忆化,放下即可用）")
            if conclusion == "file_missing":
                raise ExecutorError(
                    DETECTOR_UNAVAILABLE,
                    f"检测权重文件缺失: {report['missing']}（目录 "
                    f"{report['dir']}）。下一步: 把缺失文件放入该目录后重试"
                    f"（校验不记忆化,放下即可用）")
            if conclusion == "hash_mismatch":
                detail = "; ".join(
                    f"{m['name']} 实际 {m['actual']} ≠ 期望 {m['expected']}"
                    for m in report["mismatched"])
                raise ExecutorError(
                    DETECTOR_UNAVAILABLE,
                    f"检测权重哈希不符（文件被改动或版本不符）: {detail}"
                    f"（目录 {report['dir']}）。下一步: 重新获取与清单一致"
                    f"的权重文件（校验不记忆化,放回即可用）")
        try:
            ex._detector = ex.detector_factory()
        except Exception as e:
            ex._detector_failed = f"装填失败: {e}"
            raise ExecutorError(
                DETECTOR_UNAVAILABLE,
                f"检测器装填失败: {e}。下一步: 按异常原文检查推理后端"
                f"与权重文件完整性") from e
        return ex._detector


def template_match(ex, template: str, scope, threshold: float = 0.8) -> dict:
    """模板匹配（§12.6）：在屏幕范围搜索模板，未达阈值如实返回最高置信度。"""
    tpl = cv2.imread(template, cv2.IMREAD_COLOR)
    if tpl is None:
        raise ExecutorError(INTERNAL_ERROR, f"模板图像不可读: {template}")
    scene_img = ex._capture(ex._region_dict(scope))
    scene = np.asarray(scene_img.convert("RGB"))[:, :, ::-1]
    if scene.shape[0] < tpl.shape[0] or scene.shape[1] < tpl.shape[1]:
        return {"found": False, "best_confidence": 0.0, "matches": []}
    res = cv2.matchTemplate(scene, tpl, cv2.TM_CCOEFF_NORMED)
    h, w = tpl.shape[:2]
    best = float(res.max())
    matches: list[dict] = []
    if best >= threshold:
        # 高于阈值的全部峰，按模板尺寸做非极大值抑制
        suppressed: set[tuple[int, int]] = set()
        peaks = sorted(zip(*np.where(res >= threshold)),
                       key=lambda p: -res[p[0], p[1]])
        for y, x in peaks:
            if (y, x) in suppressed:
                continue
            for dy in range(max(0, y - h), min(res.shape[0], y + h + 1)):
                for dx in range(max(0, x - w), min(res.shape[1], x + w + 1)):
                    suppressed.add((dy, dx))
            matches.append({"x": int(x + w // 2), "y": int(y + h // 2),
                            "confidence": float(res[y, x])})
    return {"found": bool(matches), "best_confidence": best,
            "matches": matches[:20]}


def get_clickable_map(ex, window, detect: bool = False) -> dict:
    """SoM 标注（§12.6）：可交互非零面积元素按阅读顺序编号入图，
    对照表连同窗口句柄存入缓存（60 秒有效）。

    REQ-003（详设 §6/§9.1）：`detect=True` 追加图形检测通道——懒装填
    检测器（校验权重 → 建检测器 → 推理 → 坐标收口 → 去重）后把未被 UIA
    枚举覆盖的候选并入编号空间。检测任一步失败 → DETECTOR_UNAVAILABLE
    显式报错,**不落图、不返回 entries**(fail-closed,无"退回纯 UIA"
    降级路径)。`detect=False`（缺省）走既有路径，除新增 `coord_space`
    外零变化（DET-04）。
    """
    hwnd = ex._resolve_window(window)
    root = ex._element_root(hwnd)
    wl, wt, wr, wb = ex._probe.rect_of(hwnd)
    # ISS-0008 P4：每节点属性一次成型（同名属性不重复读 COM）
    summaries = list(ex._iter_summaries(root))
    interactable = []
    for s in summaries:
        if not s["enabled"]:
            continue
        rect = s["rect"]
        if rect is None or rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
            continue
        interactable.append(s)
    interactable.sort(key=lambda s: (s["rect"][1], s["rect"][0]))
    img = ex._capture({"left": wl, "top": wt,
                       "width": wr - wl, "height": wb - wt})
    # REQ-003 §6:检测通道(仅 detect=True;失败面全部 fail-closed 上抛)
    kept: list[dict] = []
    if detect:
        detector = ex._ensure_detector()
        try:
            raw = detector(img)     # 契约(§2):入参内存图,出参恰两键
        except Exception as e:
            # 推理异常**不记忆化**(瞬态,§8.1);零落图零 entries
            raise ExecutorError(
                DETECTOR_UNAVAILABLE,
                f"检测推理失败: {e}。下一步: 按异常原文排查;"
                f"若为瞬态可稍后重试") from e
        origin = (wl, wt)           # 截图原点(§3.5):收口只在此处
        cands = [{"rect": to_virtual(c["rect"], origin),
                  "confidence": c["confidence"]} for c in raw]
        # 判据集合 = UIA 枚举**全量减去结构容器**(D-17 全量含禁用/零面积,
        # D-20 再减容器类——容器是结构不是元素,字面全量会毯式全灭候选)。
        # D-20 补充(同日实测):**宿主型 CustomControl**(XAML 承载根,毯盖
        # 后代,画图/Windows Terminal 的内容区都是它)同属结构容器;判据=
        # 其矩形覆盖其它摘要中心点。叶子型 CustomControl(真自绘控件)保留
        # ——其上检测框仍按 UIA 优先去重,防双编号。
        uia_rects = []
        for s in summaries:
            rect = s["rect"]
            if rect is None or s["control_type"] in _DEDUP_EXCLUDE_TYPES:
                continue
            if s["control_type"] == "CustomControl":
                l, t, r, b = rect
                hosts = any(
                    o is not s and o["rect"] is not None
                    and l <= (o["rect"][0] + o["rect"][2]) / 2 <= r
                    and t <= (o["rect"][1] + o["rect"][3]) / 2 <= b
                    for o in summaries)
                if hosts:
                    continue
            uia_rects.append(rect)
        kept = screened(cands, uia_rects, ex.detector_threshold)
        # 检测器输出顺序不承诺(§2);检测内部按同一坐标序排位(§9.6)
        kept.sort(key=lambda c: (c["rect"][1], c["rect"][0]))
    draw = ImageDraw.Draw(img)
    entries: list[dict] = []
    # ISS-0081：编号的生命周期是「单次取图」，缓存必须与之一致——
    # 先构建局部新表，取图成功后再**整表替换**，不留任何旧编号。
    # （逐键覆盖会残留上次清单里多出来的编号：AI 拿旧编号仍能点到东西并报 ok。）
    fresh: dict[int, dict] = {}
    fresh_detect: dict[int, dict] = {}
    now = ex._clock()
    for i, s in enumerate(interactable, start=1):
        l, t, r, b = s["rect"]
        rel = [l - wl, t - wt, r - wl, b - wt]
        draw.rectangle(rel, outline=(255, 60, 60), width=3)
        draw.text((rel[0] + 2, max(0, rel[1] - 16)), str(i), fill=(255, 0, 0))
        # ISS-0066 ②:id 与 som_id 双写同值(输出↔click_element 入参
        # 命名对齐;id 标废弃日程,下个大版本删)
        entry = {"id": i, "som_id": i, "name": s["name"],
                 "control_type": s["control_type"],
                 "automation_id": s["automation_id"],
                 "rect": [l, t, r, b]}
        if detect:
            # SOM-02 统一键集(§5.2,七键不省略,FD-09):
            # UIA 条目 source="uia"、confidence 恒 null
            entry["source"] = "uia"
            entry["confidence"] = None
        entries.append(entry)
        fresh[i] = {"hwnd": hwnd, "name": s["name"],
                    "automation_id": s["automation_id"],
                    "expires": now + 60.0}
    # §9.6:检测区域追加在 UIA 之后,占 N+1..N+M;同一套画法(SOM-03)
    for j, c in enumerate(kept, start=len(interactable) + 1):
        l, t, r, b = c["rect"]
        rel = [l - wl, t - wt, r - wl, b - wt]
        draw.rectangle(rel, outline=(255, 60, 60), width=3)
        draw.text((rel[0] + 2, max(0, rel[1] - 16)), str(j), fill=(255, 0, 0))
        entries.append({"id": j, "source": "detect", "name": None,
                        "control_type": None, "automation_id": None,
                        "rect": [l, t, r, b],
                        "confidence": c["confidence"]})
        # detect 表仅存 {hwnd, expires}(FD-02):不可寻址,只供诊断分支
        fresh_detect[j] = {"hwnd": hwnd, "expires": now + 60.0}
    out = ex._shots_dir / time.strftime("%Y%m%d")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%H%M%S')}_som_{int(time.time()*1000)%100000}.png"
    img.save(path)
    # 取图成功后才换表：落盘失败则本次没有任何编号交到 AI 手上，
    # 其手中的上一张图仍然有效，缓存须原样保留（fail-closed，不静默降级）。
    ex._som_cache = fresh
    # §9.6:detect=False 时 detect 表**置空**而非保留——消除"上次开了检测、
    # 这次没开,旧 detect 编号还能命中"的残留面
    ex._detect_cache = fresh_detect
    return {"path": str(path), "count": len(entries), "entries": entries,
            "coord_space": "virtual_desktop"}
