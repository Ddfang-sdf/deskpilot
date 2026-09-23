"""ISS-0059 fakeTk 单一替身库(16 份替身收编,整改方案步骤 1)。

显式方法面 = 16 份替身并集(pack/place/grid/pack_forget/bind/bind_all/
config/configure/focus_set/title/overrideredirect/attributes/geometry/
minsize/protocol/after/after_cancel/destroy/update_idletasks/withdraw/
deiconify/mainloop/quit/lower/lift/winfo_*/yview*/create_*/itemconfig/
bbox/delete/get/set/cget);**未列方法 → AttributeError**(fail-closed,
__getattr__ 沉默方言废止——裁决②,暗靠沉默放行的用例迁移当场转红,
处置=补库方法面并登记,不回退沉默面)。

用法::

    from .faketk import install
    rec = install(monkeypatch, mod.tk)                       # mod=被测弹窗模块
    rec = install(monkeypatch, mod.tk, screen=(1920, 1080), reqheight=600)

install 一次替换 Tk/Toplevel/Frame/Label/Button/Canvas/Scrollbar/Entry/
Listbox(更多类无副作用,生产未用不触发),返回 recorder 观测口:
- buttons / button_texts:Button 实例与文本(含 command 属性);
- labels:Label 创建文本(仅创建时;undo v2 语义用 label_updates);
- label_updates:创建+configure(text=) 全量文本(TC-UNDO 语义);
- geometries / places / afters / after_ms / destroys / destroyed_widgets /
  tops / protocols / alphas / idletasks / create_line 记录(实例级);
- reqheight / screen:构造参数化(按各测试原校准值传,断言值不动);
- pump(n):after 队列泵(弹出前 n 个回调并执行,跳过 None);
- of_class(name):按 tk 类名取实例列表(ISS-0109 widget 级观测口)。

ISS-0109 widget 级扩展面(_IconButton 字形/画布替身族收编):实例级
handlers(bind 记录)/afters(实例 after ms 序列)/cancelled
(after_cancel 记录);tk_class 类名标签(of_class 检索基)。
"""

from __future__ import annotations

import re


class _Recorder:
    """观测口集合(装配侧取用;断言直读)。"""

    def __init__(self, screen: tuple[int, int], reqheight: int) -> None:
        self.screen = screen
        self.reqheight = reqheight
        self.widgets: list = []
        self.buttons: list = []
        self.button_texts: list[str] = []
        self.labels: list[str] = []          # Label 创建文本(仅创建)
        self.label_updates: list[str] = []   # 创建+configure(text=) 全量
        self.geometries: list[str] = []
        self.places: list[tuple[str, dict]] = []
        self.afters: list[tuple[int, object]] = []
        self.destroys: int = 0
        self.destroyed_widgets: list = []
        self.tops: list = []
        self.protocols: list[str] = []
        self.alphas: list = []
        self.idletasks: int = 0

    @property
    def after_ms(self) -> list[int]:
        """after 调度的 ms 序列(TC-UNDO/TC-ANIM 观测形)。"""
        return [ms for ms, _ in self.afters]

    def pump(self, n: int | None = None) -> None:
        """after 队列泵:弹出回调并执行,跳过 None。

        n 给定=弹出前 n 个(**活弹**:回调自重排也照弹——滑入动画类
        自续队列的正确语义,estopreset pump_to_shown 先例);n=None=
        泵当前已入队项(快照,不追自重排,防自续队列死循环)。
        """
        if n is None:
            queue = list(self.afters)
            del self.afters[: len(queue)]
            for _ms, fn in queue:
                if fn is not None:
                    fn()
            return
        count = 0
        while self.afters and count < n:
            _ms, fn = self.afters.pop(0)
            if fn is not None:
                fn()
            count += 1

    def of_class(self, name: str) -> list:
        """按 tk 类名取实例列表(ISS-0109 widget 级观测口)。"""
        return [w for w in self.widgets if w.tk_class == name]

    def button_command(self, text: str):
        """按文本取按钮 command(estopreset 观测形);无此按钮 → KeyError。"""
        for b in self.buttons:
            if b.text == text:
                return b.command
        raise KeyError(f"无文本为 {text!r} 的按钮: "
                       f"{[b.text for b in self.buttons]}")


class FakeWidget:
    """显式方法面替身(未列方法 → AttributeError,fail-closed)。"""

    def __init__(self, rec: _Recorder, *a, **k) -> None:
        self._rec = rec
        self.tk_class: str = ""      # 类名标签(install 工厂回填;of_class 检索基)
        self.text: str = k.get("text", "")
        self.command = k.get("command")
        self.bg = k.get("bg")
        self.fg = k.get("fg")
        self.geo: str | None = None
        self.pack_count: int = 0
        self.create_line_calls: list = []
        self._text_value: str = ""
        # ISS-0109 widget 级扩展面(TC-ICON 字形/画布族观测):bind/after/
        # after_cancel 的实例级记录
        self.handlers: dict = {}
        self.afters: list = []       # 实例级 after ms 序列(rec.afters 双轨)
        self.cancelled: list = []
        rec.widgets.append(self)

    # ---- 布局/事件 ----
    def pack(self, *a, **k):
        self.pack_count += 1

    def place(self, *a, **k):
        self._rec.places.append((self.text, dict(k)))

    def grid(self, *a, **k):
        pass

    def pack_forget(self):
        pass

    def bind(self, *a, **k):
        if len(a) >= 2:
            self.handlers[a[0]] = a[1]      # ISS-0109:bind 序列→回调记录

    def bind_all(self, *a, **k):
        pass

    def focus_set(self):
        pass

    def lower(self, *a):
        pass

    def lift(self, *a):
        pass

    # ---- 配置 ----
    def configure(self, **k):
        if "text" in k:
            self.text = k["text"]
            self._rec.label_updates.append(self.text)
        if "command" in k:
            self.command = k["command"]
        if "bg" in k:
            self.bg = k["bg"]
        if "fg" in k:
            self.fg = k["fg"]

    config = configure

    def cget(self, key):
        return self.text if key == "text" else ""

    # ---- 窗口属性 ----
    def title(self, *a):
        pass

    def overrideredirect(self, *a):
        pass

    def attributes(self, flag, val=None):
        if flag == "-alpha":
            self._rec.alphas.append(val)

    def geometry(self, spec):
        self.geo = spec
        self._rec.geometries.append(spec)

    def minsize(self, *a):
        pass

    def protocol(self, name, *a):
        self._rec.protocols.append(name)

    def resizable(self, *a):
        pass

    # ---- 调度 ----
    def after(self, ms, fn=None):
        self._rec.afters.append((ms, fn))
        self.afters.append(ms)              # ISS-0109:实例级 ms 序列
        return f"a{len(self._rec.afters)}"       # 令牌形态统一("a1"先例)

    def after_cancel(self, *a):
        self.cancelled.extend(a)            # ISS-0109:取消记录

    def destroy(self):
        self._rec.destroys += 1
        self._rec.destroyed_widgets.append(self)

    def update_idletasks(self):
        self._rec.idletasks += 1

    def mainloop(self):
        pass

    def quit(self):
        pass

    def withdraw(self):
        pass

    def deiconify(self):
        pass

    # ---- winfo ----
    def winfo_reqheight(self):
        return self._rec.reqheight

    def winfo_screenwidth(self):
        return self._rec.screen[0]

    def winfo_screenheight(self):
        return self._rec.screen[1]

    def winfo_children(self):
        return []

    def winfo_rootx(self):
        return 0

    def winfo_rooty(self):
        return 0

    def winfo_height(self):
        return self._rec.reqheight

    # ---- Canvas ----
    def yview(self, *a, **k):
        pass

    def yview_scroll(self, *a, **k):
        pass

    def create_window(self, *a, **k):
        return 1

    def create_line(self, *a, **k):
        self.create_line_calls.append((a, k))

    def create_rectangle(self, *a, **k):
        pass

    def create_oval(self, *a, **k):
        pass

    def create_polygon(self, *a, **k):
        pass

    def itemconfig(self, *a, **k):
        pass

    def bbox(self, *a, **k):
        return (0, 0, 0, 0)

    def delete(self, *a, **k):
        pass

    # ---- Entry ----
    def get(self):
        return self._text_value

    def set(self, v):
        self._text_value = v


class _FakeButton(FakeWidget):
    def __init__(self, rec, *a, **k):
        super().__init__(rec, *a, **k)
        rec.buttons.append(self)
        rec.button_texts.append(self.text)


class _FakeLabel(FakeWidget):
    def __init__(self, rec, *a, **k):
        super().__init__(rec, *a, **k)
        rec.labels.append(self.text)
        rec.label_updates.append(self.text)


class _FakeToplevel(FakeWidget):
    def __init__(self, rec, *a, **k):
        super().__init__(rec, *a, **k)
        rec.tops.append(self)


def install(monkeypatch, tk_module, screen=(2560, 1440), reqheight=100):
    """一次替换 tk 模块的控件类为替身,返回 recorder(观测口)。

    screen/reqheight 按各测试原校准值传参(裁决③,断言值不动)。
    ISS-0109:补 Tk 根窗类(TC-95-03/TC-SINGLE 壳收编);实例打 tk_class
    类名标签(of_class 检索)。
    """
    rec = _Recorder(screen, reqheight)

    def _mk(name, cls):
        def _factory(*a, **k):
            w = cls(rec, *a, **k)
            w.tk_class = name
            return w
        return _factory

    monkeypatch.setattr(tk_module, "Toplevel", _mk("Toplevel", _FakeToplevel))
    for cls in ("Tk", "Frame", "Canvas", "Scrollbar", "Entry", "Listbox"):
        monkeypatch.setattr(tk_module, cls, _mk(cls, FakeWidget))
    monkeypatch.setattr(tk_module, "Button", _mk("Button", _FakeButton))
    monkeypatch.setattr(tk_module, "Label", _mk("Label", _FakeLabel))
    return rec


# ---- TC-FAKETK-GUARD 扫描面(守卫用例与本库共用同一规则源) ----

GUARD_ALLOW = {"faketk.py", "test_faketk.py"}
GUARD_BANNED_CLASS = re.compile(
    r"^\s*class (W|Btn|Lbl|Top|FakeWin|_Recorder|_TkRig|_FakeWidget)\b",
    re.MULTILINE)
GUARD_BANNED_PATCH = re.compile(
    r"monkeypatch\.setattr\([^)]*\.tk,\s*"
    r"\"(?:Toplevel|Frame|Label|Button|Canvas|Scrollbar|Entry|Listbox)\"")
GUARD_BANNED_TYPE = re.compile(r'type\("W",')
GUARD_EXEMPT_MARK = "faketk-guard:豁免"
