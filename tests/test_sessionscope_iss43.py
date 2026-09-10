"""ISS-0043 A 层 同类许可作用域可见化单元测试(TC-43-01/02,问题单 §2 A)。

层级:单元(build_window + Tk 全替身,沿用 test_batch_iss19 装配)。
入口(设计):approval_dialog.build_window(公开入口)。
断言值来源:替身 Label 文本清单直出。

语义钉(A 层文案级,判定逻辑不动):
- 常规 L3 审批弹窗(含「此后同类允许」按钮)→ 必须同窗明示作用域:
  仅本次会话·此窗口绑定有效(daemon 重启/重新绑定后需重批);
- 入白审批弹窗(无该按钮)→ 不挂此提示(不错配预期)。
- B 层(许可键/持久许可)涉安全语义,未评审不动——本文件不测。

测试设计(五要素):
- TC-43-01 场景=常规审批;前提=Tk 替身;步骤=build_window(enroll=None);
  预期=Label 文本同时含「仅本次会话」与「重新绑定」;断言=文本清单直出。
- TC-43-02 场景=入白审批;步骤=build_window(enroll="x.exe");
  预期=无任何 Label 含「仅本次会话」;断言=文本清单直出。
"""

from __future__ import annotations


def _build_collect_texts(monkeypatch, tmp_path, enroll):
    import deskpilot.approval_dialog as ad
    labels = []

    class W:
        def pack(self, *a, **k): pass
        def place(self, *a, **k): pass
        def bind(self, *a, **k): pass
        def config(self, *a, **k): pass
        def focus_set(self): pass
        def title(self, *a): pass
        def overrideredirect(self, *a): pass
        def attributes(self, *a, **k): pass
        def configure(self, *a, **k): pass
        def geometry(self, *a): pass
        def after(self, *a, **k): pass
        def destroy(self): pass
        def winfo_screenwidth(self): return 2560
        def winfo_screenheight(self): return 1440

    class Lbl(W):
        def __init__(self, *a, **k):
            labels.append(k.get("text", ""))

    monkeypatch.setattr(ad.tk, "Toplevel", lambda parent: W())
    monkeypatch.setattr(ad.tk, "Frame", lambda *a, **k: W())
    monkeypatch.setattr(ad.tk, "Label", lambda *a, **k: Lbl(*a, **k))
    monkeypatch.setattr(ad.tk, "Button", lambda *a, **k: W())
    ad.build_window(object(), "常规审批", str(tmp_path / "r.txt"), 5,
                    enroll=enroll)
    return labels


class TestSessionScopeVisible:
    def test_tc43_01_normal_dialog_shows_scope(self, monkeypatch, tmp_path):
        """TC-43-01(ISS-0053 C 迁移):提示随新语义——仅本次会话+同键,
        且不再出现「重新绑定」字样(hwnd 键法下重绑不重批)。"""
        labels = _build_collect_texts(monkeypatch, tmp_path, enroll=None)
        assert any("仅本次会话" in t and "同键" in t
                   for t in labels), f"作用域提示缺失或未含同键粒度: {labels}"
        assert not any("重新绑定" in t for t in labels), \
            f"旧语义文案残留(重绑需重批已不为真): {labels}"

    def test_tc43_02_enroll_dialog_has_no_scope_hint(self, monkeypatch,
                                                     tmp_path):
        labels = _build_collect_texts(monkeypatch, tmp_path, enroll="x.exe")
        assert not any("仅本次会话" in t for t in labels), \
            f"入白弹窗错挂会话作用域提示: {labels}"
