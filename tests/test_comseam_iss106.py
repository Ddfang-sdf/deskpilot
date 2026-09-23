"""ISS-0106 读回/聚焦 UIA 入口经 _ensure_com 缝测试(TC-106-01/02,问题单 §3 表)。

背景:ISS-0100/0104 新增 UIA 访问点 _read_edit_value(core.py:1520)与
_focus_first_edit(:1545)绕过 ISS-0016 A 的 _ensure_com 线程惰性初始化缝,
打包形态 HTTP 工作线程 COM 未初始化 → 读回恒 None → type_text 全量
READBACK_UNAVAILABLE。修复=两函数首行补 self._ensure_com()。

层级:单元(允许打桩)。入口:Executor._read_edit_value/_focus_first_edit。
断言出处:core._com_initialize 记录桩调用记录直出(iss16 缝先例)。
红态预期:两用例全红(现状零 _ensure_com 调用)。
"""

from __future__ import annotations

import deskpilot.executor.core as core
from deskpilot.executor.core import Executor


def _fresh_executor(monkeypatch):
    """新 Executor(未初始化态)+COM 缝记录桩;UIA 面替身(不触真 COM)。

    返回 (ex, calls):calls 为 _com_initialize 调用次数记录(直出)。
    """
    calls: list[str] = []
    monkeypatch.setattr(core, "_com_initialize", lambda: calls.append("init"))
    ex = Executor.__new__(Executor)              # 不经 __init__,无 _com_local
    monkeypatch.setattr(core.uiautomation, "ControlFromHandle",
                        lambda hwnd: object())
    monkeypatch.setattr(ex, "_iter_controls",
                        lambda root, depth=0: iter([]))
    return ex, calls


class TestComSeamIss106:
    """TC-106-01/02(单元):两新 UIA 入口必经 _ensure_com 缝。"""

    def test_tc106_01_read_edit_value_ensures_com(self, monkeypatch):
        """TC-106-01(单元,ISS-0106 §3):_read_edit_value 首行 _ensure_com
        → core._com_initialize 缝被调恰好一次(未初始化态)。
        断言:桩调用记录直出。红态:现状绕缝,桩零记录。"""
        ex, calls = _fresh_executor(monkeypatch)
        ex._read_edit_value(42)
        assert calls == ["init"], \
            f"_read_edit_value 必须经 _ensure_com 缝(桩记录直出): {calls}"

    def test_tc106_02_focus_first_edit_ensures_com(self, monkeypatch):
        """TC-106-02(单元,ISS-0106 §3):_focus_first_edit 同样必经缝。
        断言:桩调用记录直出。红态:同上。"""
        ex, calls = _fresh_executor(monkeypatch)
        ex._focus_first_edit(42)
        assert calls == ["init"], \
            f"_focus_first_edit 必须经 _ensure_com 缝(桩记录直出): {calls}"
