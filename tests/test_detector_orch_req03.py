"""REQ-003 编排层测试(Executor 侧):检测通道编排 / 编号空间 / 治理面。

层级:**单元**(测试设计 v0.5 §1 装配矩阵第 3 行 —— 真 Executor 与两份编号
缓存本体)。替身只打在**两个公开装配位**(`executor.detector_factory` /
`executor.weight_manifest`)与既有构造接缝(`probe`/`element_source`/
`_shot_fn`);懒装填状态机、权重校验(`verify()`)、坐标收口、编号排位、
整表替换**全部真实**——这正是 §1 第 3b 行要证的东西。

**断言出处(三条铁律之三)**:全部断言值取自 `get_clickable_map` 的**返回值**
(count / entries 的键与取值)、`execute` 的**返回值**、替身检测器/工厂的
**调用计数**、落盘目录**快照**与注册表**文本**;无中间转换、无人工誊抄、
不读私有状态(不碰 `_detect_cache` 等内部结构 —— 绑死数据结构会让换实现
即假失败,同 `test_somcache_iss81.py` 的 P2 修订口径)。

用例来源:详细设计 v0.4 §3.1/§3.2/§5.1~§5.4/§6/§9.1/§9.6/§11;
功能设计 v0.3 §5.2;测试设计 v0.5 §2 全表(TC-DET-*/TC-SOM-*/TC-CACHE-*/
TC-CLK-01/TC-GOV-*)。
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from deskpilot.executor.core import Executor
from deskpilot.executor import core as core_mod
from deskpilot.errors import (DETECTOR_UNAVAILABLE, ELEMENT_NOT_FOUND,
                              ELEMENT_UNSUPPORTED, ExecutorError)
from deskpilot.mcp_server import TOOL_SCHEMAS, validate_call
from deskpilot.tools import _L0_DIRECT, call_tool

from .conftest import FIXTURE_HWND, FIXTURE_RECT, FakeProbe
from .test_elements import FakeElement

# 仓库根(本文件位于 <root>/tests/)
ROOT = Path(__file__).resolve().parents[1]


# ---------- 装配前提:两个公开装配位 + 既有构造接缝 ----------

# 截图原点 = FIXTURE_RECT 左上角(详设 §3.5「原点来源」)。刻意取非零值:
# 若实现漏掉坐标收口,检测 rect 会比期望值**整体小 (100,100)** —— 断言逐值
# 比对,漏收口必红(承章程 §8.2「混用不报错、静默给 0」的教训)。
ORIGIN = (FIXTURE_RECT[0], FIXTURE_RECT[1])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_weights(root, files: dict[str, bytes]) -> str:
    """把权重样本写成**真文件**,返回目录绝对路径。

    清单的**声明**是替的(出厂常量待 D-12 终裁,当下不存在);但落盘、打开、
    算哈希这些动作**全是真的** —— 本用例不构造空目录、不喂空清单,那会变成
    "校验放行"这另一种语义(测试设计 v0.5 §1 尾段的边界说明)。
    """
    root.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (root / name).write_bytes(data)
    return str(root)


class FakeDetector:
    """检测器替身(详设 §2 契约:可调用、入参内存图、输出恰两键)。

    ``calls`` 是断言源之一:若检测器压根没被调用,「候选全被去重」就退化成
    "检测通道没跑",命题未被证到 —— 故每条用例都断 ``calls``。
    入参形态如实遵守契约:只接内存图,接路径会显式失败而非静默。
    """

    def __init__(self, candidates: list[dict]):
        self._candidates = candidates
        self.calls = 0

    def __call__(self, image: Image.Image) -> list[dict]:
        assert isinstance(image, Image.Image), \
            "检测器契约(§2):入参是**已在内存**的 PIL 图像,不接受路径"
        self.calls += 1
        # 逐条深拷:输出顺序不作承诺,更不得与调用方共享可变状态
        return [dict(c) for c in self._candidates]


@pytest.fixture
def som_probe() -> FakeProbe:
    """窗口矩形探针(既有构造接缝,同 test_m3 / test_somcache_iss81)。"""
    p = FakeProbe()
    p.rects = {FIXTURE_HWND: FIXTURE_RECT}
    return p


WEIGHT_FILES = {"model.onnx": b"req03-weight-bytes", "labels.txt": b"names\n"}


def _executor(estop, tmp_path, clock, som_probe, candidates):
    """装配齐备的 Executor:两装配位经**公开属性**注入。

    权重目录以**绝对路径**经构造参数交给 Executor —— `resolve()` 对绝对
    路径原样返回(详设 §3.3 分支①),故此处的目录取值与生产装配
    (`main` 读 `policy.yml` 顶层 `detector_weights_dir` 键)走的是同一条
    解析路径,没有测试专用旁路。
    """
    weights = _write_weights(tmp_path / "detector_weights", WEIGHT_FILES)
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  wait_timeout_max=5.0, clock=clock, probe=som_probe,
                  detector_weights_dir=weights)
    ex._shot_fn = lambda region: Image.new("RGB", (700, 500), "white")
    ex.weight_manifest = {name: _sha256(data) for name, data in WEIGHT_FILES.items()}
    detector = FakeDetector(candidates)
    ex.detector_factory = lambda: detector
    return ex, detector


def _tree_enumeration_full() -> FakeElement:
    """UIA 替身流:三类元素各一(测试设计 v0.5 §2 第 134 行钉死的形态)。

      A 可交互、非零面积 → **既在枚举流里,也在编号空间里**
      B **禁用**、非零面积 → 在枚举流里,**不在**编号空间(被 `enabled` 排除)
      C **零面积**(rect 退化) → 在枚举流里,**不在**编号空间(被面积排除)

    两条**互不相同**的过滤臂各被覆盖一次 —— 这正是本用例不能只放一类
    被滤元素的原因(只放一类,判据取自编号空间也能蒙混过关)。
    """
    return FakeElement(children=[
        FakeElement(name="A", rect=(120, 120, 170, 150)),
        FakeElement(name="B", enabled=False, rect=(200, 150, 260, 190)),
        FakeElement(name="C", rect=(0, 0, 0, 0)),
    ])


def _cands(rects_in_virtual: list[list[int]]) -> list[dict]:
    """按**图像坐标**给出候选(检测器契约 §2:检测器只见图,不识虚拟屏)。

    入参写虚拟屏坐标(便于与 UIA 矩形直接对照),此处减掉截图原点 —— 这正是
    检测器**应当**看到的形态;坐标收口是 Executor 的责任(详设 §3.5:
    虚拟屏坐标**只**在 `CoordCloser` 处产生)。

    **关键**:若实现漏掉 `to_virtual`,这三条候选在判据阶段会整体偏 (100,100),
    与 UIA 矩形对不上 → 全部存活 → 断言②红。故本用例顺带把坐标契约证了。
    """
    return [{"rect": [r[0] - ORIGIN[0], r[1] - ORIGIN[1],
                      r[2] - ORIGIN[0], r[3] - ORIGIN[1]],
             "confidence": 0.9} for r in rects_in_virtual]


# ---------- TC-SOM-09:去重判据集合取枚举全量(与编号空间不同集) ----------

class TestSOM09DedupJudgementIsFullEnumeration:
    """本条要证的是「**判据集合** ⊋ **编号集合**」这个命题本身。

    单断一侧都会漏掉一种坏实现:
      · 只断「候选全被去重」→ 判据取编号空间(两集合同源)时**也**成立;
      · 只断「B/C 不在编号空间」→ 那是既有 `enabled`+非零面积的旧行为,
        与检测通道无关。
    两侧同断,才排除「两集合其实同源」这唯一读法之外的实现。
    """

    # 三条候选(虚拟屏坐标):中心点分别落在 A / B / C 的矩形内。
    # c 落在 C 的退化矩形 (0,0,0,0) 上 —— 中心点即 (0,0),闭区间口径下必然
    # 算「落入」(详设 §3.6「压边界算落入」)。三条置信度**同档**(0.9,高于
    # 任何常规门槛):B/C 被去重不得借"置信度不达标"通过,否则本用例证的是
    # 门槛而非判据集合(最隐蔽的一种假绿)。
    CANDIDATES_VIRTUAL = [
        [120, 120, 170, 150],      # a:中心 (145,135) 落 A 内
        [215, 160, 245, 180],      # b:中心 (230,170) 落 B 内
        [-20, -20, 20, 20],        # c:中心 (0,0) 落 C(退化矩形)内
    ]

    def test_all_candidates_deduped_and_only_a_numbered(self, estop, tmp_path,
                                                        clock, som_probe):
        """TC-SOM-09:三类 UIA 元素 + 三条同档候选 → 编号空间只剩 A、检测零条目。

        预期结果(测试设计 v0.5 §2 第 134 行)逐条落笔:
          ①`count == 1`(仅 UIA 条目 A),编号即 [1];
          ②entries 中**无任何** `source=="detect"` 的条目;
          ③entries 的 UIA 部分**不含** `B`/`C`。
        语义:「凡 UIA 枚举得到的矩形,检测不在其上编号」—— 检测通道是**纯
        增量**,只覆盖 UIA 从枚举层面看不见的地方(详设 §3.6 / 功能设计 §5.2)。

        **残余证伪力(如实记账)**:设计未配"候选落在三类矩形之外则全部存活"
        的对照组,故"检测候选一律丢弃"这类坏实现在本用例上返回体相同、不被
        证伪(②③的理由另说:若真在丢弃,`count==1` 与"B/C 不入表"仍成立)。
        该对照组归 TC-SOM-06/07 的既有编号用例承接,此处不私增用例
        (R6 双向映射 —— 未登记的用例即偏离已批设计)。
        """
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands(self.CANDIDATES_VIRTUAL))
        ex._element_source = lambda hwnd: _tree_enumeration_full()

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        # ①编号空间只剩 A 一条
        assert got["count"] == 1
        assert [e["id"] for e in got["entries"]] == [1]
        assert [e["name"] for e in got["entries"]] == ["A"]

        # ②检测通道零条目。先显式建列表再断言,不写内联的 min()/next() ——
        # 空列表上的 min() 会抛 ValueError,那会让一条"因错得对"的用例看起来
        # 是通过(R7 要防的借道假绿)。
        assert detector.calls == 1, "检测器须被调用恰一次,否则②只是「检测没跑」"
        assert [e for e in got["entries"] if e["source"] == "detect"] == []

        # ③B/C 不在编号空间 —— 与①②合起来才证到「判据集合 ⊋ 编号集合」
        assert "B" not in [e["name"] for e in got["entries"]]
        assert "C" not in [e["name"] for e in got["entries"]]

# ---------- 共享装配助手(本条追加部分的公共前提) ----------

def _sensing_ctx(ctx, ex):
    """新建一个把真 Executor 挂到 `executor` 字段的 sensing 上下文(GOV-02 用)。

    `ToolContext` 是 **frozen** 数据类,不能赋值;按既有先例
    (test_httpd.py:177 / test_reliability_iss9.py:250)在构造期传入 `executor=`。
    enforcement/policy 沿用既有 ctx 的装配,只替换 sensing 执行器。
    """
    from deskpilot.tools import ToolContext
    return ToolContext(policy=ctx.policy, enforcement=ctx.enforcement,
                       bindings=ctx.bindings, executor=ex, audit=ctx.audit)


def _uia_only_entries(got) -> list:
    return [e for e in got["entries"] if e["source"] == "uia"]


def _detect_entries(got) -> list:
    return [e for e in got["entries"] if e["source"] == "detect"]


# ---------- TC-DET-01:detect=true 主链(成功支可证伪反证的基准) ----------

class TestDET01MainChain:
    """检测条目进 entries,`rect` 已收口为虚拟屏(与图像坐标不同)。

    反证(测试设计 §5 第四行):把替身清单换成故意不合的一份,本用例**必须转红**
    —— 成功支的"跑通"必须由**真 `verify()` 给出 ok 引起**,不得借"校验被绕过"
    通过。该反证由本条与 TC-DET-03a/03b 合起来承担:同一装配、只换清单。
    """

    # 两条候选(虚拟屏坐标):与空 UIA 树不重叠。
    CANDIDATES_VIRTUAL = [[400, 400, 460, 440], [520, 460, 580, 500]]

    def test_detect_entries_in_entries_with_virtual_rect(
            self, estop, tmp_path, clock, som_probe):
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands(self.CANDIDATES_VIRTUAL))
        # 空 UIA 树:检测候选无去重对象,全部进编号空间
        ex._element_source = lambda hwnd: FakeElement(children=[])

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert detector.calls == 1, "检测器须恰被调用一次,否则本条证的是「没跑」"
        detect = _detect_entries(got)
        assert len(detect) == 2
        for e in detect:
            # 条目形态(详设 §5.2):detect 条目三语义键恒 null
            assert e["source"] == "detect"
            assert e["confidence"] == 0.9
            assert e["name"] is None
            assert e["control_type"] is None
            assert e["automation_id"] is None
        # rect 已收口为虚拟屏:与替身给的图像坐标(减过原点)不同
        image_rects = [[c["rect"][0], c["rect"][1], c["rect"][2], c["rect"][3]]
                       for c in _cands(self.CANDIDATES_VIRTUAL)]
        for e in detect:
            assert e["rect"] not in image_rects, \
                "rect 与图像坐标相同 = 漏收口(应加原点 (100,100))"
        # 收口的期望值:逐分量 == 原虚拟屏坐标
        assert [e["rect"] for e in detect] == self.CANDIDATES_VIRTUAL
        # 本单补齐的坐标系声明(详设 §5.1)
        assert got["coord_space"] == "virtual_desktop"


# ---------- TC-DET-02:本单权重不入包(形态) ----------

class TestDET02WeightsNotBundled:
    """①`deskpilot/` 包内零权重文件;②`deskpilot.spec` 的 datas 与基线逐字相同。

    基线取 **git HEAD blob**(`git show HEAD:deskpilot.spec`)—— 本单明令
    spec 零改动,故 HEAD 即"改动前基线",且不是自我指涉(工作树才是被测对象)。
    git 不可用时 `pytest.skip` 并留痕,**不**静默通过。
    """

    def test_no_weight_files_in_package(self):
        exts = (".onnx", ".pt", ".pth", ".weights")
        hits = [p for p in (ROOT / "deskpilot").rglob("*")
                if p.suffix.lower() in exts]
        assert hits == [], f"deskpilot/ 内出现权重文件: {hits}"

    def test_spec_datas_unchanged_vs_head(self):
        spec_path = ROOT / "deskpilot.spec"
        worktree = spec_path.read_text(encoding="utf-8")
        try:
            head = subprocess.run(
                ["git", "show", "HEAD:deskpilot.spec"], cwd=ROOT,
                capture_output=True, text=True, check=True,
                encoding="utf-8").stdout
        except Exception as e:  # git 不可用 → 显式跳过并留痕
            pytest.skip(f"git 不可用,无法取 HEAD 基线: {e}")
        assert worktree == head, "deskpilot.spec 与 HEAD 基线不一致(本单应零改动)"


# ---------- TC-DET-03a/03b:校验失败两支(真 verify() 产出结论) ----------

class TestDET03WeightVerifyFailures:
    """失败支一律注入**故意不合**的替身清单,由**真 `verify()`** 产出结论;
    工厂**不被触达**(校验先于工厂,§9.1)。断言:异常码+message+零落图。"""

    def _shots_snapshot(self, tmp_path) -> set:
        d = tmp_path / "audit" / "shots"
        if not d.exists():
            return set()
        return {p.name for p in d.rglob("*") if p.is_file()}

    def test_missing_file_reports_detector_unavailable(
            self, estop, tmp_path, clock, som_probe):
        # 清单指向 `tmp_path` 下**实际不存在**的文件名(目录本身存在)
        weights = _write_weights(tmp_path / "detector_weights", WEIGHT_FILES)
        ex, detector = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])
        # 换入故意不合的清单:多一个不存在文件
        ex.weight_manifest = {**ex.weight_manifest, "ghost.onnx": _sha256(b"x")}
        before = self._shots_snapshot(tmp_path)

        with pytest.raises(ExecutorError) as ei:
            ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert ei.value.code == DETECTOR_UNAVAILABLE
        assert "ghost.onnx" in ei.value.message, "message 须含缺失文件名"
        assert weights in ei.value.message, "message 须含目录绝对路径"
        assert detector.calls == 0, "校验失败时工厂/检测器不得被触达"
        assert self._shots_snapshot(tmp_path) == before, "零落图(fail-closed)"

    def test_hash_mismatch_reports_actual_vs_expected(
            self, estop, tmp_path, clock, som_probe):
        # 真实文件落盘,但清单的期望哈希**故意写错**
        ex, detector = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])
        ex.weight_manifest = {name: "0" * 64 for name in WEIGHT_FILES}
        before = self._shots_snapshot(tmp_path)

        with pytest.raises(ExecutorError) as ei:
            ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert ei.value.code == DETECTOR_UNAVAILABLE
        # 「实际 vs 期望」对照:实算哈希与伪造期望都须出现在 message
        actual = _sha256(WEIGHT_FILES["model.onnx"])
        assert actual in ei.value.message, "message 须含实际 sha256"
        assert "0" * 64 in ei.value.message, "message 须含期望 sha256"
        assert detector.calls == 0
        assert self._shots_snapshot(tmp_path) == before


# ---------- TC-DET-04:默认零变化(detect 缺省不触检测通道) ----------

class TestDET04DefaultZeroChange:
    """不传 `detect`:替身检测器零调用、`verify()` 零调用、返回结构除新增
    `coord_space` 外与现状逐键一致。`verify` 经**模块路径记账**(R2 允许)。"""

    def test_detect_default_false_no_detector_no_verify(
            self, estop, tmp_path, clock, som_probe, monkeypatch):
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([[400, 400, 460, 440]]))
        ex._element_source = lambda hwnd: FakeElement(children=[
            FakeElement(name="A", rect=(120, 120, 170, 150))])
        # 经模块路径给 verify 记账(非替换 —— 真本体照跑,仅计数)
        from deskpilot.executor import detector as detector_mod
        real_verify = detector_mod.verify
        calls = {"n": 0}

        def counting_verify(directory, manifest):
            calls["n"] += 1
            return real_verify(directory, manifest)
        monkeypatch.setattr(core_mod, "verify", counting_verify, raising=False)
        monkeypatch.setattr(detector_mod, "verify", counting_verify)

        got = ex.get_clickable_map(FIXTURE_HWND)   # 不传 detect

        assert detector.calls == 0, "detect 缺省时检测器零调用"
        assert calls["n"] == 0, "detect=False 不触权重校验(非「查了没报错」)"
        assert got["coord_space"] == "virtual_desktop", "本单补齐的坐标系声明"
        # 返回结构除新增 coord_space 与 ISS-0066 ②双写 som_id 外与现状
        # **逐键一致**(§5.1 DET-04;契约修订备案见 ISS-0066 单据 v0.2):
        # 顶层恰四键;UIA 条目恰六键(统一键集 detect=true 面见 SOM-02)
        assert set(got) == {"path", "count", "entries", "coord_space"}
        assert got["count"] == 1
        assert [e["name"] for e in got["entries"]] == ["A"]
        assert set(got["entries"][0]) == {"id", "som_id", "name",
                                          "control_type",
                                          "automation_id", "rect"}
        assert got["entries"][0]["som_id"] == got["entries"][0]["id"]


# ---------- TC-DET-05a/05b:装填/推理失败 fail-closed ----------

class TestDET05FailClosed:
    """失败 → `DETECTOR_UNAVAILABLE`,**零落图零 entries**,不出「仅 UIA」的图。"""

    def _assert_fail_closed(self, tmp_path):
        d = tmp_path / "audit" / "shots"
        files = {p.name for p in d.rglob("*") if p.is_file()} if d.exists() else set()
        assert files == set(), "fail-closed:任何失败支不得落图"

    def test_load_failure_memorized_and_no_image(
            self, estop, tmp_path, clock, som_probe):
        # 清单合法且校验**通过**(证明失败来自工厂而非校验)
        ex, _ = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])
        boom = RuntimeError("backend missing: onnxruntime not installed")
        ex.detector_factory = lambda: (_ for _ in ()).throw(boom)

        with pytest.raises(ExecutorError) as ei:
            ex.get_clickable_map(FIXTURE_HWND, detect=True)
        assert "onnxruntime not installed" in ei.value.message, "须含异常原文"
        self._assert_fail_closed(tmp_path)

    def test_inference_exception_no_fallback_to_uia_only(
            self, estop, tmp_path, clock, som_probe):
        # 装填成功但调用时抛异常;且**不**退回纯 UIA 结果
        ex, detector = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[
            FakeElement(name="A", rect=(120, 120, 170, 150))])

        def exploding(image):
            raise RuntimeError("inference OOM")
        ex.detector_factory = lambda: exploding

        with pytest.raises(ExecutorError) as ei:
            ex.get_clickable_map(FIXTURE_HWND, detect=True)
        assert ei.value.code == DETECTOR_UNAVAILABLE
        assert "inference OOM" in ei.value.message
        self._assert_fail_closed(tmp_path)


# ---------- TC-DET-06/06b:可替换 + 调用面不变 / 未知标识 ----------

class TestDET06ReplaceableAndRegistry:
    def test_tool_surface_unchanged_except_optional_detect(self):
        """`TOOL_SCHEMAS` 29 条不变;`get_clickable_map` 仅增可选 `detect`。"""
        assert len(TOOL_SCHEMAS) == 29, "本单零新工具(R4 ①:29 保持)"
        schema = TOOL_SCHEMAS["get_clickable_map"]
        assert "detect" in schema["optional"], "detect 须为可选参数"
        assert schema["optional"]["detect"] == ("bool",), "detect 须为 bool 型"
        # 既有键集不变:window 仍必填,其余可选键未增删
        assert set(schema["required"]) == {"window"}

    def test_unknown_registry_identifier(self):
        """TC-DET-06b:未知标识 → `DETECTOR_UNAVAILABLE`(§11 错误语义全表);
        message 含所查标识 + 已注册标识清单。"""
        from deskpilot.executor.detector import DetectorRegistry
        reg = DetectorRegistry()
        with pytest.raises(ExecutorError) as ei:
            reg.build("no_such_detector_xyz")
        assert ei.value.code == DETECTOR_UNAVAILABLE
        msg = ei.value.message
        assert "no_such_detector_xyz" in msg, "message 须含所查标识"
        # 已注册标识清单也须出现在 message(供 AI 自愈);出厂为空即如实空
        for name in reg.names():
            assert name in msg


# ---------- TC-DET-07:只读形态(零物理动作/零新文件/无网络子进程) ----------

class TestDET07ReadOnly:
    def test_full_chain_no_physical_action_no_extra_files(
            self, estop, tmp_path, clock, som_probe, monkeypatch):
        rec = []

        def spy(name):
            def f(*a, **k):
                rec.append(name)
            return f
        for fn in ("mouseDown", "mouseUp", "moveTo", "click", "hscroll",
                   "scroll", "keyDown", "keyUp", "press", "hotkey", "typewrite"):
            monkeypatch.setattr(core_mod.pyautogui, fn, spy(fn), raising=False)

        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([[400, 400, 460, 440]]))
        ex._element_source = lambda hwnd: FakeElement(children=[])
        rec.clear()  # 构造期「启动抬键清扫」会调 3 次 mouseUp——清零后再计
        audit_root = tmp_path / "audit"
        before = {str(p.relative_to(audit_root))
                  for p in audit_root.rglob("*") if p.is_file()} \
            if audit_root.exists() else set()

        ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert rec == [], f"只读工具不得触发物理动作: {rec}"
        after = {str(p.relative_to(audit_root))
                 for p in audit_root.rglob("*") if p.is_file()}
        new_files = after - before
        assert len(new_files) == 1 and next(iter(new_files)).endswith(".png"), \
            "除标注图外零新文件"

    def test_detector_module_has_no_network_or_subprocess(self):
        """源码形态断言:检测器层无网络/子进程入口(截图不出本机 D-11)。"""
        src = (ROOT / "deskpilot" / "executor" / "detector.py").read_text(
            encoding="utf-8")
        for banned in ("socket", "urllib", "requests", "subprocess",
                       "Popen", "urlopen", "http"):
            assert banned not in src, f"detector.py 不应出现 {banned!r}"


# ---------- TC-DET-08:记忆化口径(装填失败记忆化 / 校验失败不记忆化) ----------

class TestDET08Memoization:
    def test_load_failure_memoized_but_verify_failure_not(
            self, estop, tmp_path, clock, som_probe):
        ex, _ = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])

        # --- ①装填失败**记忆化**:工厂先抛异常,第二次调用工厂零新增 ---
        load_calls = {"n": 0}

        def bad_factory():
            load_calls["n"] += 1
            raise RuntimeError("load boom")
        ex.detector_factory = bad_factory
        with pytest.raises(ExecutorError) as ei1:
            ex.get_clickable_map(FIXTURE_HWND, detect=True)
        assert ei1.value.code == DETECTOR_UNAVAILABLE
        assert load_calls["n"] == 1
        with pytest.raises(ExecutorError) as ei2:
            ex.get_clickable_map(FIXTURE_HWND, detect=True)
        assert ei2.value.code == DETECTOR_UNAVAILABLE
        assert load_calls["n"] == 1, "装填失败须记忆化:第二次不得再调工厂"

        # --- ②校验失败**不记忆化**:换不合清单失败一次,换回合法清单立即成功 ---
        ex2, detector2 = _executor(estop, tmp_path / "w2", clock, som_probe, [])
        ex2._element_source = lambda hwnd: FakeElement(children=[])
        # 先注入指向不存在文件的清单(校验失败)
        ex2.weight_manifest = {"ghost.onnx": _sha256(b"x")}
        with pytest.raises(ExecutorError) as ei3:
            ex2.get_clickable_map(FIXTURE_HWND, detect=True)
        assert ei3.value.code == DETECTOR_UNAVAILABLE
        assert detector2.calls == 0
        # 换回哈希相符的同一份 → 下一次调用立即成功(真 verify() 重跑给 ok)
        ex2.weight_manifest = {name: _sha256(d) for name, d in WEIGHT_FILES.items()}
        got = ex2.get_clickable_map(FIXTURE_HWND, detect=True)
        assert got["coord_space"] == "virtual_desktop", \
            "校验失败不记忆化:换上合法清单后须立即成功"


# ---------- TC-DET-09:detect 非布尔(bool 严格判定真实触发) ----------

class TestDET09DetectNonBool:
    @pytest.mark.parametrize("bad", [1, "yes", 0, "true"])
    def test_non_bool_detect_rejected_invalid_params(self, policy, bad):
        from deskpilot.errors import INVALID_PARAMS, InvalidParamsError
        with pytest.raises(InvalidParamsError) as ei:
            validate_call("get_clickable_map",
                          {"window": FIXTURE_HWND, "detect": bad}, policy)
        assert ei.value.code == INVALID_PARAMS


# ---------- TC-SOM-01/02/07:覆盖面 / 统一键集 / 排位稳定 ----------

def _tree_three_uia() -> FakeElement:
    """三条可交互 UIA 元素(阅读顺序按 top,left)。"""
    return FakeElement(children=[
        FakeElement(name="U1", automation_id="u1", rect=(120, 120, 170, 150)),
        FakeElement(name="U2", automation_id="u2", rect=(180, 120, 230, 150)),
        FakeElement(name="U3", automation_id="u3", rect=(120, 170, 170, 200)),
    ])


class TestSOM01CoverageUnion:
    """覆盖面 = UIA ∪ 检测:无重叠时 count == 5,两 source 各就其位。"""

    DETECT_VIRTUAL = [[400, 400, 460, 440], [520, 460, 580, 500]]

    def test_count_is_uia_plus_detect(self, estop, tmp_path, clock, som_probe):
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands(self.DETECT_VIRTUAL))
        ex._element_source = lambda hwnd: _tree_three_uia()

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert detector.calls == 1
        assert got["count"] == 5
        assert len(_uia_only_entries(got)) == 3
        assert len(_detect_entries(got)) == 2


class TestSOM02UnifiedKeySet:
    """每条键**恰好**为设计 §5.2 的统一键集;`id` 全局唯一连续;source 取值闭合。

    ISS-0066 ②契约修订(设计授权,单据 v0.2 备案):UIA 条目双写 som_id
    (与 id 同值,id 标废弃日程)→ UIA 恰**八**键;detect 条目编号不可寻址
    (只取 rect 用 click),不携 som_id → 仍恰七键。键集精确性断言精神
    不动(不多键、不缺键、按 source 分型钉死)。
    """

    UIA_KEYS = {"id", "som_id", "source", "name", "control_type",
                "automation_id", "rect", "confidence"}
    DETECT_KEYS = {"id", "source", "name", "control_type",
                   "automation_id", "rect", "confidence"}
    DETECT_VIRTUAL = [[400, 400, 460, 440], [520, 460, 580, 500]]

    def test_entries_exactly_seven_keys_and_ids_contiguous(
            self, estop, tmp_path, clock, som_probe):
        ex, _ = _executor(estop, tmp_path, clock, som_probe,
                          _cands(self.DETECT_VIRTUAL))
        ex._element_source = lambda hwnd: _tree_three_uia()

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert got["count"] == 5
        for e in got["entries"]:
            assert e["source"] in ("uia", "detect")
            want = self.UIA_KEYS if e["source"] == "uia" else self.DETECT_KEYS
            assert set(e) == want, f"键集不省略: {sorted(e)}"
            if e["source"] == "uia":
                assert e["som_id"] == e["id"]   # ISS-0066 ②:双写同值
        assert [e["id"] for e in got["entries"]] == [1, 2, 3, 4, 5]
        # UIA 恒 null confidence;detect 恒浮点
        for e in _uia_only_entries(got):
            assert e["confidence"] is None
        for e in _detect_entries(got):
            assert isinstance(e["confidence"], float)


class TestSOM07StableOrdering:
    """UIA 占 1..N(阅读顺序);检测占 N+1..N+M(top,left 坐标序);
    检测替身输出**刻意打乱**,编号仍确定;同一输入两次调用编号逐位一致。"""

    # 乱序给出:第二条坐标序应排最前
    DETECT_VIRTUAL_SHUFFLED = [[520, 460, 580, 500], [400, 400, 460, 440]]

    def _map_once(self, estop, tmp_path, clock, som_probe):
        ex, _ = _executor(estop, tmp_path, clock, som_probe,
                          _cands(self.DETECT_VIRTUAL_SHUFFLED))
        ex._element_source = lambda hwnd: _tree_three_uia()
        return ex.get_clickable_map(FIXTURE_HWND, detect=True)

    def test_detect_appended_after_uia_in_coord_order(
            self, estop, tmp_path, clock, som_probe):
        got = self._map_once(estop, tmp_path, clock, som_probe)
        entries = got["entries"]
        # UIA 1..3 阅读顺序;检测 4..5 按坐标序(400 在 520 前)
        assert [e["source"] for e in entries] == ["uia"] * 3 + ["detect"] * 2
        detect = _detect_entries(got)
        assert [e["rect"] for e in detect] == [
            [400, 400, 460, 440], [520, 460, 580, 500]], \
            "检测内部按 rect.top,rect.left 坐标序,与替身给出顺序无关"

    def test_same_input_same_numbering(self, estop, tmp_path, clock, som_probe):
        # 同一 Executor、同一输入连调两次,编号须逐位一致
        ex, _ = _executor(estop, tmp_path, clock, som_probe,
                          _cands(self.DETECT_VIRTUAL_SHUFFLED))
        ex._element_source = lambda hwnd: _tree_three_uia()
        a = ex.get_clickable_map(FIXTURE_HWND, detect=True)
        b = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        def sig(g):
            return [(e["id"], e["source"], e["rect"]) for e in g["entries"]]
        assert sig(a) == sig(b), "同一输入两次调用编号须逐位一致"


# ---------- TC-SOM-03:图上逐条标注(UIA 与检测同一套画法) ----------

class TestSOM03AnnotatedPixels:
    """落图后读 PNG 像素:逐条该条 rect 的**图内**矩形边界上存在 outline 色
    (255,60,60) 像素;命中条数 == `count`。"""

    OUTLINE = (255, 60, 60)
    DETECT_VIRTUAL = [[400, 400, 460, 440], [520, 460, 580, 500]]

    def _border_has_outline(self, img, rel) -> bool:
        """该条 rect 的**图内矩形边界带**上是否存在 outline 色像素。

        PIL `rectangle(width=3)` 的描边以 rect 边界为带(具体骑缝/内收随版本),
        故采样带取边界内外各 1px + 向内 3px,只扫**边界带**不扫内部——断言目标
        不变(「边界上存在 outline 色 (255,60,60)」,详设 §9.6 同一套画法)。
        """
        l, t, r, b = rel
        w, h = img.size
        px = img.load()
        band = 4
        for y in range(max(0, t - 1), min(h, b + 1)):
            for x in range(max(0, l - 1), min(w, r + 1)):
                near_border = (x - l < band or r - 1 - x < band
                               or y - t < band or b - 1 - y < band)
                if near_border and px[x, y][:3] == self.OUTLINE:
                    return True
        return False

    def test_each_entry_annotated_on_image(
            self, estop, tmp_path, clock, som_probe):
        ex, _ = _executor(estop, tmp_path, clock, som_probe,
                          _cands(self.DETECT_VIRTUAL))
        ex._element_source = lambda hwnd: _tree_three_uia()

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        img = Image.open(got["path"]).convert("RGB")
        wl, wt = ORIGIN  # 图内坐标 = 虚拟屏坐标 - 原点
        hits = 0
        for e in got["entries"]:
            l, t, r, b = e["rect"]
            rel = [l - wl, t - wt, r - wl, b - wt]
            if self._border_has_outline(img, rel):
                hits += 1
        assert hits == got["count"], \
            f"图上标注条数({hits})须 == count({got['count']}),UIA 与检测同一套画法"


# ---------- TC-SOM-04/04b:detect 编号误用 → 指引级错误(零点击) ----------

class TestSOM04DetectIdMisuse:
    """`click_element(som_id=<detect 编号>)` → `ELEMENT_UNSUPPORTED` + 指引;
    **零点击**;指引**不得**含「请重新调用 get_clickable_map 取图」(D-14)。"""

    DETECT_VIRTUAL = [[400, 400, 460, 440], [520, 460, 580, 500]]

    def _map_with_detect(self, estop, tmp_path, clock, som_probe):
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands(self.DETECT_VIRTUAL))
        tree = _tree_three_uia()
        ex._element_source = lambda hwnd: tree
        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)
        detect_id = _detect_entries(got)[0]["id"]
        return ex, detect_id, tree

    def test_detect_som_id_click_returns_unsupported_guidance(
            self, estop, tmp_path, clock, som_probe, monkeypatch):
        ex, detect_id, tree = self._map_with_detect(
            estop, tmp_path, clock, som_probe)
        clicks = []
        monkeypatch.setattr(core_mod.pyautogui, "click",
                            lambda *a, **k: clicks.append((a, k)),
                            raising=False)
        # 零点击的最强绊线:分支②须在 `_element_root` **之前**返回(§5.3),
        # 故取图后换掉 `_element_source` 并计数——误用点击不得再触达它
        root_calls = {"n": 0}

        def counting_source(hwnd):
            root_calls["n"] += 1
            return tree
        ex._element_source = counting_source

        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element",
                        "params": {"som_id": detect_id},
                        "binding_hwnd": FIXTURE_HWND})

        assert ei.value.code == ELEMENT_UNSUPPORTED
        msg = ei.value.message
        assert "detect" in msg, "须含 source=\"detect\" 语义"
        assert "rect" in msg and "click" in msg, \
            "须指引:取该条 rect 用 click 坐标点击"
        assert clicks == [] and root_calls["n"] == 0, \
            "零点击保证(§5.3):不触 pyautogui,也不再进 _element_root"

    def test_guidance_must_not_mislead(self, estop, tmp_path, clock, som_probe):
        ex, detect_id, _ = self._map_with_detect(estop, tmp_path, clock,
                                                 som_probe)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element",
                        "params": {"som_id": detect_id},
                        "binding_hwnd": FIXTURE_HWND})
        assert "请重新调用 get_clickable_map 取图" not in ei.value.message, \
            "对 detect 编号,该指引会致 AI 循环(D-14),须禁"


# ---------- TC-SOM-05:重叠去重(中心点落入 UIA 矩形即不进编号空间) ----------

class TestSOM05OverlapDedup:
    def test_candidate_center_inside_uia_rect_dropped(
            self, estop, tmp_path, clock, som_probe):
        # 候选中心 (145,135) 落在 U1(120,120,170,150) 内
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([[120, 120, 170, 150]]))
        ex._element_source = lambda hwnd: _tree_three_uia()

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert detector.calls == 1
        assert got["count"] == 3, "重叠候选不进编号空间,只剩 3 条 UIA"
        assert _detect_entries(got) == []


# ---------- TC-SOM-08:越界坐标非错误(如实保留,工具不做二次裁剪) ----------

class TestSOM08OutOfBoundsKept:
    def test_out_of_screenshot_rect_kept_verbatim(
            self, estop, tmp_path, clock, som_probe):
        # 候选越出截图区域(截图宽 700,候选 rect 远超)
        far = [9000, 9000, 9100, 9050]
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([far]))
        ex._element_source = lambda hwnd: FakeElement(children=[])

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        detect = _detect_entries(got)
        assert len(detect) == 1, "越界非错误,须如实保留(判断归 AI)"
        assert detect[0]["rect"] == far, "rect 原样,不做二次裁剪"


# ---------- TC-CACHE-01/03/05:两份缓存整表替换 ----------

class TestCacheReplace:
    """每次取图**整表替换**(ISS-0081 口径):扩容/缩容/detect 表同口径。

    树形态设计(R7 防假绿):A/B 两树**槽位同矩形、名字不同**——若缓存未整表
    替换,点击会拿旧名去解析新树(失配)或命中残留编号,断言的元素名/错误码
    立即对不上;若实现正确,编号同位不同名,逐一点击须命中**新表**元素。
    """

    SLOTS = [(120, 120, 170, 150), (180, 120, 230, 150),
             (120, 170, 170, 200), (180, 170, 230, 200),
             (120, 220, 170, 250)]

    def _tree(self, names) -> FakeElement:
        return FakeElement(children=[
            FakeElement(name=n, automation_id=n, rect=r)
            for n, r in zip(names, self.SLOTS)])

    def test_expand_then_click_new_id_hits_b(self, estop, tmp_path, clock,
                                             som_probe):
        """TC-CACHE-01 扩容:取图 A(3 元素)→取图 B(5 元素);用 **B 的第 5 号**
        点击 → 命中 B 的第 5 个元素(该编号在 A 中不存在)。"""
        ex, detector = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: self._tree(["A1", "A2", "A3"])
        map_a = ex.get_clickable_map(FIXTURE_HWND, detect=True)
        assert map_a["count"] == 3

        ex._element_source = lambda hwnd: self._tree(
            ["B1", "B2", "B3", "B4", "B5"])
        map_b = ex.get_clickable_map(FIXTURE_HWND, detect=True)
        assert map_b["count"] == 5

        r = ex.execute({"tool": "click_element", "params": {"som_id": 5},
                        "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert r["element"]["name"] == "B5"

    def test_shrink_then_new_table_in_effect(self, estop, tmp_path, clock,
                                             som_probe):
        """TC-CACHE-03 缩容后新表生效:A(5)→B(3);用 1~3 逐个点击 →
        命中 **B** 的对应元素(元素名是 B 系而非 A 系,即证非旧表)。"""
        ex, detector = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: self._tree(
            ["A1", "A2", "A3", "A4", "A5"])
        ex.get_clickable_map(FIXTURE_HWND, detect=True)

        ex._element_source = lambda hwnd: self._tree(["B1", "B2", "B3"])
        ex.get_clickable_map(FIXTURE_HWND, detect=True)

        names = []
        for som_id in (1, 2, 3):
            r = ex.execute({"tool": "click_element",
                            "params": {"som_id": som_id},
                            "binding_hwnd": FIXTURE_HWND})
            assert r["status"] == "ok"
            names.append(r["element"]["name"])
        assert names == ["B1", "B2", "B3"]

    def test_detect_table_same_replace_semantics(self, estop, tmp_path, clock,
                                                 som_probe):
        """TC-CACHE-05:`detect=True` 取图(含检测编号)→ 再 `detect=False` 取图;
        上一次的 detect 编号**不再命中**,落 `ELEMENT_NOT_FOUND`(detect 表
        被整表替换为空,无跨次残留面)。"""
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([[400, 400, 460, 440],
                                         [520, 460, 580, 500]]))
        ex._element_source = lambda hwnd: _tree_three_uia()
        map_a = ex.get_clickable_map(FIXTURE_HWND, detect=True)
        detect_id = _detect_entries(map_a)[0]["id"]
        # 再 detect=False 取图(detect 表整表替换为空)
        ex.get_clickable_map(FIXTURE_HWND, detect=False)

        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element",
                        "params": {"som_id": detect_id},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == ELEMENT_NOT_FOUND, \
            "detect 表整表替换为空,旧 detect 编号不得跨次残留"


# ---------- TC-CLK-01:过期边界(恰好 60.0 仍有效,越过即失效) ----------

class TestCLK01ExpiryBoundary:
    def test_exactly_expires_still_valid_then_invalid(
            self, estop, tmp_path, clock, som_probe):
        ex, _ = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: _tree_three_uia()
        ex.get_clickable_map(FIXTURE_HWND)  # detect=False,1..3 号

        # 恰好推进 60.0:判据 `now > expires`,故**仍有效**
        clock.advance(60.0)
        r = ex.execute({"tool": "click_element", "params": {"som_id": 1},
                        "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok", "恰好等于 expires 时刻仍有效(判据 now>expires)"

        # 再推 1 单位 → 失效
        clock.advance(1.0)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element", "params": {"som_id": 1},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == ELEMENT_NOT_FOUND


# ---------- TC-GOV-01a/01b:描述面(互相指引,两路点击分野) ----------

class TestGOV01Descriptions:
    def test_get_clickable_map_description(self):
        d = TOOL_SCHEMAS["get_clickable_map"]["description"]
        assert len(d) <= 200
        assert any(w in d for w in ("Windows", "桌面", "窗口", "浏览器")), \
            "须含领域限定词"
        assert "detect" in d, "须含 detect 开关语义"
        assert "source" in d, "须含 source 两值语义"
        # 两路点击分野:detect 编号不可传 som_id,须取 rect 走坐标点击
        assert "som_id" in d and "rect" in d, \
            "须含两路点击分野(detect 编号取其 rect 走 click)"

    def test_click_element_description(self):
        d = TOOL_SCHEMAS["click_element"]["description"]
        assert len(d) <= 200
        # 同向指引:为何 som_id 点不了 detect 编号
        assert "detect" in d or "图形" in d, \
            "须含同向指引(som_id 为何点不了 detect 编号)"


# ---------- TC-GOV-02:L0 分级 / 无新审批路径 ----------

class TestGOV02L0NoApprovalPath:
    def test_l0_direct_and_no_enforcement_submit(
            self, estop, tmp_path, clock, som_probe, ctx):
        from deskpilot.models import TOOL_LEVELS
        assert TOOL_LEVELS["get_clickable_map"] == "L0"
        assert "get_clickable_map" in _L0_DIRECT

        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([[400, 400, 460, 440]]))
        ex._element_source = lambda hwnd: _tree_three_uia()
        sensing_ctx = _sensing_ctx(ctx, ex)
        # 记录 enforcement.submit
        submits = []
        orig = ctx.enforcement.submit

        def recording_submit(*a, **k):
            submits.append(a)
            return orig(*a, **k)
        ctx.enforcement.submit = recording_submit

        r = call_tool(sensing_ctx, "get_clickable_map",
                      {"window": FIXTURE_HWND, "detect": True})
        # R7:`r.ok` 单独不足以证「检测通道真跑了」——_run_sensing 若丢 detect,
        # 走缺省路径也返回 ok。故断**透传终效应**:检测器被调 + 返回体带
        # coord_space + 检测条目出现,三者合起来才证 detect 真正到达执行层。
        assert r.ok, f"L0 直调须成功: {r.message}"
        assert detector.calls == 1, \
            "detect=True 须经 _run_sensing 透传到执行层(tools/__init__.py 不得丢参)"
        assert (r.data or {}).get("coord_space") == "virtual_desktop"
        assert submits == [], "L0 不走闸一/闸二,enforcement.submit 零调用"


# ---------- TC-GOV-03a:预算登记单源(覆盖优先于级别表) ----------

class TestGOV03BudgetSingleSource:
    def test_override_registered_and_resolve_budget_uses_it(self, policy):
        from deskpilot.httpd import resolve_budget
        from deskpilot.models import TOOL_BUDGET_OVERRIDES
        assert "get_clickable_map" in TOOL_BUDGET_OVERRIDES, \
            "预算覆盖表须含 get_clickable_map(R4 ③ +1 条目,数字待 R-04)"
        # 覆盖优先于级别表:取覆盖值,而非 L0 的 5.0
        assert resolve_budget("get_clickable_map", "L0", policy) == \
            TOOL_BUDGET_OVERRIDES["get_clickable_map"]
        # 既有覆盖不受影响
        assert resolve_budget("ocr", "L0", policy) == 12.0
        assert resolve_budget("screenshot", "L0", policy) == 12.0
        assert resolve_budget("find_window", "L0", policy) == 5.0


# ---------- TC-GOV-04:三条错误路径均含下一步(AI 可自愈) ----------

class TestGOV04ErrorsActionable:
    """五条错误路径的 message 均含**可执行的下一步**与诊断要素。"""

    def _expect_unavailable(self, ex, *must_contain):
        with pytest.raises(ExecutorError) as ei:
            ex.get_clickable_map(FIXTURE_HWND, detect=True)
        assert ei.value.code == DETECTOR_UNAVAILABLE
        # GOV-04:五条的 message **均含**可执行的下一步(措辞为单源标记「下一步」)
        assert "下一步" in ei.value.message, "GOV-04:message 须含可执行的下一步"
        for needle in must_contain:
            assert needle in ei.value.message, f"message 缺诊断要素: {needle!r}"
        return ei.value.message

    def test_dir_missing_has_next_step(self, estop, tmp_path, clock, som_probe):
        # 权重目录**经构造参数**(公开入口)指向不存在目录;两装配位照常注入
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      wait_timeout_max=5.0, clock=clock, probe=som_probe,
                      detector_weights_dir=str(tmp_path / "no_such_dir"))
        ex._shot_fn = lambda region: Image.new("RGB", (700, 500), "white")
        ex.weight_manifest = {n: _sha256(d) for n, d in WEIGHT_FILES.items()}
        ex.detector_factory = lambda: FakeDetector([])
        ex._element_source = lambda hwnd: FakeElement(children=[])
        self._expect_unavailable(ex, str(tmp_path / "no_such_dir"))

    def test_file_missing_has_next_step(self, estop, tmp_path, clock, som_probe):
        ex, detector = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])
        ex.weight_manifest = {"ghost.onnx": _sha256(b"x")}
        self._expect_unavailable(ex, "ghost.onnx")

    def test_hash_mismatch_has_next_step(self, estop, tmp_path, clock, som_probe):
        ex, detector = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])
        ex.weight_manifest = {name: "0" * 64 for name in WEIGHT_FILES}
        self._expect_unavailable(ex, "0" * 64, _sha256(WEIGHT_FILES["model.onnx"]))

    def test_load_failure_has_exception_text(self, estop, tmp_path, clock,
                                             som_probe):
        ex, _ = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])
        ex.detector_factory = lambda: (_ for _ in ()).throw(
            RuntimeError("load boom text"))
        self._expect_unavailable(ex, "load boom text")

    def test_inference_failure_has_exception_text(self, estop, tmp_path, clock,
                                                  som_probe):
        ex, _ = _executor(estop, tmp_path, clock, som_probe, [])
        ex._element_source = lambda hwnd: FakeElement(children=[])

        def exploding(image):
            raise RuntimeError("inference boom text")
        ex.detector_factory = lambda: exploding
        self._expect_unavailable(ex, "inference boom text")


# ---------- TC-SOM-10:容器类节点不进判据集合(D-20) ----------

class TestSOM10ContainersDoNotDedup:
    """TC-SOM-10(D-20,2026-09-15 裁定):判据集合 = 枚举全量**减结构容器**。

    两臂同断,防借道假绿:
      ①整窗 Pane(容器)覆盖全区,落在其上而不在任何元素上的候选**须存活**
        ——若容器进判据集,本条必红(TC-INT-02 在真机上即是这么死的);
      ②落在真实元素(Button)上的候选**仍被去重**——D-17 语义不回退。
    """

    def test_container_does_not_blanket_but_element_dedups(
            self, estop, tmp_path, clock, som_probe):
        # 树:根 = PaneControl 盖住整窗(模拟西柚/画图容器的毯式矩形),
        # 内含一个真实可点 Button(300,300,360,340)
        root = FakeElement(control_type="PaneControl", rect=FIXTURE_RECT,
                           children=[FakeElement(name="BTN",
                                                 rect=(300, 300, 360, 340))])
        # 候选:c1 中心落在 Button 内;c2 落在窗口空白区(只在 Pane 上)
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([[310, 310, 350, 330],     # c1 → Button 内
                                         [500, 500, 560, 540]]))   # c2 → 仅 Pane 上
        ex._element_source = lambda hwnd: root

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        # ①c2 存活:检测通道有且仅有它一条(容器不毯式去重)
        detect = [e for e in got["entries"] if e["source"] == "detect"]
        assert [e["rect"] for e in detect] == [[500, 500, 560, 540]], \
            "整窗 Pane(容器)不得把候选毯式去重(D-20)"
        # ②c1 被 Button 去重:entries 里没有 rect==c1 的检测条目(D-17 不回退)
        assert [310, 310, 350, 330] not in [e["rect"] for e in detect]
        # 编号空间 = 根 Pane + Button + c2。**注意**:根节点 enabled 且非退化,
        # 既有编号行为会把它编为 1 号(编号空间不过滤容器——容器豁免只在
        # **判据集合**侧,D-20;编号侧行为既有不动)
        assert got["count"] == 3
        assert [e["source"] for e in got["entries"]] == ["uia", "uia", "detect"]


class TestSOM10CustomControlHosting:
    """TC-SOM-10 增补臂(D-20 补充):宿主型 CustomControl(XAML 承载根)
    不进判据集;叶子型 CustomControl(真自绘控件)保留——其上候选仍去重。

    实证出处:画图/Windows Terminal 的内容区都是 CustomControl 毯盖全窗
    (2026-09-15 TC-INT-02 二段追踪:`CustomControl (8,31,1912,1034)`)。
    """

    def test_host_custom_control_excluded_leaf_kept(
            self, estop, tmp_path, clock, som_probe):
        # 树:根 Pane(全窗) → 宿主 CustomControl(300,100,600,300) 内含
        # 一个 Button(320,120,360,150);另有一叶子 CustomControl(500,400,560,450)
        host = FakeElement(control_type="CustomControl",
                           rect=(300, 100, 600, 300),
                           children=[FakeElement(name="BTN",
                                                 rect=(320, 120, 360, 150))])
        leaf = FakeElement(control_type="CustomControl",
                           rect=(500, 400, 560, 450), name="LEAF")
        root = FakeElement(control_type="PaneControl", rect=FIXTURE_RECT,
                           children=[host, leaf])
        ex, detector = _executor(estop, tmp_path, clock, som_probe,
                                 _cands([[320, 120, 360, 150],   # 落 Button 上
                                         [400, 200, 460, 240],   # 仅宿主上
                                         [500, 400, 560, 450]]))  # 落叶子上
        ex._element_source = lambda hwnd: root

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        detect = [e for e in got["entries"] if e["source"] == "detect"]
        rects = [e["rect"] for e in detect]
        # ①宿主上的候选存活(宿主 CustomControl 不毯式去重)
        assert [400, 200, 460, 240] in rects, "宿主 CustomControl 须被排除(D-20 补充)"
        # ②叶子上的候选被去重(真自绘控件仍受 UIA 优先保护,防双编号)
        assert [500, 400, 560, 450] not in rects, "叶子 CustomControl 须保留在判据集"
        # ③Button 上的候选被去重(D-17 不回退)
        assert [320, 120, 360, 150] not in rects
