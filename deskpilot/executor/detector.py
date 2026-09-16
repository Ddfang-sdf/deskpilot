"""检测器层(REQ-003 详细设计 v0.2 §3.3~§3.6)。

组成(§2):权重目录锚定、权重校验、坐标收口、去重判据。四者均为**纯函数**
(§2 组成视图的职责列即写「纯函数:…」),故按仓库既有形态(`desktop_icons.py`
的模块级 `rects_intersect` 与容器类同模块)落为**模块级公开函数**,测试直接
import 本体调用。设计文档 §3 的「成员」表用中文标签描述语义(如
`to_virtual(rect, 原点)`),落地的形参名按仓库既有代码风格取英文——
`resolve` 例外,其形参名由 §3.3 钉死为与 `audit_paths.resolve_audit_dir`
**逐位同名**(`configured` / `policy_path`),测试设计 TC-WDIR-05 直接比对
两者 `__code__.co_varnames`。

**为什么是模块级函数而非类方法**:§3.3 要求 `resolve` 的形参与
`resolve_audit_dir` 逐位相同,而该方法本身就是 `audit_paths.py` 的模块级
函数(ISS-0010 先例);做成类方法会让 `co_varnames` 多出 `self`,使 §3.3
的可比对性失效。四者在 §2 被列为「组成」是为标明**单一职责边界**,
落地形态由仓库既有风格与 §3.3 的签名约束共同决定。

SDD 阶段:本文件为 **P3 已实现**——纯函数层五项工具 + 注册表(D-12 终裁
回填 `cv-contour`,CV 管线零权重)+ 清单(恒空,D-16 闭环)。Executor 侧
编排在 `core.py` 落地。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from ..errors import DETECTOR_UNAVAILABLE, ExecutorError

__all__ = ["to_virtual", "to_image", "screened", "verify", "resolve",
           "DetectorRegistry", "WeightManifest", "CvContourDetector"]


# ---------- 检测器注册表(§3.1) ----------

class DetectorRegistry:
    """标识 → 工厂 的只读映射(§3.1)。

    `names()` 给出已注册标识清单(只读,出厂固定);`build(标识)` 产出检测器,
    标识不存在 → 抛「未知检测器标识」(`DETECTOR_UNAVAILABLE`,§11 错误语义
    全表);工厂内的异常**原样上抛**由调用方归约(§3.1)。

    出厂标识表 = 文件尾 `_REGISTRY` 常量(D-12 已终裁回填 `cv-contour`);
    只读、无运行期改写入口。
    """

    def names(self) -> tuple[str, ...]:
        """已注册标识清单(只读,出厂固定)。"""
        return tuple(_REGISTRY)

    def build(self, name):
        """按标识产出检测器;标识不存在抛「未知检测器标识」(§3.1)。"""
        factory = _REGISTRY.get(name)
        if factory is None:
            raise ExecutorError(
                DETECTOR_UNAVAILABLE,
                f"未知检测器标识: {name};已注册标识: {list(_REGISTRY)}。"
                f"下一步: 核对标识拼写,或等待检测器选型(D-12)终裁后使用出厂标识")
        return factory()


# ---------- 权重清单(§3.2 / D-18) ----------

# 出厂清单常量(D-12 已裁:**CV 单线零权重**,清单恒空;「空清单 = 校验通过」
# 是真实语义而非占位——本线没有权重可验,D-16「代码内无下载器」彻底闭环)。
# 若未来启用模型线(C2,独立需求单),此处回填 标识 → {相对路径 → sha256}。
_MANIFEST: dict = {}


class WeightManifest:
    """标识 → {相对路径 → sha256}(§3.2)。

    模块级常量 `_MANIFEST` 为主体;经 `Executor.weight_manifest` 装配位可替
    (D-18,装配位持**扁平 {相对路径 → sha256}** 形态,与 `verify()` 入参同形),
    但缺省值即出厂常量,生产装配**不赋值**。

    D-12 终裁 CV 单线零权重,出厂清单**恒空**。
    """

    def files(self, name) -> dict[str, str]:
        """该检测器所需的全部权重文件及其出厂期望哈希(§3.2)。"""
        return dict(_MANIFEST.get(name, {}))


# ---------- 坐标收口(§3.5 / §9.4) ----------

def to_virtual(rect, origin):
    """图像坐标 rect → 虚拟屏坐标 rect(§3.5):逐分量平移,不缩放。"""
    ox, oy = origin
    l, t, r, b = rect
    return [l + ox, t + oy, r + ox, b + oy]


def to_image(rect, origin):
    """虚拟屏坐标 rect → 图像坐标 rect(§3.5):`to_virtual` 的成对逆运算。"""
    ox, oy = origin
    l, t, r, b = rect
    return [l - ox, t - oy, r - ox, b - oy]


# ---------- 去重判据(§3.6 / §9.5) ----------

def _center_inside(rect, uia_rect) -> bool:
    """中心点 ((l+r)/2, (t+b)/2) 是否落在 uia_rect 内——**闭区间**(§3.6)。"""
    cx = (rect[0] + rect[2]) / 2
    cy = (rect[1] + rect[3]) / 2
    ul, ut, ur, ub = uia_rect
    return ul <= cx <= ur and ut <= cy <= ub


def screened(candidates, uia_rects, threshold):
    """去重判据(§3.6):先按置信度门槛过滤,再丢弃中心点落入任一 UIA 矩形的候选。

    返回**同形态**的 `list[dict]`(保留下来的候选原样,恰两键 `rect`/`confidence`),
    **不产出 `id`**——编号权归 Executor(§9.6)。纯函数:无 IO、无时钟、无状态。
    """
    kept = [c for c in candidates if c["confidence"] >= threshold]
    return [c for c in kept
            if not any(_center_inside(c["rect"], u) for u in uia_rects)]


# ---------- 权重校验(§3.4 / §9.2) ----------

def _sha256_of(path: Path) -> str:
    """逐块计算文件 sha256——权重可达数百 MB,不整读进内存。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(directory, manifest) -> dict:
    """权重校验(§3.4):目录 → 存在 → 哈希三段递进,返回**单字典**。

    键 `conclusion` 恒有,取值域四值闭合 `dir_missing`/`file_missing`/
    `hash_mismatch`/`ok`;诊断键 `dir` 恒有,`missing` 仅分支②,`mismatched`
    仅分支③。结论与诊断同源同出,不做缓存(每次 `detect=true` 都查)。
    """
    root = Path(directory)
    report: dict = {"dir": str(root)}

    if not root.is_dir():
        return {**report, "conclusion": "dir_missing"}

    missing = sorted(name for name in manifest if not (root / name).is_file())
    if missing:
        return {**report, "conclusion": "file_missing", "missing": missing}

    # 逐文件只算一次哈希:权重可达数百 MB,条件里再算一遍等于读两遍盘
    mismatched = []
    for name, expected in sorted(manifest.items()):
        actual = _sha256_of(root / name)
        if actual != expected:
            mismatched.append({"name": name, "actual": actual,
                               "expected": expected})
    if mismatched:
        return {**report, "conclusion": "hash_mismatch",
                "mismatched": mismatched}

    return {**report, "conclusion": "ok"}


# ---------- 权重目录锚定(§3.3 / §9.3) ----------

def resolve(configured, policy_path=None) -> Path:
    """由锚定规矩算出权重目录绝对路径(§3.3)。

    与 `audit_paths.resolve_audit_dir` **同规矩、同签名、同分支顺序**:
    绝对路径原样;冻结形态锚定到可执行文件所在目录;源码形态锚定到策略文件
    所在目录;两者皆无锚定当前工作目录。三分支一致是刻意的——用户对"相对
    路径锚在哪"已有一次心智模型,不引入第二个(§9.3)。
    """
    p = Path(configured)
    if p.is_absolute():
        return p
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / p
    if policy_path:
        return Path(policy_path).resolve().parent / p
    return Path.cwd() / p


# ---------- CV 检测器(D-12 终裁:出厂唯一标识 cv-contour,零权重) ----------

# 管线参数(侦察变体 E 校准,证据见侦察方案 §5.2):
#   自适应阈值(块 25,C=10) → 轻闭运算(3×3×1) → 连通域 → 过滤。
_CV_BLOCK = 25            # 自适应阈值邻域块
_CV_C = 10                # 自适应阈值常数
_CV_MIN_AREA = 150        # 噪声下限(前景像素)
_CV_BIG_RATIO = 0.15      # 外接框占图比例上限(超过且稀疏=纹理团)
_CV_FILL_MIN = 0.35       # 大团的填充率下限(低于即判纹理,丢弃)


class CvContourDetector:
    """CV 管线检测器(D-12 终裁出厂线;侦察变体 E 产品化)。

    契约(详设 §2):入参 = 内存中的 PIL 图像(不接受路径);出参 =
    `list[dict]`,每条**恰两键** `{"rect": [l,t,r,b], "confidence": float}`,
    图像坐标;零副作用;装填后无状态。

    **confidence 口径(D-12 裁定)**:CV 线无学习置信度,此值 = **几何显著度**
    (填充率派生,越实越高),值域 [0.5, 0.99];**不是语义置信度**,描述面
    对 AI 须写明(§5.4 描述含此义)。检测不到任何图形 = 返回空清单
    (如实,非失败);只有管线内部异常才算失败上抛。
    """

    def __call__(self, image) -> list[dict]:
        import cv2                              # 局部 import:装填即导入,
        import numpy as np                      # 不进本模块头部(DET-07 面)
        arr = np.asarray(image.convert("RGB"))
        h, w = arr.shape[:2]
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV,
                                   _CV_BLOCK, _CV_C)
        bw = cv2.morphologyEx(
            bw, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
        n, _labels, stats, _cents = cv2.connectedComponentsWithStats(bw, 8)
        out: list[dict] = []
        for i in range(1, n):
            x, y, bw_, bh_, area = (int(v) for v in stats[i])
            if area < _CV_MIN_AREA:
                continue
            bbox_area = bw_ * bh_
            fill = area / max(bbox_area, 1)
            # 纹理抑制:大而稀(点阵地图/半调底纹)丢弃——控件与涂鸦「小而实」
            if bbox_area > _CV_BIG_RATIO * w * h and fill < _CV_FILL_MIN:
                continue
            confidence = round(min(0.99, 0.5 + 0.49 * fill), 3)
            out.append({"rect": [x, y, x + bw_, y + bh_],
                        "confidence": confidence})
        return out


def _build_cv_contour() -> CvContourDetector:
    """出厂工厂(§3.1):CV 管线检测器,零权重零装填开销。"""
    return CvContourDetector()


# 出厂标识表(D-12 终裁回填):`cv-contour` = CV 管线。模块级常量为主体,
# 无运行期改写入口——注册表若可被用户改写,权重校验与装配位都形同虚设。
_REGISTRY = {"cv-contour": _build_cv_contour}
