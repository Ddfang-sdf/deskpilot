"""ISS-0085:白名单管理窗口撤销/清空 → 块级就地刷新(整窗零销毁重建)。

层级:**单元**(tk 全替身——iss12 同款内联套件的第 4 处拷贝,「替身散落」
既有坏味道不顺手重构(范围纪律,见 cleancode 族票);`_http_json` 替身控
数据源)。断言全在替身直出:labels 文本列表 / Top.destroy 调用记录 /
protocol 记录 / build_window 计数 / `state["win"]` 对象身份 / `ui._entries`。

用例来源:ISS-0085 §6.2(TC-UI85-01~06,评审通过整改方向①,sdfang 2026-09-15)。

**P1 红点位**:`refresh_view` / `_fetch_whitelist` / `_ManagerUI.set_data`
均为 NotImplementedError 空壳。

几何不变量(验收口径§3)以机制蕴含证明:窗口对象未销毁(destroy 零调用+
对象身份)⇒ Tk 几何天然保留(§6.1);真机肉眼面归手工验收,不引入真 Tk
测试新形态(仓库零先例)。
"""

from __future__ import annotations

import pytest

import deskpilot.whitelist_window as ww


# ---------- 替身套件(iss12 同款形态,加 Top 销毁/协议/建窗记录) ----------

class _Rec:
    def __init__(self):
        self.tops = []           # 创建的窗口(Top)实例
        self.top_destroys = []   # Top.destroy 调用记录(核心断言面)
        self.protocols = []      # Top.protocol 注册名
        self.labels = []         # 全部 Label 创建文本(直出)
        self.builds = []         # build_window 调用计数


def _stub_tk(monkeypatch) -> _Rec:
    rec = _Rec()

    class W:
        def __init__(self, *a, **k):
            self.text = k.get("text", "")
            self.command = k.get("command")
            self._text_value = ""
            self.pack_count = 0
            self.create_line_calls = []

        def pack(self, *a, **k): self.pack_count += 1
        def grid(self, *a, **k): pass
        def config(self, *a, **k): pass
        def configure(self, *a, **k):
            if "text" in k: self.text = k["text"]
            if "command" in k: self.command = k["command"]
        def bind(self, *a, **k): pass
        def bind_all(self, *a, **k): pass
        def title(self, *a): pass
        def geometry(self, *a): pass
        def minsize(self, *a): pass
        def attributes(self, *a, **k): pass
        def yview(self, *a, **k): pass
        def create_window(self, *a, **k): return 1
        def itemconfig(self, *a, **k): pass
        def bbox(self, *a, **k): return (0, 0, 0, 0)
        def set(self, *a, **k): pass
        def yview_scroll(self, *a, **k): pass
        def winfo_children(self): return []
        def destroy(self): pass
        def pack_forget(self): pass
        def get(self): return self._text_value
        def create_line(self, *a, **k): self.create_line_calls.append((a, k))
        def create_rectangle(self, *a, **k): pass
        def create_oval(self, *a, **k): pass
        def delete(self, *a, **k): pass

    class Lbl(W):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            rec.labels.append(self.text)

    class Top(W):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            rec.tops.append(self)

        def destroy(self):
            rec.top_destroys.append(self)

        def protocol(self, name, *a):
            rec.protocols.append(name)

    monkeypatch.setattr(ww.tk, "Toplevel", lambda parent: Top())
    monkeypatch.setattr(ww.tk, "Frame", lambda *a, **k: W(*a, **k))
    monkeypatch.setattr(ww.tk, "Canvas", lambda *a, **k: W(*a, **k))
    monkeypatch.setattr(ww.tk, "Scrollbar", lambda *a, **k: W(*a, **k))
    monkeypatch.setattr(ww.tk, "Label", lambda *a, **k: Lbl(*a, **k))
    monkeypatch.setattr(ww.tk, "Button", lambda *a, **k: W(*a, **k))
    monkeypatch.setattr(ww.tk, "Entry", lambda *a, **k: W(*a, **k))

    orig_build = ww.build_window

    def counted(*a, **k):
        rec.builds.append(1)
        return orig_build(*a, **k)

    monkeypatch.setattr(ww, "build_window", counted)
    return rec


# ---------- 数据源替身(/whitelist 端点形态) ----------

def _entry(proc, level="L2", display=None, desc=None):
    return {"process": proc, "level": level, "display": display, "desc": desc}


class _Source:
    """holder:{"data": {group: [entry...]}, "raise": bool}"""

    def __init__(self, monkeypatch, data):
        self.holder = {"data": data, "raise": False}

        def fake_http(url, payload=None):
            if self.holder["raise"]:
                raise OSError("network down")
            return {"data": self.holder["data"]}

        monkeypatch.setattr(ww, "_http_json", fake_http)

    def set(self, data):
        self.holder["data"] = data

    def fail(self):
        self.holder["raise"] = True


_TWO_STATIC = {"static": [_entry("notepad.exe", display="记事本"),
                          _entry("excel.exe", display="Excel")],
               "session": [_entry("a.exe")]}


def _mk(monkeypatch, data=None):
    rec = _stub_tk(monkeypatch)
    src = _Source(monkeypatch, data if data is not None else _TWO_STATIC)
    state = {"win": None}
    return rec, src, state


class _Root:
    """root 替身:refresh_view 首建时访问 root.quit(WM_DELETE_WINDOW 回调)。"""
    def __init__(self):
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


def _view(state):
    ww.refresh_view(state, "http://127.0.0.1:1", _Root(),
                    on_remove=lambda p: None, on_clear=lambda: None)


# ---------- TC-UI85-01:撤销后零重建(核心) ----------

class TestRemoveInPlace:
    def test_remove_refreshes_in_place(self, monkeypatch):
        """场景:窗口已建,数据源中 excel.exe 被撤销 → 再刷新。
        预期:窗不销毁不重建(对象身份+destroy 零+build 一次),条目就地更新。
        断言出处:state["win"] 身份 / rec.top_destroys / rec.builds /
        ui._entries / 重渲染 labels(直出)。"""
        rec, src, state = _mk(monkeypatch)
        _view(state)
        win0 = state["win"]
        assert win0 is not None and len(rec.builds) == 1   # 前提:首建完成

        rec.labels.clear()
        src.set({"static": [_entry("notepad.exe", display="记事本")],
                 "session": [_entry("a.exe")]})             # excel 已撤销
        _view(state)

        assert state["win"] is win0, "窗口对象身份须不变(未销毁重建)"
        assert rec.top_destroys == [], "窗口 destroy 须零调用"
        assert len(rec.builds) == 1, "build_window 不得二次调用"
        ui = win0._manager
        assert "excel.exe" not in ui._entries["static"]     # 数据已更新
        assert "notepad.exe" in ui._entries["static"]
        assert not any("excel.exe" in s for s in rec.labels), "excel 行须消失"
        assert any("notepad.exe · L2" in s for s in rec.labels), "notepad 行仍在"


# ---------- TC-UI85-02:清空同病同治 ----------

class TestClearInPlace:
    def test_clear_refreshes_in_place(self, monkeypatch):
        """场景:session 清空(全部清空按钮路径)→ 再刷新。
        预期:零重建 + session 区空态直出。"""
        rec, src, state = _mk(monkeypatch)
        _view(state)
        win0 = state["win"]

        rec.labels.clear()
        src.set({"static": [_entry("notepad.exe", display="记事本"),
                            _entry("excel.exe", display="Excel")],
                 "session": []})
        _view(state)

        assert state["win"] is win0
        assert rec.top_destroys == []
        assert len(rec.builds) == 1
        assert win0._manager._entries["session"] == {}
        assert any("本次会话暂无临时允许" in s for s in rec.labels), \
            "session 空态主标题须直出"


# ---------- TC-UI85-03:首建路径 ----------

class TestFirstBuild:
    def test_first_call_builds_and_registers_protocol(self, monkeypatch):
        """场景:state 无窗 → refresh_view 首建。
        预期:建窗一次,WM_DELETE_WINDOW 注册,state["win"] 落位。"""
        rec, src, state = _mk(monkeypatch)
        _view(state)

        assert state["win"] is not None
        assert len(rec.builds) == 1
        assert len(rec.tops) == 1
        assert "WM_DELETE_WINDOW" in rec.protocols


# ---------- TC-UI85-04:抓取失败保窗 ----------

class TestFetchFailure:
    def test_http_failure_keeps_window_in_place(self, monkeypatch):
        """场景:已建窗后 /whitelist 抓取抛异常。
        预期:不抛异常(直接调用,不包 raises),窗保住,数据置空表
        (既有容错语义原样迁移),空态渲染。"""
        rec, src, state = _mk(monkeypatch)
        _view(state)
        win0 = state["win"]

        rec.labels.clear()
        src.fail()
        _view(state)                            # 不得抛异常

        assert state["win"] is win0
        assert rec.top_destroys == []
        assert len(rec.builds) == 1
        assert win0._manager._entries == {"static": {}, "session": {}}
        assert any("暂无永久加入的软件" in s for s in rec.labels)


# ---------- TC-UI85-05:set_data 整表替换 ----------

class TestSetData:
    def test_set_data_replaces_tables_wholesale(self, monkeypatch):
        """场景:控制器已建,喂新表。
        预期:_entries/_dmap 引用整体换(整表替换,非逐键改),重渲染生效。"""
        rec, src, state = _mk(monkeypatch)
        _view(state)
        ui = state["win"]._manager

        new_entries = {"static": {"code.exe": "L2"}, "session": {}}
        new_dmap = {"code.exe": ("VS Code", "编辑器")}
        rec.labels.clear()
        ui.set_data(new_entries, new_dmap)

        assert ui._entries is new_entries, "整表替换:引用同一性"
        assert ui._dmap is new_dmap
        assert any("VS Code" in s for s in rec.labels)
        assert any("code.exe · L2" in s for s in rec.labels)
        assert not any("notepad.exe" in s for s in rec.labels), "旧行须消失"


# ---------- TC-UI85-06:dmap 零解析直供 ----------

class TestDmapSupply:
    def test_set_data_dmap_supplies_display_name(self, monkeypatch):
        """场景:set_data 带 display_map,proc 为 appnames 名录外名字。
        预期:行主名用 dmap 直供名,不走 appnames 回退
        (TC-FAST-02 同语义在就地路径保持)。"""
        rec, src, state = _mk(monkeypatch)
        _view(state)
        ui = state["win"]._manager

        rec.labels.clear()
        ui.set_data({"static": {"zzz_unknown.exe": "L2"}, "session": {}},
                    {"zzz_unknown.exe": ("定制名", None)})

        assert any("定制名" in s for s in rec.labels), "dmap 直供名须上行"
