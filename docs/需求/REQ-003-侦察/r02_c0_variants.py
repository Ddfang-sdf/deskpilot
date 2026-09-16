"""REQ-003 R-02 C0 变体对照(侦察证据归档):CV 基线四变体在真实 UI 上的表现。

变体:A 阈值连通域 / B 阈值外轮廓 / C 边缘图(Canny→膨胀闭合→外轮廓) /
     D 自适应阈值(mean,C=10,块25→闭运算→外轮廓)
样本:wxwork-main-全盲.png、seeyou-accelerator-全盲.png(真实自绘 UI 族)。
口径:框数(>=150px²)+耗时;C/D 标注图存档目检(面板合并是否消解、图标是否逐枚分离)。
"""
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
MIN_AREA = 150
K = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))


def imread_cn(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


def variant_mask(gray, v):
    if v in ("A", "B"):
        bw = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)[1]
        return cv2.morphologyEx(bw, cv2.MORPH_CLOSE, K, iterations=2)
    if v == "C":
        e = cv2.Canny(gray, 50, 150)
        e = cv2.dilate(e, K, iterations=1)
        return cv2.morphologyEx(e, cv2.MORPH_CLOSE, K, iterations=2)
    if v == "D":
        bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 25, 10)
        return cv2.morphologyEx(bw, cv2.MORPH_CLOSE, K, iterations=2)


def boxes_of(bw, v):
    if v == "A":
        n, _l, stats, _c = cv2.connectedComponentsWithStats(bw, 8)
        return [(int(x), int(y), int(x + w), int(y + h))
                for x, y, w, h, a in stats[1:] if a >= MIN_AREA]
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        if cv2.contourArea(c) >= MIN_AREA:
            x, y, w, h = cv2.boundingRect(c)
            out.append((x, y, x + w, y + h))
    return out


for sp in (SAMPLES / "wxwork-main-全盲.png",
           SAMPLES / "seeyou-accelerator-全盲.png"):
    img = imread_cn(sp)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    print(f"== {sp.stem} ({img.shape[1]}x{img.shape[0]}) ==")
    for v in "ABCD":
        t0 = time.perf_counter()
        boxes = boxes_of(variant_mask(gray, v), v)
        ms = (time.perf_counter() - t0) * 1000
        print(f"  {v}: {len(boxes):3d} 框  {ms:6.1f} ms")
        if v in ("C", "D"):
            vis = img.copy()
            for (l, t, r, b) in boxes:
                cv2.rectangle(vis, (l, t), (r, b), (60, 60, 255), 2)
            out = SAMPLES / f"r02-c0{v}-{sp.stem}.png"
            cv2.imencode(".png", vis)[1].tofile(str(out))
