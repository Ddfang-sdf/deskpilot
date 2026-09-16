"""ISS-0081 单元测试：SoM 编号缓存只写不清，短清单残留旧编号。

入口：Executor 公开方法 get_clickable_map / execute（som_id 点击路径）。
断言值来源（全部为公开出口产出，无私有状态读取）：
  · `get_clickable_map` 的返回值 count / entries（id、name、rect）；
  · `execute` 的返回值 status / element；
  · `ExecutorError` 的 code / message；
  · 元素替身的 invoked 计数（点击终效应 R5）。

用例来源：ISS-0081 §4 验收用例 1~4（红→绿）。

**R7 失效原因判别（本文件的判别手段）**

本单两条失效原因的**异常码相同**（`ELEMENT_NOT_FOUND`），只能靠 message 分：
  · 缓存分支（`_click_element` 校验不过）→ 含取图指引 `get_clickable_map`；
  · 元素分支（`_resolve_unique_element` 无匹配）→ 含 `候选元素` 列表。
两者都是设计文档面向 AI 的既定文本（前者为 ISS-0081 §4 明文要求的"取图指引"，
后者自 ISS-0042 起为使 AI 一轮自诊断而设），故断言 message 属公开出口断言，
不构成"断言无出处"。`_reason()` 即此判别的唯一实现，供各用例复用。

**P2 修订（据实记录）**：本文件初稿曾以 `sorted(ex._som_cache)` 键集区分两条
同码原因（读 Executor 内部状态）。经核对，公开出口的 message 已足以判别，
且读内部状态会把测试绑死在缓存的**数据结构**上（换实现即假失败），
故私有状态读取已全部移除，改为 `_reason()`；同时
test_stale_id_refused_when_element_gone 由"守卫"转为真红。
"""

from __future__ import annotations

import pytest
from PIL import Image

from deskpilot.errors import ELEMENT_NOT_FOUND, ExecutorError
from deskpilot.executor.core import Executor

from .conftest import (FIXTURE_HWND, FIXTURE_HWND_B, FIXTURE_RECT,
                       FIXTURE_RECT_B, FakeProbe)
from .test_elements import FakeElement


# ---------- 失效原因判别（只读公开出口） ----------

CACHE_STALE = "cache_stale"
ELEMENT_MISSING = "element_missing"


def _reason(ei) -> str:
    """从公开异常上判别失效原因：缓存作废 / 元素侧无匹配。

    缓存分支的 message 含取图指引（本单 §4 要求）；
    元素分支的 message 含候选元素列表。两者异常码相同，故必须分。
    """
    if "get_clickable_map" in ei.value.message:
        return CACHE_STALE
    if "候选元素" in ei.value.message:
        return ELEMENT_MISSING
    return "other"


def _expect_refusal(ex, som_id, *, reason=CACHE_STALE, hwnd=FIXTURE_HWND) -> None:
    """断言一次 som_id 点击被拒，且拒绝原因恰为 reason。"""
    with pytest.raises(ExecutorError) as ei:
        ex.execute({"tool": "click_element", "params": {"som_id": som_id},
                    "binding_hwnd": hwnd})
    assert ei.value.code == ELEMENT_NOT_FOUND
    assert _reason(ei) == reason


# ---------- 树布置 ----------

def _tree_a() -> FakeElement:
    """取图 A 的树：5 个可交互元素。

    阅读顺序（按 rect 的 top, left 排序）：
      1 文件 / 2 编辑 / 3 保存 / 4 打印 / 5 导出
    末尾的「灰_隐藏」「零_消失」不可交互，不入表、不占编号。
    """
    return FakeElement(children=[
        FakeElement(name="文件", rect=(110, 110, 160, 140)),
        FakeElement(name="编辑", rect=(170, 110, 220, 140)),
        FakeElement(name="保存", automation_id="save", rect=(110, 160, 160, 190)),
        FakeElement(name="打印", rect=(170, 160, 220, 190)),
        FakeElement(name="导出", automation_id="export", rect=(110, 210, 160, 240)),
        FakeElement(name="灰_隐藏", enabled=False, rect=(200, 210, 240, 240)),
        FakeElement(name="零_消失", rect=(0, 0, 0, 0)),
    ])


def _tree_b() -> FakeElement:
    """取图 B 的树：3 个可交互元素，阅读顺序与 A **整体重排**。

      B 阅读顺序：1 文件 / 2 保存 / 3 编辑
      A 阅读顺序：1 文件 / 2 编辑 / 3 保存
    同名元素换号：A 的 3 号是「保存」，B 的 3 号是「编辑」。

    「打印」「导出」**仍在树上但零面积**——不在本次可交互集合内（故不入 B 的 1..3），
    却仍能被名称解析命中、仍可 Invoke。这正是 ISS-0081 §1 触发链第 5 步的形态：
    旧编号 4/5 解析成功 → 真的点到 → 报 ok。本形态使"缓存未整表替换"与
    "元素不存在"两种失效原因可被分开（前者修复后 message 含取图指引）。
    """
    return FakeElement(children=[
        FakeElement(name="文件", rect=(110, 110, 160, 140)),
        FakeElement(name="保存", automation_id="save", rect=(110, 160, 160, 190)),
        FakeElement(name="编辑", rect=(110, 210, 160, 240)),
        FakeElement(name="打印", rect=(0, 0, 0, 0)),
        FakeElement(name="导出", automation_id="export", rect=(0, 0, 0, 0)),
    ])


def _tree_b_disabled_old() -> FakeElement:
    """取图 B 的树，另一形态：「打印」「导出」**被禁用**（非零面积）。

    过滤路径换成 enabled（而非零面积），且 _resolve_unique_element 会走到
    ELEMENT_DISABLED 分支——即令缓存未清，旧编号也点不到，错误码与"修好了"
    看齐。本形态用来核对：拒绝必须来自**缓存作废**（ELEMENT_NOT_FOUND +
    取图指引），不得被 enabled 过滤器顺手掩盖（否则缓存缺陷被掩盖）。
    """
    return FakeElement(children=[
        FakeElement(name="文件", rect=(110, 110, 160, 140)),
        FakeElement(name="保存", automation_id="save", rect=(110, 160, 160, 190)),
        FakeElement(name="编辑", rect=(110, 210, 160, 240)),
        FakeElement(name="打印", enabled=False, rect=(170, 160, 220, 190)),
        FakeElement(name="导出", enabled=False, rect=(170, 210, 220, 240)),
    ])


def _tree_b_without_old() -> FakeElement:
    """取图 B 的树：3 个可交互元素，且 A 的 4/5 号**已从树上删除**。

    修复前：缓存命中（hwnd 一致、未过期）→ 元素侧无匹配 → message 为「元素不存在」。
    修复后：缓存校验直接拒 → message 含取图指引。
    异常码相同而 message 不同，故本例可判定"编号是否真的被缓存作废"。
    """
    return FakeElement(children=[
        FakeElement(name="文件", rect=(110, 110, 160, 140)),
        FakeElement(name="保存", automation_id="save", rect=(110, 160, 160, 190)),
        FakeElement(name="编辑", rect=(110, 210, 160, 240)),
    ])


# ---------- 夹具与工具 ----------

@pytest.fixture
def som_probe() -> FakeProbe:
    """绑定窗口矩形探针（Executor 的 probe 接缝，同 test_m3 布置）。"""
    p = FakeProbe()
    p.rects = {FIXTURE_HWND: FIXTURE_RECT, FIXTURE_HWND_B: FIXTURE_RECT_B}
    return p


@pytest.fixture
def som_executor(estop, tmp_path, clock, som_probe):
    """SoM 场景执行器：真 Executor + 假时钟/假探针；截图与元素源接缝就地布置。"""
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  wait_timeout_max=5.0, clock=clock, probe=som_probe)
    ex._shot_fn = lambda region: Image.new("RGB", (700, 500), "white")
    return ex


def _bind(ex, tree: FakeElement) -> None:
    """把元素源绑到**同一个树实例**（不每次现做），否则点击的终效应
    落在无人持有的节点上，invoked 计数不可观测。"""
    ex._element_source = lambda hwnd: tree


def _take_map(ex, tree: FakeElement) -> dict:
    """取图一次：先绑定本次的树，再取图；返回取图响应。"""
    _bind(ex, tree)
    return ex.get_clickable_map(FIXTURE_HWND)


def _invoked(tree: FakeElement) -> list[int]:
    """树内全部节点的 Invoke 计数（终效应直出）。"""
    return [n.invoked for n in tree.GetChildren()]


def _names(tree: FakeElement) -> list[str]:
    return [n.Name for n in tree.GetChildren()]


def _click(ex, som_id, *, hwnd=FIXTURE_HWND) -> dict:
    return ex.execute({"tool": "click_element", "params": {"som_id": som_id},
                       "binding_hwnd": hwnd})


# ---------- ISS-0081 §4 用例 1~3：编号的生命周期是「单次取图」 ----------

class TestSomCacheReset:

    def test_shorter_map_stale_id_refused_by_cache(self, som_executor):
        """用例 2（核心缺陷）：A(5) → B(3) → 用 B **未给出**的编号 4 点击 →
        显式 ELEMENT_NOT_FOUND（含取图指引），**零点击**。

        B 树里「打印」仍在（零面积，故不在本次可交互集合内 = 本次未给出 4 号），
        且名称仍可解析。修复前：缓存校验过 → 元素解析成功 → **真的点到并报 ok**
        （本用例以 DID NOT RAISE 红）。修复后：缓存校验直接拒，
        且 message 必须含取图指引（= 判为缓存作废，而非元素侧无匹配）。
        """
        _take_map(som_executor, _tree_a())
        tree_b = _tree_b()
        r = _take_map(som_executor, tree_b)
        assert r["count"] == 3
        assert "打印" in _names(tree_b)          # 目标仍在树上，排除"元素不存在"借道

        _expect_refusal(som_executor, 4, reason=CACHE_STALE)
        assert _invoked(tree_b) == [0, 0, 0, 0, 0]

    def test_shorter_map_remaining_ids_hit_new_tree(self, som_executor):
        """用例 3：A(5) → B(3) → 编号 1~3 命中 B 对应元素，
        编号 4/5 **按缓存作废拒绝且零点击**。

        一正一反锁死"编号域 = 本次清单"：4/5 号在 B 树上是零面积
        （不可交互、名称仍可解析），修复前会被点到并报 ok（本用例红）；
        修复后拒绝原因必须是缓存作废。
        """
        _take_map(som_executor, _tree_a())
        tree_b = _tree_b()
        r = _take_map(som_executor, tree_b)
        assert [e["name"] for e in r["entries"]] == ["文件", "保存", "编辑"]

        for som_id in (1, 2, 3):
            assert _click(som_executor, som_id)["status"] == "ok"
        assert _invoked(tree_b) == [1, 1, 1, 0, 0]      # 打印、导出零点击

        for som_id in (4, 5):
            _expect_refusal(som_executor, som_id, reason=CACHE_STALE)
        assert _invoked(tree_b) == [1, 1, 1, 0, 0]

    def test_all_ids_above_count_refused_by_cache(self, som_executor):
        """A(5) → B(3)：count 之上的**每一个**编号都按缓存作废拒绝。

        等价于"编号域恰为 1..count(B)"这一条完整性断言，但在公开出口上完成：
        逐个编号核对，任何一个落到元素侧（message 为「元素不存在」）都算失败。
        """
        _take_map(som_executor, _tree_a())
        r = _take_map(som_executor, _tree_b())
        assert r["count"] == 3

        for som_id in range(r["count"] + 1, 6):
            _expect_refusal(som_executor, som_id, reason=CACHE_STALE)

    def test_map_shrinks_then_new_ids_hit_new_tree(self, som_executor):
        """用例 1（守卫）：A(5) → B(3) → 用 B 给出的编号 1~3 → 命中 B 的元素。

        B 的 3 号是「编辑」，A 的 3 号是「保存」——编号含义已整体重排。
        编号 ≤ count(B) 的部分因缓存逐键覆盖而在修复前后都对，故本例 PASS
        属预期（非红）；其价值是锁住新编号域 1..count(B) 的语义不被写坏
        （例如改成"先清后建"或"惰性重建"时把 1..count 写错）。
        缺陷本体由编号 > count(B) 的各条覆盖。
        """
        _take_map(som_executor, _tree_a())
        tree_b = _tree_b()
        r = _take_map(som_executor, tree_b)

        assert r["count"] == 3
        assert [e["id"] for e in r["entries"]] == [1, 2, 3]

        hit = []
        for som_id in (1, 2, 3):
            got = _click(som_executor, som_id)
            assert got["status"] == "ok"
            hit.append(got["element"]["name"])
        assert hit == ["文件", "保存", "编辑"]
        assert _invoked(tree_b)[:3] == [1, 1, 1]


# ---------- ISS-0081 §4 用例 4：既有失效语义是回归项 ----------

class TestSomCacheRegression:

    def test_expiry_unchanged(self, som_executor, clock):
        """A → 推进 61s → 任意编号 → 既有过期拒绝不变（仍为缓存分支）。"""
        _take_map(som_executor, _tree_a())
        clock.advance(61)
        _expect_refusal(som_executor, 1, reason=CACHE_STALE)

    def test_cross_window_unchanged(self, som_executor):
        """A → 换绑定窗 B → 任意编号 → 既有跨窗拒绝不变（仍为缓存分支）。"""
        _take_map(som_executor, _tree_a())
        _expect_refusal(som_executor, 1, reason=CACHE_STALE, hwnd=FIXTURE_HWND_B)

    def test_single_map_unchanged(self, som_executor):
        """只取图一次 → 全部编号可用（整表替换不得误伤单次取图场景）。"""
        tree_a = _tree_a()
        r = _take_map(som_executor, tree_a)
        assert r["count"] == 5

        got = _click(som_executor, 3)
        assert got["status"] == "ok"
        assert got["element"]["name"] == "保存"
        assert _invoked(tree_a) == [0, 0, 1, 0, 0, 0, 0]

    def test_non_interactable_never_numbered(self, som_executor):
        """取图基本契约（回归）：禁用/零面积节点不入表、不占编号。"""
        r = _take_map(som_executor, _tree_a())
        assert r["count"] == 5
        assert [e["name"] for e in r["entries"]] == \
            ["文件", "编辑", "保存", "打印", "导出"]
        for e in r["entries"]:
            l, t, rr, b = e["rect"]
            assert FIXTURE_RECT[0] <= l and FIXTURE_RECT[1] <= t
            assert rr <= FIXTURE_RECT[2] and b <= FIXTURE_RECT[3]


# ---------- R7 失效原因核对：把「缓存作废」与「元素侧无匹配」分开 ----------

class TestFailureReasonSplit:
    """两条原因的异常码同为 ELEMENT_NOT_FOUND，必须逐条核对是哪一条在起作用。

    判别手段 = `_reason()`（公开异常 message）。用例各自的判别点写在 docstring。
    """

    def test_stale_id_refused_when_element_gone(self, som_executor):
        """A(5) → B(3，且 A 的 4/5 号**已从树上删除**）→ 编号 4 →
        拒绝原因必须是**缓存作废**，不是「元素不存在」。

        修复前：缓存命中（hwnd 一致、未过期）→ 元素侧无匹配 →
        message 为「元素不存在」（同码，本用例红）。
        修复后：缓存校验先拒 → message 含取图指引。
        本例与 test_shorter_map_stale_id_refused_by_cache 配对，
        分别覆盖"旧目标仍在树上"与"旧目标已不在树上"两种旧表残留形态：
        两例都必须由**缓存**判拒，否则说明编号从未真正作废。
        """
        _take_map(som_executor, _tree_a())
        tree_bp = _tree_b_without_old()
        r = _take_map(som_executor, tree_bp)
        assert r["count"] == 3

        _expect_refusal(som_executor, 4, reason=CACHE_STALE)
        assert _invoked(tree_bp) == [0, 0, 0]

    def test_disabled_old_target_refused_by_cache_not_by_enabled(self, som_executor):
        """A(5) → B(3，「打印/导出」被禁用）→ 编号 4 → 拒绝原因必须是**缓存作废**。

        过滤路径换成 enabled 后，修复前旧编号会先被 _resolve_unique_element 的
        禁用检查挡住（ELEMENT_DISABLED）——也没点到、码也像个失败，看似"已修好"。
        本用例要求恰为 ELEMENT_NOT_FOUND + 取图指引：编号作废是**缓存**的职责，
        不许被 enabled 过滤器顺手掩盖。
        """
        _take_map(som_executor, _tree_a())
        tree_bd = _tree_b_disabled_old()
        r = _take_map(som_executor, tree_bd)
        assert r["count"] == 3
        assert [e["name"] for e in r["entries"]] == ["文件", "保存", "编辑"]

        with pytest.raises(ExecutorError) as ei:
            _click(som_executor, 4)
        assert ei.value.code == ELEMENT_NOT_FOUND          # 非 ELEMENT_DISABLED
        assert _reason(ei) == CACHE_STALE
        assert _invoked(tree_bd) == [0, 0, 0, 0, 0]

    def test_remap_hits_new_index_not_same_name(self, som_executor):
        """同名元素换号（A:3=保存 → B:3=编辑）→ 3 号只命中 B 的「编辑」。

        本用例是**守卫，非红**：本单缺陷的机制是缓存逐键覆盖，B 的 1..count(B)
        必然被新表覆盖，故编号 ≤ count(B) 在修复前后都指向新元素——
        用 1..count 的编号**测不出**本缺陷，缺陷只体现在编号 > count(B) 上
        （见 test_all_ids_above_count_refused_by_cache）。
        保留本例是为防未来改成"先清后建"或"惰性重建"时把
        编号 1..count 的语义写坏。
        """
        _take_map(som_executor, _tree_a())
        tree_b = _tree_b()
        _take_map(som_executor, tree_b)

        assert _click(som_executor, 3)["element"]["name"] == "编辑"
        assert _click(som_executor, 2)["element"]["name"] == "保存"
        assert _invoked(tree_b) == [0, 1, 1, 0, 0]

    def test_grow_then_all_ids_of_both_available(self, som_executor):
        """A(3) → B(5)：条目变多时全部 5 个编号可用，无旧编号错位。

        反方向的边界（N 变大），**守卫非红**：逐键覆盖下 N 变大本就无残留。
        留它是因为"先清后建"的实现若把清表做在异常路径上（取图失败即清空），
        或把替换误做成"仅在 N 变小时替换"，本条会红。
        """
        tree_small = FakeElement(children=[
            FakeElement(name="文件", rect=(110, 110, 160, 140)),
            FakeElement(name="编辑", rect=(170, 110, 220, 140)),
            FakeElement(name="保存", rect=(110, 160, 160, 190)),
        ])
        _take_map(som_executor, tree_small)

        tree_big = _tree_a()
        r = _take_map(som_executor, tree_big)
        assert r["count"] == 5

        hit = []
        for som_id in (1, 2, 3, 4, 5):
            got = _click(som_executor, som_id)
            assert got["status"] == "ok"
            hit.append(got["element"]["name"])
        assert hit == ["文件", "编辑", "保存", "打印", "导出"]


# ---------- 编号域边界 ----------

class TestMapIdDomain:
    """取图响应给出的编号域与缓存可解析的编号域必须同一。

    AI 唯一的编号来源是取图响应（它看不到缓存），故两个编号域错位就是本单缺陷。
    本类在公开出口上核对"响应编号域 == 可点击编号域"。
    """

    def test_ids_contiguous_and_only_count_clickable(self, som_executor):
        """A(5) → B(3)：响应 id 恰为 1..count；count+1 起一律按缓存作废拒绝。"""
        _take_map(som_executor, _tree_a())
        r = _take_map(som_executor, _tree_b())

        assert [e["id"] for e in r["entries"]] == list(range(1, r["count"] + 1))

        for som_id in range(1, r["count"] + 1):
            assert _click(som_executor, som_id)["status"] == "ok"
        _expect_refusal(som_executor, r["count"] + 1, reason=CACHE_STALE)

    def test_empty_map_leaves_no_clickable_id(self, som_executor):
        """A(5) → B(0，无可交互元素)：响应为空，且**所有**旧编号都按缓存作废拒绝。

        "N 变小"的极端情形。修复前：旧缓存全留，AI 用任何旧编号都能点到东西
        （且新图是空图，连"该重新取图"的线索都没有）；修复后一律缓存作废。
        """
        _take_map(som_executor, _tree_a())

        empty = FakeElement(children=[])
        r = _take_map(som_executor, empty)
        assert r["count"] == 0
        assert r["entries"] == []

        for som_id in (1, 3, 5):
            _expect_refusal(som_executor, som_id, reason=CACHE_STALE)
        assert _invoked(empty) == []

    def test_id_zero_and_negative_refused(self, som_executor):
        """编号 0 / 负数不在任何一次取图的编号域内 → 显式拒绝且零点击。

        本用例是**守卫，非红**：单次取图内 1..5 全在缓存，0/-1 走的不是
        本单要修的路径。留它是因为"编号域 1..N"是既有安全语义，
        整表替换不得把它改坏。
        """
        tree_a = _tree_a()
        _take_map(som_executor, tree_a)
        for bad in (0, -1):
            _expect_refusal(som_executor, bad, reason=CACHE_STALE)
        assert _invoked(tree_a) == [0, 0, 0, 0, 0, 0, 0]
