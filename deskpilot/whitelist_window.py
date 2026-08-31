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

def build_window(parent, entries: dict, on_remove: Callable[[str], None],
                 on_clear_session: Callable[[], None]):
    """ISS-0012 §6 E2：白名单管理窗口。

    entries = {"static": {proc: level}, "session": {proc: level}}；
    静态区标题"已永久加入"、会话区标题"本次会话临时允许（重启失效）"，
    逐行 [移出]；会话区底部 [全部清空]。
    """
    win = tk.Toplevel(parent)
    win.title("DeskPilot 白名单管理")
    win.geometry(f"{_WIDTH}x360")
    win.configure(bg="#FFFFFF")

    body = tk.Frame(win, bg="#FFFFFF")
    body.pack(fill="both", expand=True, padx=16, pady=12)

    tk.Label(body, text="已永久加入（写入白名单文件）", bg="#FFFFFF",
             font=_TITLE_FONT, anchor="w").pack(fill="x")
    for proc, level in entries.get("static", {}).items():
        _row(body, proc, level, on_remove)

    tk.Label(body, text="本次会话临时允许（重启失效）", bg="#FFFFFF",
             font=_TITLE_FONT, anchor="w").pack(fill="x", pady=(14, 0))
    for proc, level in entries.get("session", {}).items():
        _row(body, proc, level, on_remove)

    bar = tk.Frame(body, bg="#FFFFFF")
    bar.pack(fill="x", pady=(14, 0))
    tk.Button(bar, text="全部清空", width=10, relief="flat",
              bg="#F0F0F0", font=_TEXT_FONT, cursor="hand2",
              command=on_clear_session).pack(side="right")
    return win


def _row(parent, proc: str, level: str, on_remove) -> None:
    row = tk.Frame(parent, bg="#FFFFFF")
    row.pack(fill="x", pady=2)
    tk.Label(row, text=f"{proc}    {level}", bg="#FFFFFF", font=_TEXT_FONT,
             anchor="w").pack(side="left", fill="x", expand=True)
    tk.Button(row, text="移出", width=8, relief="flat", bg="#F0F0F0",
              font=_TEXT_FONT, cursor="hand2",
              command=lambda p=proc: on_remove(p)).pack(side="right")


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
