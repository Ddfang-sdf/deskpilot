"""REQ-003 检测器纯函数层测试(测试设计 v0.2 §2 的接缝 1/2/4/5 直出用例)。

层级:**单元**。被测对象是 `deskpilot.executor.detector` 的模块级纯函数本体
(真实现,零替身);仅文件系统经 `tmp_path` 造真实样本,时钟/网络/窗口一概不涉。
按测试设计 §1 的归层判据,`TC-COORD-*`/`TC-DEDUP-*`/`TC-WVER-*`/`TC-WDIR-*`
共 18 条全部落单元层。

层内替身说明(测试设计 §1 第 45 行):「**真纯函数本体**;仅文件系统经
`tmp_path` 造样本(无替身)」。`TC-WDIR-02` 需要 `sys.frozen` 为真——
该属性在源码形态下**不存在**(非「值为假」),故用 `monkeypatch.setattr`
临时装上并按测试设计 §2 第 80 行的口径以「替身属性」对待,属既有的
「时钟/探针接缝」同类做法(`tests/conftest.py` 的 `FakeClock`/`FakeProbe`)。

断言出处(三条铁律之三):全部断言值取自被测函数的**返回值**或文件系统上
由本用例自己造出的**持久化数据**(哈希、路径),无中间转换、无人工比对。
唯一的形态断言是 `TC-WDIR-05` 的 `__code__.co_varnames` 比对——出处是
**函数对象自身**,非人工誊抄。

用例来源:详细设计 v0.2 §3.3/§3.4/§3.5/§3.6 + §9.2/§9.3/§9.4/§9.5;
测试设计 v0.2 §2 的 TC-COORD-01/01b/01c、TC-DEDUP-01~06、
TC-WVER-01~04、TC-WDIR-01~05。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from deskpilot.audit_paths import resolve_audit_dir
from deskpilot.executor.detector import (resolve, screened, to_image,
                                          to_virtual, verify)


# ---------- 造样本(无替身:真文件、真哈希) ----------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_for(root: Path, files: dict[str, bytes]) -> dict[str, str]:
    """把真文件写到磁盘,返回其出厂期望哈希清单(标识→{相对路径→sha256})。

    清单形态取自详细设计 §3.2:`{相对路径 → sha256}`。这里返回的就是
    单标识下的那段映射,`verify` 的第二形参按 §3.4 即「清单」。
    """
    root.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (root / name).write_bytes(data)
    return {name: _sha256(data) for name, data in files.items()}


# ---------- 接缝 1:坐标收口成对函数(§3.5 / §9.4) ----------

class TestCoordCloser:
    """图像坐标 ↔ 虚拟屏坐标的成对平移。

    「截图原点非零」是本组全部用例的共同前提——承侦察章程 §8.2 的
    「混用不报错、静默给 0」教训(详细设计 §4 坐标契约表的按语)。
    """

    ORIGIN = (100, 100)
    IMAGE_RECT = [10, 20, 40, 50]
    VIRTUAL_RECT = [110, 120, 140, 150]

    def test_image_to_virtual(self):
        """TC-COORD-01:图像坐标 rect + 非零原点 → 虚拟屏坐标 rect。"""
        assert to_virtual(self.IMAGE_RECT, self.ORIGIN) == self.VIRTUAL_RECT

    def test_not_passthrough(self):
        """TC-COORD-01b:**漏加原点对照组**。

        证伪「静默给 0 / 原样透传」这一类失效:结果必须**不等于**入参原值,
        且等于上格的期望值。两条一起断言,缺任一条都可能漏掉一种坏实现
        (只断言「不等于入参」时,返回任意乱数也能过)。
        """
        got = to_virtual(self.IMAGE_RECT, self.ORIGIN)
        assert got != self.IMAGE_RECT
        assert got == self.VIRTUAL_RECT

    def test_virtual_to_image_and_roundtrip(self):
        """TC-COORD-01c:反向函数 + 往返恒等(§3.5「成对性要求」)。"""
        assert to_image(self.VIRTUAL_RECT, self.ORIGIN) == self.IMAGE_RECT
        rect = [7, 13, 29, 41]
        origin = (1234, -56)
        assert to_image(to_virtual(rect, origin), origin) == rect


# ---------- 接缝 2:去重判据(§3.6 / §9.5) ----------

def _cand(rect, confidence):
    """检测候选(恰两键,§2 检测器契约):虚拟屏 rect + 置信度。"""
    return {"rect": list(rect), "confidence": confidence}


class TestDeduper:
    """中心点落入口径(闭区间),门槛过滤先于去重。

    全部断言取自 `screened` 的**返回值**;`TC-DEDUP-06` 的注(测试设计 §2)
    明确:`screened` 返回**恰两键**候选、**无 `id`**——编号权在 Executor
    (§9.6),此层不得出现对 `id` 的任何断言。
    """

    THRESHOLD = 0.5

    def test_center_inside_uia_dropped(self):
        """TC-DEDUP-01:候选中心点落入 UIA 矩形 → 丢弃。"""
        got = screened([_cand([120, 120, 180, 180], 0.9)],
                       [[100, 100, 200, 200]], self.THRESHOLD)
        assert len(got) == 0

    def test_center_outside_kept(self):
        """TC-DEDUP-02:中心点不落入 → 保留。"""
        kept = _cand([300, 300, 340, 340], 0.9)
        got = screened([kept], [[100, 100, 200, 200]], self.THRESHOLD)
        assert got == [kept]

    def test_boundary_point_counts_as_inside(self):
        """TC-DEDUP-03:**恰好压边界**(闭区间口径)。

        候选 [180,180,220,220] 的中心点 =(200,200),正是 UIA 矩形的右下角。
        §3.6 口径为闭区间(边界点算落入),故须丢弃;若实现写成开区间,
        本用例红。
        """
        got = screened([_cand([180, 180, 220, 220], 0.9)],
                       [[100, 100, 200, 200]], self.THRESHOLD)
        assert len(got) == 0

    def test_any_of_multiple_uia_rects_dedupes(self):
        """TC-DEDUP-04:落入**任一** UIA 矩形即去重(多矩形)。"""
        uia = [[100, 100, 200, 200], [400, 400, 500, 500]]
        inside_second = _cand([420, 420, 460, 460], 0.9)   # 中心 (440,440)
        got = screened([inside_second], uia, self.THRESHOLD)
        assert len(got) == 0

    def test_spanning_candidate_with_center_in_gap_kept(self):
        """TC-DEDUP-05:候选框横跨两元素、中心落在缝中 → **保留**。

        对称性要求(§9.5 说明):不因框大而误判全重叠。这是「中心点落入」
        口径相对「面积交叠比」口径的可陈述理由。
        """
        uia = [[100, 100, 200, 200], [300, 100, 400, 200]]   # 中间 200~300 是缝
        spanning = _cand([150, 120, 350, 180], 0.9)          # 中心 (250,150) 在缝里
        got = screened([spanning], uia, self.THRESHOLD)
        assert got == [spanning]

    def test_threshold_filter_and_boundary(self):
        """TC-DEDUP-06:门槛过滤与边界(置信度 0.49 / 0.5 / 0.51 同批)。

        `< 门槛` 才丢弃,故 0.5 **保留**(闭下端)。断言集合长度==2 与两条
        `confidence` 逐条直出;不涉 `id`(§9.6 编号权在 Executor)。
        """
        far = [900, 900, 940, 940]          # 远离 UIA,只受门槛影响
        batch = [_cand(far, 0.49), _cand(far, 0.5), _cand(far, 0.51)]
        got = screened(batch, [[100, 100, 200, 200]], self.THRESHOLD)
        assert len(got) == 2
        assert [c["confidence"] for c in got] == [0.5, 0.51]


# ---------- 接缝 4:权重校验四分支(§3.4 / §9.2) ----------

class TestWeightVerifier:
    """目录 → 存在 → 哈希三段递进;结论与诊断要素同字典(单返回值)。

    四分支的判别手段是返回字典的 `conclusion` 字段(四值闭合),
    **不得**靠「都抛异常」或人工比对通过(测试设计 §5 R7)。
    """

    FILES = {"model.onnx": b"weight-bytes-1", "labels.txt": b"names\n"}

    def test_dir_missing(self, tmp_path):
        """TC-WVER-01:目录不存在 → 结论① + 目录绝对路径。"""
        missing = tmp_path / "no_such_dir"
        manifest = {"model.onnx": _sha256(b"x")}
        got = verify(missing, manifest)
        assert got["conclusion"] == "dir_missing"
        assert got["dir"] == str(missing)

    def test_file_missing(self, tmp_path):
        """TC-WVER-02:目录存在、清单内缺 1 个文件 → 结论② + 缺失文件名清单。"""
        root = tmp_path / "weights"
        manifest = _manifest_for(root, self.FILES)
        (root / "labels.txt").unlink()
        got = verify(root, manifest)
        assert got["conclusion"] == "file_missing"
        assert got["missing"] == ["labels.txt"]
        assert got["dir"] == str(root)

    def test_hash_mismatch(self, tmp_path):
        """TC-WVER-03:文件齐备但内容被改 → 结论③ + 逐文件「实际 vs 期望」对照。"""
        root = tmp_path / "weights"
        manifest = _manifest_for(root, self.FILES)
        (root / "model.onnx").write_bytes(b"tampered")
        got = verify(root, manifest)
        assert got["conclusion"] == "hash_mismatch"
        assert got["mismatched"] == [{"name": "model.onnx",
                                      "actual": _sha256(b"tampered"),
                                      "expected": manifest["model.onnx"]}]
        assert got["dir"] == str(root)

    def test_all_match_key_set_is_exactly_dir(self, tmp_path):
        """TC-WVER-04:全符通过 → 结论④,且键集**恰为** `{"conclusion","dir"}`。

        键集断言证明诊断键是**不存在**而非空值——「空 list 也算无附带信息」
        的弱断言会让「恒填三个键」的实现蒙混过关。

        **P2 修订(据实记录)**:测试设计 v0.2 该行原文写「键集恰为 `{"dir"}`」,
        与详细设计 §3.4「`conclusion` **恒有**」直接冲突,且与本用例自身的前
        一条断言(`got["conclusion"]=="ok"` 要求该键存在)自相矛盾——照字面
        落笔的用例**无法同时成立**。语意显然是「诊断键 `missing`/`mismatched`
        不出现」,`conclusion` 作为恒有键必须在键集内。故断言写为
        `{"conclusion", "dir"}`,证伪力不变(仍逐键锁死三个键的存在与否)。
        """
        root = tmp_path / "weights"
        manifest = _manifest_for(root, self.FILES)
        got = verify(root, manifest)
        assert got["conclusion"] == "ok"
        assert set(got) == {"conclusion", "dir"}


# ---------- 接缝 5:权重目录锚定(§3.3 / §9.3) ----------

class TestWeightDirResolver:
    """四分支锚定:绝对 / 冻结 / 策略目录 / cwd(与 `resolve_audit_dir` 同规矩)。"""

    def test_absolute_passthrough(self):
        """TC-WDIR-01:绝对路径原样返回(不看 policy_path、不看 frozen)。"""
        abs_path = Path.cwd() / "anchored" / "weights"
        assert resolve(str(abs_path), "/somewhere/policy.yml") == abs_path

    def test_frozen_anchors_executable_dir(self, monkeypatch, tmp_path):
        """TC-WDIR-02:`sys.frozen` 为真 → exe 所在目录 / 配置值。"""
        exe = tmp_path / "app" / "deskpilot.exe"
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        assert resolve("detector_weights", "/somewhere/policy.yml") == \
            exe.parent / "detector_weights"

    def test_source_form_anchors_policy_dir(self, tmp_path):
        """TC-WDIR-03:源码形态有 `policy_path` → 策略文件所在目录 / 配置值。"""
        policy = tmp_path / "cfg" / "policy.yml"
        assert resolve("detector_weights", str(policy)) == \
            policy.resolve().parent / "detector_weights"

    def test_no_anchor_falls_back_to_cwd(self):
        """TC-WDIR-04:非冻结且无 `policy_path`(=None)→ cwd / 配置值。"""
        assert resolve("detector_weights") == Path.cwd() / "detector_weights"

    def test_baseline_independent_and_signature_matched(self):
        """TC-WDIR-05:**基准独立** + 形参名与 `resolve_audit_dir` 逐位相同。

        ①取值由权重自己的键提供,不吃 `audit_dir`;
        ②形参名断言的出处是**两个函数对象自身**(§3.3「形参名」行的落地),
          非人工誊抄——`co_varnames` 由解释器从函数对象给出。
        """
        assert resolve("detector_weights", None) == \
            Path.cwd() / "detector_weights"
        assert resolve_audit_dir("audit_dir_value", None) == \
            Path.cwd() / "audit_dir_value"
        assert resolve.__code__.co_varnames[:2] == \
            resolve_audit_dir.__code__.co_varnames[:2]
