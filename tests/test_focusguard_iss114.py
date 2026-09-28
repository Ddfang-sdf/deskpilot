"""ISS-0114 聚焦助手抢焦点修复测试(TC-114-01/02,问题单 §3 改法 A)。

背景:ISS-0104 的 _focus_first_edit 无条件 SetFocus 首个 Edit/Document;
焦点已在 ComboBox(浏览器地址栏等可输入控件)时被抢回页面,粘贴落空。
改法 A:焦点已在可输入控件(Edit/Document/ComboBox)则不抢。

层级:单元(替身允许)。入口:deskpilot.executor.input._focus_first_edit。
断言出处:SetFocus 替身调用记录直出。
红态预期:TC-114-01 红(现状无条件 SetFocus);TC-114-02 绿(行为保持面)。
"""

from __future__ import annotations

import deskpilot.executor.input as inp
from deskpilot.executor.core import Executor


class _Node:
    def __init__(self, type_name: str):
        self.ControlTypeName = type_name
        self.setfocus_calls = 0

    def SetFocus(self):
        self.setfocus_calls += 1


def _rig(monkeypatch, focused_type: str):
    """替身装配:focused=指定类型焦点控件;页面首个 Edit 带 SetFocus 记录。"""
    edit = _Node("EditControl")
    focused = _Node(focused_type)
    ex = Executor.__new__(Executor)
    monkeypatch.setattr(ex, "_ensure_com", lambda: None)
    monkeypatch.setattr(inp.uiautomation, "ControlFromHandle",
                        lambda hwnd: object())
    monkeypatch.setattr(inp.uiautomation, "GetFocusedControl",
                        lambda: focused)
    monkeypatch.setattr(ex, "_iter_controls",
                        lambda root, depth=0: iter([edit]))
    return ex, edit, focused


class TestFocusGuardIss114:
    """TC-114-01/02(单元,改法 A:已在可输入控件则不抢)。"""

    def test_tc114_01_combobox_focused_no_steal(self, monkeypatch):
        """TC-114-01:焦点在 ComboBox(地址栏)→ SetFocus 零调用(不抢)。
        断言:替身调用记录直出。红态:现状无条件 SetFocus。"""
        ex, edit, _ = _rig(monkeypatch, "ComboBoxControl")
        ex._focus_first_edit(42)
        assert edit.setfocus_calls == 0, \
            f"焦点已在 ComboBox 不得抢(直出): {edit.setfocus_calls}"

    def test_tc114_02_pane_focused_steals_to_first_edit(self, monkeypatch):
        """TC-114-02(行为保持):焦点在 Pane(非输入区)→ 聚焦首个 Edit
        (ISS-0104 行为不回退)。断言:替身调用记录直出。"""
        ex, edit, _ = _rig(monkeypatch, "PaneControl")
        ex._focus_first_edit(42)
        assert edit.setfocus_calls == 1, \
            f"焦点在非输入区须聚焦首个 Edit(直出): {edit.setfocus_calls}"


class TestComboBoxReadback:
    """TC-114-03(改法 B,2026-09-28 sdfang 裁定补上):ComboBox 纳入
    可输入/读回集合——地址栏类目标粘贴后可读回,不再误报重贴。

    红态:现状 _EDIT_TYPE_NAMES 无 ComboBox,读回落 READBACK_UNAVAILABLE。"""

    def test_tc114_03_combobox_readback_ok_no_repaste(self, monkeypatch):
        """TC-114-03(单元):焦点在 ComboBox;其 ValuePattern 给出已粘贴文本
        → type_text ok+note 一致+粘贴恰一次(零重贴)。
        断言:桩 hotkey 序列直出(ctrl+v 恰一次);返回值直出。"""
        import deskpilot.executor.input as inp
        from deskpilot.executor.core import Executor

        class _Combo:
            ControlTypeName = "ComboBoxControl"
            setfocus_calls = 0
            def SetFocus(self): self.setfocus_calls += 1
            class _VP:
                Value = "www.baidu.com"
            def GetValuePattern(self): return self._VP()

        combo = _Combo()
        hotkeys: list = []
        ex = Executor.__new__(Executor)
        monkeypatch.setattr(ex, "_activate_if_needed", lambda hwnd: True)
        monkeypatch.setattr(ex, "_ensure_com", lambda: None)
        monkeypatch.setattr(inp.uiautomation, "ControlFromHandle",
                            lambda hwnd: object())
        monkeypatch.setattr(inp.uiautomation, "GetFocusedControl",
                            lambda: combo)
        monkeypatch.setattr(ex, "_iter_controls",
                            lambda root, depth=0: iter([combo]))
        monkeypatch.setattr(inp.pyperclip, "copy", lambda t: None)
        monkeypatch.setattr(inp.pyperclip, "paste", lambda: "old")
        monkeypatch.setattr(inp.pyautogui, "hotkey",
                            lambda *a, **k: hotkeys.append(a))
        monkeypatch.setattr(inp.time, "sleep", lambda s: None)

        r = ex._type_text("www.baidu.com", 42)
        assert r["status"] == "ok", f"读回应通过(返回值直出): {r}"
        assert hotkeys.count(("ctrl", "v")) == 1, \
            f"粘贴须恰一次零重贴(桩序列直出): {hotkeys}"
        assert combo.setfocus_calls == 0, \
            "焦点已在 ComboBox 不得抢(直出)"
