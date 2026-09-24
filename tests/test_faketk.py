"""ISS-0059 fakeTk 库契约钉 + 唯一来源守卫(TC-FAKETK-01~04+GUARD,方案 §测试设计)。

层级:TC-FAKETK-01~04 单元(替身库自测允许打桩);GUARD 形态(源码直读)。
入口(设计):faketk.install / FakeWidget 方法面 / GUARD_* 扫描规则。
断言出处:recorder 观测口直出/异常直出/源码文本检索直读。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from . import faketk
from .faketk import install

TESTS_DIR = Path(__file__).resolve().parent


class TestFakeTkContract:
    """TC-FAKETK-01~04(单元):库观测口与 fail-closed 契约。"""

    def test_faketk01_button_text_command_recorded(self, monkeypatch):
        """TC-FAKETK-01:经替身构造 Button(text="x", command=f) →
        recorder 收录该按钮(text/command 直出)。"""
        import tkinter as tk
        rec = install(monkeypatch, tk)
        f = lambda: None
        tk.Button(text="x", command=f)
        assert rec.buttons[0].text == "x"               # 替身记录直出
        assert rec.buttons[0].command is f              # 替身记录直出
        assert rec.button_texts == ["x"]

    def test_faketk02_geometry_recorded(self, monkeypatch):
        """TC-FAKETK-02:替身窗 geometry("1x1+2+3") → 几何记录末项为该串。"""
        import tkinter as tk
        rec = install(monkeypatch, tk)
        win = tk.Toplevel()
        win.geometry("1x1+2+3")
        assert rec.geometries[-1] == "1x1+2+3"          # 直出
        assert win.geo == "1x1+2+3"                     # 实例属性(monitors 形)

    def test_faketk03_after_queued_and_pumped(self, monkeypatch):
        """TC-FAKETK-03:after(10, f) 入队 → pump 后 f 恰执行一次(计数直出)。"""
        import tkinter as tk
        rec = install(monkeypatch, tk)
        win = tk.Toplevel()
        calls = []
        token = win.after(10, lambda: calls.append(1))
        assert isinstance(token, str) and token         # 令牌形态统一
        rec.pump()
        assert calls == [1]                             # 直出
        assert rec.afters == []                         # 泵后队列空

    def test_faketk04_unknown_method_fails_closed(self, monkeypatch):
        """TC-FAKETK-04:调替身未定义方法 → AttributeError
        (沉默方言废止,fail-closed 直出)。"""
        import tkinter as tk
        rec = install(monkeypatch, tk)
        win = tk.Toplevel()
        with pytest.raises(AttributeError):
            win.wm_iconify()                            # 未列方法


class TestGuardRuleCoverage:
    """TC-FAKETK-GUARD-02(单元):守卫规则覆盖扩展形态(ISS-0109 收尾)。

    场景:①字符串形补丁 setattr("tkinter.Toplevel", …);②变体名内联
    tk 壳 type("T", (), {withdraw/mainloop…});③unittest.Mock 标准缝
    (行内 Mock( 自动豁免,ISS-0109 v0.2 登记);④非 tk 数据袋
    type("B"/"C", (), {…}) 不得误伤。
    断言:规则命中/豁免布尔直出。红态:现行规则对①②零命中。"""

    def test_guard02_string_form_patch_banned(self):
        """GUARD-02a:字符串形就地补丁(tkinter.X)命中禁则。"""
        src = 'monkeypatch.setattr("tkinter.Toplevel", fake)'
        assert faketk.GUARD_BANNED_PATCH.search(src), \
            "字符串形补丁未入禁则(直读)"

    def test_guard02_variant_inline_shell_banned(self):
        """GUARD-02b:变体名(type("T")内联 tk 壳命中禁则。"""
        src = ('type("T", (), {"withdraw": lambda s: None,\n'
               '                     "mainloop": lambda s: None})()')
        assert faketk.GUARD_BANNED_TYPE.search(src), \
            "变体名内联壳未入禁则(直读)"

    def test_guard02_mock_seam_auto_exempt(self):
        """GUARD-02c:行内 Mock( 的就地补丁=unittest.Mock 标准缝,
        守卫豁免裁决直出(ISS-0109 v0.2 登记)。"""
        line = 'monkeypatch.setattr("tkinter.Toplevel", Mock())'
        assert faketk.GUARD_BANNED_PATCH.search(line)
        assert faketk.guard_exempted(faketk.GUARD_BANNED_PATCH, line, ""), \
            "Mock 标准缝应自动豁免(直读)"

    def test_guard02_plain_data_bag_not_banned(self):
        """GUARD-02d:非 tk 数据袋 type("B"/"C") 不误伤。"""
        for src in ('type("B", (), {"window_rect": (0, 0, 1, 1)})()',
                    'type("C", (), {"policy": None})()'):
            assert not faketk.GUARD_BANNED_TYPE.search(src), \
                f"数据袋误伤(直读): {src}"


class TestFakeTkGuard:
    """TC-FAKETK-GUARD(形态):替身唯一来源——tests/ 下除白名单外,
    禁止本地替身类定义与就地 tk 控件补丁。

    提交时红(16 份在册),随迁移逐个转绿;永久防复发。
    白名单:faketk.py(库本体)/test_faketk.py(库钉);
    test_estopreset_iss93.py 的真 Tk E2E(TC-93-12)非替身不受影响
    (守卫只禁本地替身定义/就地补丁,不禁止 import tkinter)。
    """

    def test_faketk_guard_no_local_tk_doubles(self):
        """扫描 tests/*.py:本地替身类(class W/Btn/Lbl/Top/FakeWin/
        _Recorder/_TkRig/_FakeWidget)、就地 setattr(*.tk, "<控件>") 补丁、
        type("W", …) 内联替身——白名单外命中清单须为空(源码直读)。"""
        hits: list[str] = []
        for path in sorted(TESTS_DIR.glob("*.py")):
            if path.name in faketk.GUARD_ALLOW:
                continue
            src = path.read_text(encoding="utf-8")
            lines = src.splitlines()
            for rx, tag in ((faketk.GUARD_BANNED_CLASS, "本地替身类"),
                            (faketk.GUARD_BANNED_PATCH, "就地控件补丁"),
                            (faketk.GUARD_BANNED_TYPE, "内联 type(W)")):
                for m in rx.finditer(src):
                    line = src[: m.start()].count("\n") + 1
                    above = "\n".join(lines[max(0, line - 14): line])
                    if faketk.guard_exempted(rx, lines[line - 1], above):
                        continue            # 豁免裁决单点(标记/Mock 标准缝)
                    hits.append(f"{path.name}:{line} {tag}: "
                                f"{m.group(0)[:40]}")
        assert hits == [], \
            "替身未收编单一来源(应迁移到 tests/faketk.py):\n" + \
            "\n".join(hits)
