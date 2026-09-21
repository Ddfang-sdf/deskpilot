"""ISS-0103 冻结卡英文两处破防测试(f01~f04,问题单 §3 骨架)。

层级:单元(替身/桩允许)+形态(源码直读)。
入口(设计):deskpilot.freeze_dialog 源映射函数 / 按钮组构建;
deskpilot.i18n.tr(公开取词口)。
断言出处:映射函数返回值直出/tr 返回值直出/place 调用参数直出/源码直读。

红态预期:f01/f02 红(键/映射不存在),f03 红(按钮定宽 140),
f04 红(全角括号硬拼在源码)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestTriggerSourceBilingual:
    """f01/f02:触发源与 snooze 模板双语。"""

    def test_f01_trigger_source_mapped_bilingual(self, monkeypatch):
        """f01:state.source=「鼠标甩角」→ en 显示为英文,zh 原样;
        「热键 Ctrl+Shift+F12」同;未知来源原样透传。"""
        from deskpilot.freeze_dialog import source_display
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        en = source_display("鼠标甩角")
        assert "甩角" not in en and en                      # 英文无中文(直出)
        en_hk = source_display("热键 Ctrl+Shift+F12")
        assert "热键" not in en_hk and "Ctrl+Shift+F12" in en_hk
        monkeypatch.setenv("DESKPILOT_LOCALE", "zh-CN")
        assert source_display("鼠标甩角") == "鼠标甩角"       # zh 原样(直出)
        assert source_display("别的什么") == "别的什么"       # 未知透传(直出)

    def test_f02_snooze_template_bilingual_with_seconds(self, monkeypatch):
        """f02:freeze.btn.snooze 含 {n} 槽,en 半角括号,zh 全角括号。"""
        from deskpilot import i18n
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        en = i18n.tr("freeze.btn.snooze", n=180)
        assert en == "Remind me later (180s)"               # 半角(直出)
        monkeypatch.setenv("DESKPILOT_LOCALE", "zh-CN")
        zh = i18n.tr("freeze.btn.snooze", n=180)
        assert zh == "稍后提醒（180s）"                     # 全角(直出)


class TestButtonMeasuredWidth:
    """f03:按钮宽按实测文本宽,组居中(先量后排,同 ISS-0098 纪律)。"""

    def test_f03_button_width_from_measured_text(self, monkeypatch):
        """f03:英文长文案下,snooze 按钮 place width ≥ 文本实测宽+padding;
        按钮组按总宽居中(x = (WIN_W - 总宽)/2)。"""
        import deskpilot.freeze_dialog as fd
        places = []

        class W:
            def __init__(self, *a, **k):
                self._text = k.get("text", "")

            def __getattr__(self, name):
                if name.startswith("__"):
                    raise AttributeError(name)
                if name in ("winfo_screenwidth", "winfo_screenheight"):
                    return lambda: 1920
                return lambda *a, **k: None

            def place(self, *a, **k):
                places.append((self._text, dict(k)))

            def configure(self, **k):
                if "text" in k:
                    self._text = k["text"]

            config = configure

        import tkinter as _tk
        for cls in ("Toplevel", "Frame", "Label", "Button", "Canvas"):
            monkeypatch.setattr(_tk, cls, W)
        monkeypatch.setattr(fd, "_measure_text", lambda s: 170)   # 替身测量缝
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        try:
            fd.build_window(object(), audit_dir=str(ROOT / "audit"),
                            interval=180)
        finally:
            fd.release_singleton()   # 替身窗无 Destroy 事件,单例互斥须手动放
        snooze = [p for t, p in places if "Remind" in t]
        assert snooze, "未找到 snooze 按钮 place 记录"
        w = snooze[0].get("width", 0)
        assert w >= 160, f"英文长文按钮宽仍 {w}px(定宽裁边未修)"


class TestNoFullwidthParenHardcode:
    """f04(形态):源码不再硬拼全角括号秒数。"""

    def test_f04_no_fullwidth_paren_hardcode(self):
        """f04:freeze_dialog.py 不再出现 f\"（{…}s）\" 全角拼串。"""
        src = (ROOT / "deskpilot" / "freeze_dialog.py").read_text(
            encoding="utf-8")
        assert "（{" not in src.replace("（按钮组", ""), \
            "源码仍硬拼全角括号秒数"
        assert 'f"（{' not in src, "源码仍硬拼全角括号秒数"
