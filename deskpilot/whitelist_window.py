"""白名单管理窗口、入白确认 toast、撤回确认通道（ISS-0012 §6 E2/E3/E4）。

- build_window：管理窗口——静态/会话分组列出，逐行 [移出]、会话区 [全部清空]；
- build_enroll_notice：E4 入白确认 toast「已加入白名单 [撤销]」；
- build_revoke_confirm：E3 撤回确认窗「是否移出 X？[移出/保留]」，倒计时默认保留；
- DialogRevokeChannel：E3 生产确认通道（经弹窗线程服务 + 结果文件回传）；
- main：--whitelist-manager <base_url> 进程入口（经本机 HTTP 拉取/操作）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import tkinter as tk

_TITLE_FONT = ("Microsoft YaHei", 11, "bold")
_TEXT_FONT = ("Microsoft YaHei", 10)
_HINT_FONT = ("Microsoft YaHei", 8)

_WIDTH = 420


# ---------- E2 管理窗口 ----------

_BG = "#FFFFFF"
_TITLE_FG = "#202020"
_HINT_FG = "#999999"
_SEP = "#EFEFEF"
_BTN_BG = "#F4F4F4"
_BTN_HOVER = "#FBE3DD"
_REMOVE_FG = "#C8391F"
_ROW_H = 52                      # 行高（双行文本+分隔线）
_VISIBLE_N = 5                   # 每区默认展示条数，超出经[更多]展开


def _hover(btn, base: str, hover: str) -> None:
    btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
    btn.bind("<Leave>", lambda e: btn.configure(bg=base))


def _wheelable(canvas) -> None:
    """滚轮只作用于鼠标悬停的滚动区（修复全局绑定被后注册者通吃）。"""
    canvas.bind("<Enter>",
                lambda e, c=canvas: c.bind_all(
                    "<MouseWheel>",
                    lambda ev: c.yview_scroll(int(-ev.delta / 120), "units")))
    canvas.bind("<Leave>",
                lambda e, c=canvas: c.unbind_all("<MouseWheel>"))


def _draw_chevron(canvas, direction: str, color: str) -> None:
    """Fluent 风细线尖角：down=收拢(更多)，up=展开(收起)；1.5px 圆角描边。"""
    canvas.delete("chev")
    if direction == "down":
        pts = (1, 1, 6, 6, 11, 1)
    else:
        pts = (1, 6, 6, 1, 11, 6)
    canvas.create_line(*pts, fill=color, width=1.5,
                       capstyle="round", joinstyle="round", tags="chev")


class _ChevronButton:
    """尖角图标按钮（▼ 更多 / ▲ 收起）：无底色、悬停变色、点击整行。"""

    def __init__(self, parent, command):
        self._command = command
        self.direction = "down"
        self.frame = tk.Frame(parent, bg=_BG, cursor="hand2")
        self.chevron = tk.Canvas(self.frame, width=12, height=8, bg=_BG,
                                 highlightthickness=0, cursor="hand2")
        self.chevron.pack(side="left", pady=(3, 0))
        self.label = tk.Label(self.frame, text="", bg=_BG, fg="#666666",
                              font=("Microsoft YaHei", 9), cursor="hand2")
        self.label.pack(side="left", padx=(4, 0))
        _draw_chevron(self.chevron, "down", "#666666")
        for w in (self.frame, self.chevron, self.label):
            w.bind("<Button-1>", lambda e: self._command())
            w.bind("<Enter>", lambda e: self._set_color("#202020"))
            w.bind("<Leave>", lambda e: self._set_color("#666666"))

    def _set_color(self, color: str) -> None:
        self.label.configure(fg=color)
        _draw_chevron(self.chevron, self.direction, color)

    def set_state(self, text: str, direction: str) -> None:
        self.direction = direction
        self.label.configure(text=text)
        _draw_chevron(self.chevron, direction, "#666666")

    def pack(self, *a, **k):
        self.frame.pack(*a, **k)

    def pack_forget(self) -> None:
        self.frame.pack_forget()


class _IconButton:
    """行内图标按钮（禁止样式 ⛔：圆环+粗横杆；悬停动效：灰→红+横杆划入）。

    业界语义：禁止/移出关联（UX.SE/NNg 共识）；icon-only 配悬浮提示（SSW）。
    instances：类级注册表（测试观测口）。
    _base_color / _current_color()：动效状态观测口（TC-ICON-02 断言点）。
    """

    instances: list = []

    _BASE = "#999999"
    _HOVER = "#C8391F"
    _STEPS = 6
    _STEP_MS = 40

    def __init__(self, parent, action: str, tooltip: str, command):
        self.action = action
        self.command = command
        self._base_color = self._BASE
        self._color = self._BASE
        self._step = 0
        self._anim_id = None
        self.frame = tk.Frame(parent, bg=_BG, cursor="hand2")
        self.cv = tk.Canvas(self.frame, width=22, height=22, bg=_BG,
                            highlightthickness=0, cursor="hand2")
        self.cv.pack()
        self._draw_static(self._BASE)
        for w in (self.frame, self.cv):
            w.bind("<Button-1>", lambda e: self.command())
        self.cv.bind("<Enter>", self._on_enter)
        self.cv.bind("<Leave>", self._on_leave)
        _Tooltip(self.frame, tooltip)          # 提示绑 frame,避免与动效抢绑定
        _IconButton.instances.append(self)

    # ---- 观测口 ----

    def _current_color(self) -> str:
        return self._color

    # ---- 绘制 ----

    def _draw_static(self, color: str) -> None:
        self._color = color
        self.cv.delete("x")
        self.cv.create_oval(3, 3, 19, 19, outline=color, width=1.8, tags="x")
        self.cv.create_line(6.5, 11, 15.5, 11, fill=color, width=2.5,
                            capstyle="round", tags="x")

    def _draw_frame(self, color: str, frac: float) -> None:
        self._color = color
        self.cv.delete("x")
        self.cv.create_oval(3, 3, 19, 19, outline=color, width=1.8, tags="x")
        # 横杆自左向右划入
        self.cv.create_line(6.5, 11, 6.5 + 9.0 * frac, 11, fill=color,
                            width=2.5, capstyle="round", tags="x")

    # ---- 动效 ----

    def _on_enter(self, _e=None) -> None:
        self._cancel_anim()
        self._step = 0
        self._animate_in()

    def _animate_in(self) -> None:
        self._step += 1
        frac = self._step / self._STEPS
        self._draw_frame(_mix_hex(self._BASE, self._HOVER, frac), frac)
        if self._step < self._STEPS:
            self._anim_id = self.cv.after(self._STEP_MS, self._animate_in)

    def _on_leave(self, _e=None) -> None:
        self._cancel_anim()
        self._draw_static(self._BASE)

    def _cancel_anim(self) -> None:
        if self._anim_id is not None:
            try:
                self.cv.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    def pack(self, *a, **k):
        self.frame.pack(*a, **k)


def _mix_hex(c1: str, c2: str, frac: float) -> str:
    """两个 #RRGGBB 颜色按 frac 线性插值。"""
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    m = tuple(round(a[i] + (b[i] - a[i]) * frac) for i in range(3))
    return f"#{m[0]:02x}{m[1]:02x}{m[2]:02x}"


class _Tooltip:
    """行悬浮提示：悬停 500ms 浮出描述气泡，移开即消。"""

    def __init__(self, widget, text: str):
        self._w = widget
        self._text = text
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)

    def _schedule(self, _e) -> None:
        self._after_id = self._w.after(500, self._show)

    def _show(self) -> None:
        if self._tip is not None or not self._text:
            return
        tip = tk.Toplevel(self._w)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg="#2B2B2B")
        tk.Label(tip, text=self._text, bg="#2B2B2B", fg="#FFFFFF",
                 font=("Microsoft YaHei", 9), wraplength=300,
                 justify="left", anchor="w").pack(padx=10, pady=6)
        x = self._w.winfo_rootx() + 24
        y = self._w.winfo_rooty() + self._w.winfo_height() + 6
        tip.geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _e) -> None:
        if self._after_id is not None:
            try:
                self._w.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class _ManagerUI:
    """白名单管理窗口控制器：搜索过滤 + 两区分立滚动 + 更多/收起。"""

    _SECTIONS = (("static", "已永久加入（写入白名单文件）"),
                 ("session", "本次会话临时允许（重启失效）"))

    def __init__(self, win, entries: dict, on_remove, on_clear_session):
        self._entries = entries
        self._on_remove = on_remove
        self._query = ""
        self._expanded = {"static": False, "session": False}
        self._blocks: dict[str, dict] = {}

        header = tk.Frame(win, bg=_BG)
        header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(header, text="白名单管理", bg=_BG, fg=_TITLE_FG,
                 font=("Microsoft YaHei", 13, "bold"),
                 anchor="w").pack(side="left")
        self._search = tk.Entry(header, width=18, relief="solid", bd=1,
                                font=("Microsoft YaHei", 9))
        self._search.pack(side="right")
        self._search.bind("<KeyRelease>", self._on_search)
        tk.Label(header, text="搜索", bg=_BG, fg=_HINT_FG,
                 font=("Microsoft YaHei", 9)).pack(side="right", padx=(0, 6))

        for key, title in self._SECTIONS:
            self._blocks[key] = self._build_block(win, title)

        bar = tk.Frame(win, bg=_BG)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        clear = tk.Button(bar, text="全部清空", width=10, relief="flat",
                          bg=_BTN_BG, fg=_REMOVE_FG, font=_TEXT_FONT,
                          cursor="hand2", command=on_clear_session)
        clear.pack(side="right")
        _hover(clear, _BTN_BG, _BTN_HOVER)

        self.render()

    # ---- 骨架 ----

    def _build_block(self, win, title: str) -> dict:
        head = tk.Frame(win, bg=_BG)
        head.pack(fill="x", padx=16, pady=(8, 2))
        tk.Label(head, text=title, bg=_BG, fg=_TITLE_FG,
                 font=("Microsoft YaHei", 10, "bold"),
                 anchor="w").pack(side="left")

        wrap = tk.Frame(win, bg=_BG)
        wrap.pack(fill="x", padx=16)
        canvas = tk.Canvas(wrap, bg=_BG, highlightthickness=0,
                           height=_ROW_H * _VISIBLE_N)
        canvas.pack(side="left", fill="x", expand=True)
        body = tk.Frame(canvas, bg=_BG)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e, c=canvas, i=body_id: c.itemconfig(i, width=e.width))
        _wheelable(canvas)

        foot = tk.Frame(win, bg=_BG)
        foot.pack(fill="x", padx=16)
        more = _ChevronButton(foot, command=lambda k=None: None)
        return {"canvas": canvas, "body": body, "more": more}

    # ---- 渲染 ----

    def _filtered(self, items: dict) -> list[tuple[str, str, str]]:
        """[(proc, level, display)]；搜索串同时匹配显示名与进程名。"""
        from .appnames import app_display_name
        out = []
        for proc, level in items.items():
            display = app_display_name(proc)
            q = self._query
            if q and q not in display.lower() and q not in proc.lower():
                continue
            out.append((proc, level, display))
        return out

    def render(self) -> None:
        for key, _title in self._SECTIONS:
            self._render_block(key)

    def _render_block(self, key: str) -> None:
        blk = self._blocks[key]
        body = blk["body"]
        for child in body.winfo_children():
            child.destroy()
        rows = self._filtered(self._entries.get(key, {}))
        expanded = self._expanded[key] or bool(self._query)
        visible = rows if expanded else rows[:_VISIBLE_N]
        if not visible:
            tk.Label(body, text="（空）" if not self._query else "（无匹配）",
                     bg=_BG, fg=_HINT_FG, font=_HINT_FONT,
                     anchor="w").pack(fill="x", pady=2)
        for proc, level, display in visible:
            _row(body, proc, level, display, self._on_remove)

        rest = len(rows) - _VISIBLE_N
        more = blk["more"]
        if not self._query and rest > 0:
            more._command = (lambda k=key: self._toggle(k))
            if self._expanded[key]:
                more.set_state("收起", "up")
            else:
                more.set_state(f"更多 {rest} 项", "down")
            more.pack(side="left", pady=4)
        else:
            more.pack_forget()

    def _toggle(self, key: str) -> None:
        self._expanded[key] = not self._expanded[key]
        self._render_block(key)

    def _on_search(self, _event) -> None:
        self._query = self._search.get().strip().lower()
        self.render()


def build_window(parent, entries: dict, on_remove: Callable[[str], None],
                 on_clear_session: Callable[[], None]):
    """ISS-0012 §6 E2：白名单管理窗口（v2：两区分立滚动+默认5条更多+搜索）。

    entries = {"static": {proc: level}, "session": {proc: level}}；
    行主名显示应用显示名（与审批弹窗同源），次行进程名·级别；
    顶部搜索实时过滤（匹配显示名/进程名）；每区默认 5 条，
    [更多 N 项] 展开全部、[收起] 还原；控制器挂 win._manager（测试观测口）。
    """
    win = tk.Toplevel(parent)
    win.title("DeskPilot 白名单管理")
    win.geometry("560x560")
    win.minsize(460, 420)
    win.configure(bg=_BG)
    win._manager = _ManagerUI(win, entries, on_remove, on_clear_session)
    return win


def _row(parent, proc: str, level: str, display: str, on_remove) -> None:
    from .appnames import app_description
    row = tk.Frame(parent, bg=_BG)
    row.pack(fill="x", pady=(4, 0))
    left = tk.Frame(row, bg=_BG)
    left.pack(side="left", fill="x", expand=True)
    name_lbl = tk.Label(left, text=display, bg=_BG, fg=_TITLE_FG,
                        font=("Microsoft YaHei", 10, "bold"),
                        anchor="w")
    name_lbl.pack(fill="x")
    tk.Label(left, text=f"{proc} · {level}", bg=_BG, fg=_HINT_FG,
             font=("Microsoft YaHei", 8), anchor="w").pack(fill="x")
    btn = _IconButton(row, action="remove", tooltip="移出白名单",
                      command=lambda p=proc: on_remove(p))
    btn.pack(side="right", padx=(10, 0))
    tk.Frame(parent, bg=_SEP, height=1).pack(fill="x", pady=(4, 0))
    # 悬浮描述（OS/厂商数据源；500ms 悬停浮出）
    _Tooltip(name_lbl, app_description(proc))


# ---------- E4 入白确认 toast ----------

def build_enroll_notice(parent, process: str, on_undo: Callable[[], None]):
    """ISS-0012 §6 E4：入白确认 toast「已加入白名单 [撤销]」。

    on_undo 由装配侧接到 WhitelistAdmin.remove（误点立撤）。
    """
    win = tk.Toplevel(parent)
    win.title("DeskPilot")
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg="#FFFFFF")

    card = tk.Frame(win, bg="#FFFFFF", highlightthickness=1,
                    highlightbackground="#DDDDDD")
    card.pack(fill="both", expand=True)
    body = tk.Frame(card, bg="#FFFFFF")
    body.pack(fill="both", expand=True, padx=16, pady=12)
    tk.Label(body, text=f"已加入白名单：{process}", bg="#FFFFFF",
             font=_TEXT_FONT, anchor="w").pack(side="left")
    tk.Button(body, text="撤销", width=8, relief="flat", bg="#F0F0F0",
              font=_TEXT_FONT, cursor="hand2",
              command=on_undo).pack(side="right", padx=(12, 0))
    win.geometry(f"{_WIDTH}x48+{win.winfo_screenwidth() - _WIDTH - 16}+40")
    return win


# ---------- E3 撤回确认窗与通道 ----------

def build_revoke_confirm(parent, process: str, result_path, timeout_s: float):
    """ISS-0012 §6 E3：撤回确认窗——[移出]/[保留]，倒计时默认保留。

    裁决写结果文件："remove" / "keep" / "timeout"。
    """
    result_path = Path(result_path)
    win = tk.Toplevel(parent)
    win.title("DeskPilot 白名单")
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg="#FFFFFF")

    card = tk.Frame(win, bg="#FFFFFF", highlightthickness=1,
                    highlightbackground="#DDDDDD")
    card.pack(fill="both", expand=True)
    body = tk.Frame(card, bg="#FFFFFF")
    body.pack(fill="both", expand=True, padx=16, pady=12)

    tk.Label(body, text=f"AI 请求将「{process}」移出白名单", bg="#FFFFFF",
             font=_TITLE_FONT, anchor="w").pack(fill="x")
    remaining = [int(timeout_s)]
    timer_label = tk.Label(body, text=f"{remaining[0]} 秒后默认保留",
                           bg="#FFFFFF", fg="#888888", font=_HINT_FONT,
                           anchor="w")
    timer_label.pack(fill="x", pady=(6, 0))

    decided = [False]

    def decide(value: str) -> None:
        if decided[0]:
            return
        decided[0] = True
        try:
            result_path.write_text(value, encoding="utf-8")
        except OSError:
            pass
        win.destroy()

    bar = tk.Frame(body, bg="#FFFFFF")
    bar.pack(fill="x", pady=(12, 0))
    rm = tk.Button(bar, text="移出", width=10, relief="flat", bg="#C8391F",
                   fg="#FFFFFF", font=_TEXT_FONT, cursor="hand2",
                   command=lambda: decide("remove"))
    rm.pack(side="right")
    keep = tk.Button(bar, text="保留", width=10, relief="flat", bg="#F0F0F0",
                     font=_TEXT_FONT, cursor="hand2",
                     command=lambda: decide("keep"))
    keep.pack(side="right", padx=(0, 12))
    keep.focus_set()                       # 默认焦点在安全项（保留）
    win.bind("<Escape>", lambda e: decide("keep"))

    def tick() -> None:
        remaining[0] -= 1
        if remaining[0] <= 0:
            decide("timeout")
            return
        timer_label.config(text=f"{remaining[0]} 秒后默认保留")
        win.after(1000, tick)

    win.geometry(f"{_WIDTH}x130+{win.winfo_screenwidth() - _WIDTH - 16}+40")
    win.after(1000, tick)
    return win


class DialogRevokeChannel:
    """ISS-0012 §6 E3：生产撤回确认通道（弹窗线程服务 + 结果文件回传）。

    request(process) -> "remove" / "keep"；超时与一切异常按 "keep"
    （fail-safe：无人类明确同意不产生任何策略变更）。
    """

    _POLL_INTERVAL = 0.1

    def __init__(self, dialog_service, timeout: float = 15.0,
                 clock: Callable[[], float] = time.monotonic,
                 result_root: str | None = None, audit_paths=None):
        self._ds = dialog_service
        self._timeout = timeout
        self._clock = clock
        self._audit_paths = audit_paths
        self._result_root = Path(result_root) if result_root else Path(
            sys.executable).parent.parent
        self.last_request: dict[str, str] | None = None   # 测试观测口

    def request(self, process: str) -> str:
        request_id = uuid.uuid4().hex[:16]
        base_dir = (self._audit_paths.approval if self._audit_paths is not None
                    else self._result_root)
        result_path = base_dir / f"deskpilot-revoke-{request_id}.result"
        self.last_request = {"process": process, "result_path": str(result_path)}
        try:
            self._ds.show("revoke", {"process": process,
                                     "result_path": str(result_path),
                                     "timeout_s": self._timeout})
        except Exception:
            return "keep"
        deadline = self._clock() + self._timeout + 1.0
        while self._clock() < deadline:
            try:
                if result_path.exists():
                    decision = result_path.read_text(encoding="utf-8").strip()
                    result_path.unlink(missing_ok=True)
                    if decision in ("remove", "keep", "timeout"):
                        return "keep" if decision == "timeout" else decision
                    return "keep"      # 非法内容按保留（fail-safe）
            except OSError:
                return "keep"
            time.sleep(self._POLL_INTERVAL)
        return "keep"


# ---------- --whitelist-manager 进程入口 ----------

def _http_json(url: str, payload: dict | None = None) -> dict:
    if payload is None:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    """--whitelist-manager <base_url>：管理窗口进程（经本机 HTTP 操作）。"""
    base = sys.argv[1].rstrip("/")
    root = tk.Tk()
    root.withdraw()

    state: dict[str, Any] = {"win": None}

    def refresh() -> None:
        try:
            entries = _http_json(f"{base}/whitelist")["data"]
        except Exception:
            entries = {"static": {}, "session": {}}
        if state["win"] is not None:
            try:
                state["win"].destroy()
            except Exception:
                pass
        state["win"] = build_window(root, entries, on_remove, on_clear)
        state["win"].protocol("WM_DELETE_WINDOW", root.quit)

    def on_remove(proc: str) -> None:
        try:
            _http_json(f"{base}/whitelist/remove", {"process": proc})
        except Exception:
            pass
        refresh()

    def on_clear() -> None:
        try:
            _http_json(f"{base}/whitelist/clear_session", {})
        except Exception:
            pass
        refresh()

    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
