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
        sb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="x", expand=True)
        body = tk.Frame(canvas, bg=_BG)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e, c=canvas, i=body_id: c.itemconfig(i, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e, c=canvas: c.yview_scroll(
                            int(-e.delta / 120), "units"))

        foot = tk.Frame(win, bg=_BG)
        foot.pack(fill="x", padx=16)
        more = tk.Button(foot, text="", width=12, relief="flat", bg=_BTN_BG,
                         fg=_TITLE_FG, font=("Microsoft YaHei", 9),
                         cursor="hand2")
        more.pack(side="left", pady=4)
        _hover(more, _BTN_BG, _BTN_HOVER)
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
            more.configure(
                text=("收起" if self._expanded[key] else f"更多 {rest} 项"),
                command=lambda k=key: self._toggle(k))
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
    row = tk.Frame(parent, bg=_BG)
    row.pack(fill="x", pady=(4, 0))
    left = tk.Frame(row, bg=_BG)
    left.pack(side="left", fill="x", expand=True)
    tk.Label(left, text=display, bg=_BG, fg=_TITLE_FG,
             font=("Microsoft YaHei", 10, "bold"),
             anchor="w").pack(fill="x")
    tk.Label(left, text=f"{proc} · {level}", bg=_BG, fg=_HINT_FG,
             font=("Microsoft YaHei", 8), anchor="w").pack(fill="x")
    btn = tk.Button(row, text="移出", width=7, relief="flat", bg=_BTN_BG,
                    fg=_REMOVE_FG, font=("Microsoft YaHei", 9),
                    cursor="hand2",
                    command=lambda p=proc: on_remove(p))
    btn.pack(side="right", padx=(10, 0))
    _hover(btn, _BTN_BG, _BTN_HOVER)
    tk.Frame(parent, bg=_SEP, height=1).pack(fill="x", pady=(4, 0))


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
