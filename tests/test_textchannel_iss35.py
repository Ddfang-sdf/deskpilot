"""ISS-0035【修改引入】文字通道修正测试(TC-TX-01~06,问题单 §3 v0.1)。

层级:单元(type_text 轮询/归一化纯函数,替身计数直出);
TC-TX-03 为既有 ct08 集成恢复(其回归在 test_clicktext_iss21)。
入口(设计):executor._type_text 剪贴板桥 / textclick 归一化。
"""

from __future__ import annotations

import pytest

from deskpilot.errors import ExecutorError
from deskpilot.executor.textclick import resolve_click, suggest_similar


class TestTypeTextPolling:
    """TC-TX-01/02:读回轮询确认——滞后不重贴,真失败仍重贴至上限。"""

    def _executor(self, monkeypatch):
        from deskpilot.executor import Executor
        ex = Executor.__new__(Executor)          # 不经 __init__,仅取方法
        monkeypatch.setattr(ex, "_activate_if_needed", lambda hwnd: True)
        monkeypatch.setattr(ex, "_read_edit_value",
                            lambda hwnd: self._readback.pop(0)
                            if self._readback else "stale")
        return ex

    def test_tx01_lag_no_repaste(self, monkeypatch):
        """读回先滞后后一致 → 恰一次粘贴,读回一致(中文走剪贴板桥)。"""
        import deskpilot.executor.core as core
        self._readback = ["", "中文", "中文"]     # 首读空(滞后)→次读命中
        ex = self._executor(monkeypatch)
        pastes = []
        monkeypatch.setattr(core.pyautogui, "hotkey",
                            lambda *a, **k: pastes.append(a))
        monkeypatch.setattr(core.pyperclip, "copy", lambda t: None)
        monkeypatch.setattr(core.pyperclip, "paste", lambda: "old")
        r = ex._type_text("中文", 42)
        assert len(pastes) == 1                  # 不重贴(直出)
        assert r["mode"] == "clipboard"
        assert r["note"] == "读回校验一致"

    def test_tx02_real_failure_retries_then_raises(self, monkeypatch):
        """读回恒不含文本 → 重贴至上限 2 次后 INTERNAL_ERROR。"""
        import deskpilot.executor.core as core
        self._readback = []
        ex = self._executor(monkeypatch)
        pastes = []
        monkeypatch.setattr(core.pyautogui, "hotkey",
                            lambda *a, **k: pastes.append(a))
        monkeypatch.setattr(core.pyperclip, "copy", lambda t: None)
        monkeypatch.setattr(core.pyperclip, "paste", lambda: "old")
        monkeypatch.setattr(core.time, "sleep", lambda s: None)  # 免真等待
        with pytest.raises(ExecutorError):
            ex._type_text("中文", 42)
        assert len(pastes) == 2                  # 重贴至上限(直出)


class TestNormalization:
    """TC-TX-04/05/06:命中与建议共用归一化(大小写不敏感,中文不回归)。"""

    ITEMS = [{"text": "Save", "position": [10, 10, 60, 40]}]

    def test_tx04_case_insensitive_hit(self):
        status, payload = resolve_click(self.ITEMS, "save", "contains", None,
                                        100, 100, (0, 0, 100, 100))
        assert status == "ok"
        assert payload["matched"] == "Save"

    def test_tx05_case_insensitive_suggest(self):
        assert suggest_similar(self.ITEMS, "save") == ["Save"]

    def test_tx06_chinese_unaffected(self):
        items = [{"text": "保存文档", "position": [0, 0, 10, 10]}]
        status, payload = resolve_click(items, "保存", "contains", None,
                                        100, 100, (0, 0, 100, 100))
        assert status == "ok"
        assert payload["matched"] == "保存文档"
