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


def _draw_empty_icon(cv, color: str = "#CCCCCC") -> None:
    """空态插画：灰调细线"托盘"图标（与尖角/禁止同语言）。"""
    cv.create_rectangle(4, 10, 36, 28, outline=color, width=1.5)
    cv.create_line(4, 18, 14, 18, fill=color, width=1.5, capstyle="round")
    cv.create_line(26, 18, 36, 18, fill=color, width=1.5, capstyle="round")
    cv.create_line(14, 18, 18, 23, fill=color, width=1.5, capstyle="round")
    cv.create_line(26, 18, 22, 23, fill=color, width=1.5, capstyle="round")


class _EmptyState:
    """空态组件（业界标准：灰调插画+主标题+副提示，居中）；
    整块替换滚动区——占位符永不进入 Canvas（TC-EMPTY-02）。"""

    def __init__(self, parent, title: str, hint: str):
        self.frame = tk.Frame(parent, bg=_BG)
        inner = tk.Frame(self.frame, bg=_BG)
        inner.pack(expand=True, pady=24)
        self._cv = tk.Canvas(inner, width=40, height=32, bg=_BG,
                             highlightthickness=0)
        self._cv.pack()
        _draw_empty_icon(self._cv)
        self._title = tk.Label(inner, text=title, bg=_BG, fg="#999999",
                               font=("Microsoft YaHei", 10, "bold"))
        self._title.pack(pady=(8, 0))
        self._hint = tk.Label(inner, text=hint, bg=_BG, fg="#BBBBBB",
                              font=("Microsoft YaHei", 8), wraplength=380,
                              justify="center")
        self._hint.pack(pady=(4, 0))

    def set_state(self, title: str, hint: str) -> None:
        self._title.configure(text=title)
        self._hint.configure(text=hint)

    def pack(self, *a, **k):
        self.frame.pack(*a, **k)

    def pack_forget(self) -> None:
        self.frame.pack_forget()


def _draw_chevron(canvas, direction: str, color: str) -> None:
    """Fluent 风细线尖角：down=收拢(更多)，up=展开(收起)；1.5px 圆角描边。"""
    canvas.delete("chev")
    if direction == "down":
        pts = (1, 1, 6, 6, 11, 1)
    else:
        pts = (1, 6, 6, 1, 11, 6)
    canvas.create_line(*pts, fill=color, width=1.5,
                       capstyle="round", joinstyle="round", tags="chev")


class _GraphicButton:
    """图形按钮统一基类（通用性原则：尖角/禁止/…都是绘制回调的入参，
    不再新增 bespoke 按钮类）。子类实现 _draw(color) 与可选的悬停行为。"""

    def __init__(self, parent, command, tooltip: str = "",
                 width: int = 22, height: int = 22):
        self.command = command
        self.frame = tk.Frame(parent, bg=_BG, cursor="hand2")
        self.cv = tk.Canvas(self.frame, width=width, height=height, bg=_BG,
                            highlightthickness=0, cursor="hand2")
        self.cv.pack()
        for w in (self.frame, self.cv):
            w.bind("<Button-1>", lambda e: self.command())
        if tooltip:
            _Tooltip(self.frame, tooltip)

    def pack(self, *a, **k):
        self.frame.pack(*a, **k)

    def pack_forget(self) -> None:
        self.frame.pack_forget()


def fade_in(win, total_ms: int = 120, step_ms: int = 20):
    """窗口淡入（通用助手）：alpha 0→1 按 step_ms 步进。

    返回帧生成器（测试观测口：消费即逐帧应用并产出 alpha 值）；
    有 after 能力的窗口同时按步进调度驱动。
    """
    steps = max(1, total_ms // step_ms)

    def frames():
        for i in range(steps + 1):
            yield round(i / steps, 3)

    def apply(a: float) -> None:
        win.attributes("-alpha", a)

    apply(0.0)
    after = getattr(win, "after", None)
    if callable(after):
        def drive(i: int) -> None:
            apply(round(i / steps, 3))
            if i < steps:
                after(step_ms, lambda: drive(i + 1))
        drive(1)
    return (a for a in frames() if not apply(a))


def focus_existing_or_exit(title: str) -> bool:
    """单例语义（通用助手）：已存在同名顶层窗口则聚焦并返回 True。"""
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)           # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    return False


class _ChevronButton(_GraphicButton):
    """尖角图标按钮（▼ 更多 / ▲ 收起）：_GraphicButton 的尖角绘制变体。"""

    def __init__(self, parent, command):
        super().__init__(parent, command, tooltip="", width=12, height=8)
        self.direction = "down"
        self.label = tk.Label(self.frame, text="", bg=_BG, fg="#666666",
                              font=("Microsoft YaHei", 9), cursor="hand2")
        self.label.pack(side="left", padx=(4, 0))
        _draw_chevron(self.cv, "down", "#666666")
        for w in (self.frame, self.cv, self.label):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", lambda e: self._set_color("#202020"))
            w.bind("<Leave>", lambda e: self._set_color("#666666"))

    def _set_color(self, color: str) -> None:
        self.label.configure(fg=color)
        _draw_chevron(self.cv, self.direction, color)

    def set_state(self, text: str, direction: str) -> None:
        self.direction = direction
        self.label.configure(text=text)
        _draw_chevron(self.cv, direction, "#666666")


class _IconButton(_GraphicButton):
    """行内图标按钮（系统 ⛔ 字形；悬停字号脉冲动效）。

    instances：类级注册表（测试观测口）。
    _base_size / _current_size()：动效状态观测口（TC-ICON-02 断言点）。
    """

    instances: list = []

    _STEP_MS = 40

    def __init__(self, parent, action: str, tooltip: str, command):
        super().__init__(parent, command, tooltip=tooltip)
        self.action = action
        # A 方案:系统 ⛔ 字形(Segoe UI Emoji),弃手绘像素图;悬停=字号脉冲
        self.cv.pack_forget()
        self._base_size = 12
        self._size = self._base_size
        self._step = 0
        self._anim_id = None
        self.glyph = tk.Label(self.frame, text="⛔", bg=_BG, fg="#202020",
                              font=("Segoe UI Emoji", self._base_size),
                              cursor="hand2")
        self.glyph.pack()
        self.glyph.bind("<Button-1>", lambda e: self.command())
        self.glyph.bind("<Enter>", self._on_enter)
        self.glyph.bind("<Leave>", self._on_leave)
        _IconButton.instances.append(self)

    # ---- 观测口 ----

    def _current_size(self) -> int:
        return self._size

    # ---- 动效（字号脉冲 12→15,40ms 步进） ----

    _PULSE = (13, 14, 15)

    def _set_size(self, size: int) -> None:
        self._size = size
        self.glyph.configure(font=("Segoe UI Emoji", size))

    def _on_enter(self, _e=None) -> None:
        self.glyph.configure(fg="#C8391F")         # 悬停红(TC-COLOR-02)
        self._cancel_anim()
        self._step = 0
        self._animate_in()

    def _animate_in(self) -> None:
        if self._step < len(self._PULSE):
            self._set_size(self._PULSE[self._step])
            self._step += 1
            self._anim_id = self.glyph.after(self._STEP_MS, self._animate_in)

    def _on_leave(self, _e=None) -> None:
        self._cancel_anim()
        self.glyph.configure(fg="#202020")         # 回常态黑(TC-COLOR-02)
        self._set_size(self._base_size)

    def _cancel_anim(self) -> None:
        if self._anim_id is not None:
            try:
                self.glyph.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    # ---- 观测口 ----

    def _current_size(self) -> int:
        return self._size


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

    def __init__(self, win, entries: dict, on_remove, on_clear_session,
                 display_map: dict | None = None):
        self._entries = entries
        self._on_remove = on_remove
        self._dmap = display_map or {}          # {proc: (display, desc)} 端点直供
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

    _EMPTY_TEXT = {
        "static": ("暂无永久加入的软件",
                   "AI 请求新应用时，在弹窗选「永久加入」即可出现在这里"),
        "session": ("本次会话暂无临时允许",
                    "「本次会话允许」的应用会列在这里，重启后自动清空"),
    }

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
        return {"wrap": wrap, "canvas": canvas, "body": body, "more": more,
                "canvas_packed": False, "empty": None}

    # ---- 渲染 ----

    def _filtered(self, items: dict) -> list[tuple[str, str, str, str]]:
        """[(proc, level, display, desc)]；display_map 直供时零解析(TC-FAST-02)。"""
        out = []
        for proc, level in items.items():
            display, desc = self._dmap.get(proc, (None, None))
            if display is None:
                from .appnames import app_display_name
                display = app_display_name(proc)
            q = self._query
            if q and q not in display.lower() and q not in proc.lower():
                continue
            out.append((proc, level, display, desc))
        return out

    def render(self) -> None:
        for key, _title in self._SECTIONS:
            self._render_block(key)

    def _render_block(self, key: str) -> None:
        blk = self._blocks[key]
        rows = self._filtered(self._entries.get(key, {}))
        expanded = self._expanded[key] or bool(self._query)
        visible = rows if expanded else rows[:_VISIBLE_N]

        if not visible:
            # 空态:整块替换滚动区(占位符永不进 Canvas,TC-EMPTY-02)
            if blk["canvas_packed"]:
                blk["canvas"].pack_forget()
                blk["canvas_packed"] = False
            title, hint = (("无匹配项", "换个关键词试试") if self._query
                           else self._EMPTY_TEXT[key])
            if blk["empty"] is None:
                blk["empty"] = _EmptyState(blk["wrap"], title, hint)
            else:
                blk["empty"].set_state(title, hint)
            blk["empty"].pack(fill="both", expand=True)
        else:
            if blk["empty"] is not None:
                blk["empty"].pack_forget()
            if not blk["canvas_packed"]:
                blk["canvas"].pack(side="left", fill="x", expand=True)
                blk["canvas_packed"] = True
            body = blk["body"]
            for child in body.winfo_children():
                child.destroy()
            for proc, level, display, desc in visible:
                _row(body, proc, level, display, self._on_remove, desc)

        rest = len(rows) - _VISIBLE_N
        more = blk["more"]
        if not self._query and rest > 0:
            more.command = (lambda k=key: self._toggle(k))
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
                 on_clear_session: Callable[[], None],
                 display_map: dict | None = None):
    """ISS-0012 §6 E2：白名单管理窗口（v2：两区分立滚动+默认5条更多+搜索）。

    entries = {"static": {proc: level}, "session": {proc: level}}；
    display_map = {proc: (display, desc)}（/whitelist 端点直供时零解析提速,
    TC-FAST-02/03）；缺省回退 appnames 本地解析。
    行主名显示应用显示名，次行进程名·级别，三行描述；
    顶部搜索实时过滤；每区默认 5 条，[更多 N 项]/[收起]；
    控制器挂 win._manager（测试观测口）。
    """
    win = tk.Toplevel(parent)
    win.title("DeskPilot 白名单管理")
    win.geometry("560x560")
    win.minsize(460, 420)
    win.configure(bg=_BG)
    win._manager = _ManagerUI(win, entries, on_remove, on_clear_session,
                              display_map=display_map)
    fade_in(win)                                   # TC-ANIM:淡入动效
    return win


def _row(parent, proc: str, level: str, display: str, on_remove,
         desc: str | None = None) -> None:
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
    if desc is None:
        from .appnames import app_description
        desc = app_description(proc)
    if desc:                                    # 空描述省略第三行(TC-DESC-03)
        tk.Label(left, text=_truncate(desc), bg=_BG, fg=_HINT_FG,
                 font=("Microsoft YaHei", 8), anchor="w").pack(fill="x")
    btn = _IconButton(row, action="remove", tooltip="移出白名单",
                      command=lambda p=proc: on_remove(p))
    btn.pack(side="right", padx=(10, 0))
    tk.Frame(parent, bg=_SEP, height=1).pack(fill="x", pady=(4, 0))


def _truncate(text: str, n: int = 40) -> str:
    """描述截断：压缩空白后 ≤n 字，超出补省略号(TC-DESC-02)。"""
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[:n] + "…"


# ---------- E4 入白确认 toast ----------

_DARK = "#2B2B2B"
_ACTION_BLUE = "#8AB4F8"          # Material dark snackbar 动作色
_CONFIRM_GREEN = "#81C995"


def build_enroll_notice(parent, process: str, on_undo: Callable[[], None]):
    """ISS-0012 §6 E4 v2（Gmail/Material 模式，TC-UNDO-01~06）。

    深色卡片；8s 自动消失；× 立即关闭；「撤销」为亮蓝文字动作按钮；
    点撤销 → 执行 on_undo + 切绿色确认态「✓ 已撤销」1.5s 后自动消失。
    """
    win = tk.Toplevel(parent)
    win.title("DeskPilot")
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=_DARK)

    card = tk.Frame(win, bg=_DARK)
    card.pack(fill="both", expand=True)
    body = tk.Frame(card, bg=_DARK)
    body.pack(fill="both", expand=True, padx=14, pady=10)

    msg = tk.Label(body, text=f"已加入白名单：{process}", bg=_DARK,
                   fg="#FFFFFF", font=("Microsoft YaHei", 10), anchor="w")
    msg.pack(side="left")

    def _dismiss() -> None:
        try:
            win.destroy()
        except Exception:
            pass

    def _confirm_then_dismiss() -> None:
        msg.configure(text="✓ 已撤销，已移出白名单", fg=_CONFIRM_GREEN)
        undo_btn.pack_forget()
        win.after(1500, _dismiss)

    def _undo() -> None:
        try:
            on_undo()
        finally:
            _confirm_then_dismiss()

    close = tk.Button(body, text="×", relief="flat", bd=0, bg=_DARK,
                      fg="#BDBDBD", activebackground=_DARK,
                      activeforeground="#FFFFFF",
                      font=("Microsoft YaHei", 10), cursor="hand2",
                      command=_dismiss)
    close.pack(side="right", padx=(8, 0))
    undo_btn = tk.Button(body, text="撤销", relief="flat", bd=0, bg=_DARK,
                         fg=_ACTION_BLUE, activebackground=_DARK,
                         activeforeground="#A8C7FA",
                         font=("Microsoft YaHei", 10, "bold"),
                         cursor="hand2", command=_undo)
    undo_btn.pack(side="right", padx=(12, 0))

    win.geometry(f"{_WIDTH}x48+{win.winfo_screenwidth() - _WIDTH - 16}+40")
    win.after(8000, _dismiss)                    # 8s 自动消失（业界 4~10s 档）
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
    """--whitelist-manager <base_url>：管理窗口进程（经本机 HTTP 操作）。

    单例语义（TC-SINGLE）：已存在管理窗口则聚焦并退出，不再开新窗。
    """
    if focus_existing_or_exit("DeskPilot 白名单管理"):
        return
    base = sys.argv[1].rstrip("/")
    root = tk.Tk()
    root.withdraw()

    state: dict[str, Any] = {"win": None}

    def refresh() -> None:
        try:
            data = _http_json(f"{base}/whitelist")["data"]
            entries: dict = {}
            dmap: dict = {}
            for group, items in data.items():
                entries[group] = {}
                for it in items:
                    entries[group][it["process"]] = it["level"]
                    dmap[it["process"]] = (it.get("display") or None,
                                           it.get("desc") or None)
        except Exception:
            entries, dmap = {"static": {}, "session": {}}, {}
        if state["win"] is not None:
            try:
                state["win"].destroy()
            except Exception:
                pass
        state["win"] = build_window(root, entries, on_remove, on_clear,
                                    display_map=dmap)
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
