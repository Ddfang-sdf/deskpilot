"""REQ-003 R-02 C0 变体 E(侦察证据归档):纹理背景抑制。

seeyou 的点阵世界地图在闭运算后连成大团 → A/B/C/D 全军覆没(合并)。
E = 自适应阈值(块25,C=10) + 轻闭运算(3x3,1次) + 连通域 + **填充率过滤**:
  丢弃条件 = 外接框占图 >15% 且 填充率(前景像素/外接框面积) < 0.35
  ——点阵纹理「大而稀」,控件/涂鸦「小而实」或「轮廓清晰」,以此分离。
样本:seeyou / wxwork / paint-v2(回归验证涂鸦不被误杀)。
"""
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"


def imread_cn(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


for sp in (SAMPLES / "seeyou-accelerator-全盲.png",
           SAMPLES / "wxwork-main-全盲.png",
           SAMPLES / "paint-canvas-v2-填充彩色.png"):
    img = imread_cn(sp)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t0 = time.perf_counter()
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 10)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
                          iterations=1)
    n, _l, stats, _c = cv2.connectedComponentsWithStats(bw, 8)
    kept, dropped = [], []
    for x, y, bw_, bh_, area in stats[1:]:
        if area < 150:
            continue
        bbox_area = bw_ * bh_
        fill = area / max(bbox_area, 1)
        big = bbox_area > 0.15 * w * h
        if big and fill < 0.35:
            dropped.append((x, y, bw_, bh_, round(fill, 2)))
            continue
        kept.append((x, y, x + bw_, y + bh_))
    ms = (time.perf_counter() - t0) * 1000
    print(f"== {sp.stem}: {len(kept)} 框(丢 {len(dropped)} 个稀疏大团) {ms:.1f}ms")
    for d in dropped:
        print(f"   丢弃: bbox=({d[0]},{d[1]},{d[2]}x{d[3]}) fill={d[4]}")
    vis = img.copy()
    for (l, t, r, b) in kept:
        cv2.rectangle(vis, (l, t), (r, b), (60, 60, 255), 2)
    cv2.imencode(".png", vis)[1].tofile(
        str(SAMPLES / f"r02-c0E-{sp.stem}.png"))
