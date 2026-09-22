"""ISS-0105 读回选读通道自证假阳性测试(TC-105-01~03,问题单 §5 测试设计表)。

背景:选读通道③(ctrl+a/ctrl+c)在「目标文档为空 ∧ 焦点不在编辑区」
组合下失效——粘贴落空后,选读在标签条上空操作,剪贴板残留的是桥刚
写入的请求文本本身,子串比对退化成自证(假命中 ok:true,文档实为空,
ISS-0104 P1 逃逸口实盘)。裁定 A(哨兵清剪贴板):选读前 copy 专属哨兵,
ctrl+c 后仍是哨兵=选读失败(None),被改写才进入比对。

层级分布(§5 表逐行落码):
- 单元:TC-105-01/02(替身/桩允许,照 test_typeguard_iss100 桥替身风格;
  剪贴板状态机替身:copy 写值、ctrl+c 按需模拟应用改写)
- 形态:TC-105-03(源码直读)

入口(设计):Executor._type_text(全链)/Executor._read_via_selection
(选读通道本体)/core.py 源码。
断言出处:异常 code 属性直出/返回值直出/copy 桩调用记录直出/源码文本
检索直读——均直出,无中间转换。

P1 红态预期:TC-105-01 红(现状无哨兵,paste 读到请求文本假命中 ok,
DID NOT RAISE);TC-105-02 红(现状选读零 copy,桩记录无哨兵);
TC-105-03 红(源码无哨兵常量)。适配面:TC-100-07 替身已按登记改
剪贴板状态机(ctrl+c 模拟真实改写),双世界语义一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deskpilot.errors import READBACK_UNAVAILABLE, ExecutorError
from deskpilot.executor.core import Executor

ROOT = Path(__file__).resolve().parent.parent


class _UiaNode:
    """UIA 替身节点(iss100 同型):两路读值均无,仅存在 Edit 控件。"""

    def __init__(self, type_name: str):
        self.ControlTypeName = type_name

    def GetValuePattern(self):
        raise Exception("替身:无 ValuePattern")

    def GetTextPattern(self):
        raise Exception("替身:无 TextPattern")


def _clipboard_rig(monkeypatch, core, *, overwrite_with: str | None,
                   initial: str = "old"):
    """剪贴板状态机替身:copy 记录并写值;hotkey 记录,其中 ctrl+c 在
    overwrite_with 非 None 时模拟目标应用真实改写(选区内容),为 None
    时模拟焦点落空空操作(剪贴板保持)。返回 (copies, hotkeys)。"""
    state = {"v": initial}
    copies: list[str] = []
    hotkeys: list[tuple] = []

    def _copy(t):
        copies.append(t)
        state["v"] = t

    def _hotkey(*a, **k):
        hotkeys.append(a)
        if a == ("ctrl", "c") and overwrite_with is not None:
            state["v"] = overwrite_with       # 应用真实改写(选区内容)

    monkeypatch.setattr(core.pyperclip, "copy", _copy)
    monkeypatch.setattr(core.pyperclip, "paste", lambda: state["v"])
    monkeypatch.setattr(core.pyautogui, "hotkey", _hotkey)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    return copies, hotkeys


class TestSelectionSelfProofSealed:
    """TC-105-01(单元,裁定 A):选读自证路径封死。"""

    def test_tc105_01_stale_clipboard_no_false_match(self, monkeypatch):
        """TC-105-01(单元):替身 paste 返回=桥写入的请求文本(模拟焦点
        落空,ctrl+c 空操作,剪贴板保持) → _type_text 不得假命中 ok;
        走 READBACK_UNAVAILABLE(选读失败,通道全灭面不回退)。
        前提:UIA 替身首个 Edit 节点两路无值(①②无值,仅③选读);
        old_clip="old"(finally 还原断言)。
        断言:异常 code 直出;copy 桩记录直出(还原语义覆盖)。
        红态:现状无哨兵,选读读到请求文本假命中返回 ok(DID NOT RAISE)。"""
        import deskpilot.executor.core as core

        text = "中文请求文本"
        ex = Executor.__new__(Executor)          # 不经 __init__,仅取方法
        monkeypatch.setattr(ex, "_activate_if_needed", lambda hwnd: True)
        monkeypatch.setattr(ex, "_iter_controls",
                            lambda root, depth=0: iter([_UiaNode("Edit")]))
        monkeypatch.setattr(core.uiautomation, "ControlFromHandle",
                            lambda hwnd: object())
        copies, _ = _clipboard_rig(monkeypatch, core, overwrite_with=None)
        with pytest.raises(ExecutorError) as ei:
            ex._type_text(text, 42)
        assert ei.value.code == READBACK_UNAVAILABLE, \
            f"选读自证须封死(READBACK_UNAVAILABLE),实得 {ei.value.code}"
        assert copies[-1] == "old", \
            "finally old_clip 还原语义覆盖哨兵写(桩记录直出)"


class TestSelectionRealHit:
    """TC-105-02(单元,裁定 A 正向):真实选区改写后正常命中。"""

    def test_tc105_02_real_selection_overwrite_hits(self, monkeypatch):
        """TC-105-02(单元):替身 ctrl+c 真实改写(选区="选区真实内容")
        → _read_via_selection 返回选区内容(非 None);copy 桩记录含哨兵
        (序列首步,常量内嵌引用)。
        断言:返回值直出;copy 桩记录直出(含 _SELECTION_SENTINEL)。
        红态:现状选读零 copy(桩记录空,无哨兵)。"""
        import deskpilot.executor.core as core

        copies, hotkeys = _clipboard_rig(monkeypatch, core,
                                         overwrite_with="选区真实内容")
        r = Executor._read_via_selection()
        assert r == "选区真实内容"               # 返回值直出(非 None)
        assert hotkeys[:2] == [("ctrl", "a"), ("ctrl", "c")]  # 序直出
        from deskpilot.executor.core import _SELECTION_SENTINEL
        assert copies and copies[0] == _SELECTION_SENTINEL, \
            f"选读首步须写哨兵(桩记录直出): {copies}"


class TestSentinelSourcePin:
    """TC-105-03(形态):哨兵定值唯一性(源码直读)。"""

    def test_tc105_03_sentinel_constant_single_pointed(self):
        """TC-105-03(形态,§5):core.py 哨兵常量单点定义且含不可打印
        字符(\\x00,防撞串)。断言:源码文本检索直读。
        红态:现状无哨兵常量。"""
        src = (ROOT / "deskpilot" / "executor" / "core.py").read_text(
            encoding="utf-8")
        defs = [l for l in src.splitlines()
                if l.startswith("_SELECTION_SENTINEL")]
        assert len(defs) == 1, f"哨兵常量须单点定义(直读): {defs}"
        assert "\\x00" in defs[0], \
            f"哨兵须含不可打印字符(防撞串,直读): {defs[0]}"
