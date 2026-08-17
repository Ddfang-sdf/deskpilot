"""审批弹窗独立进程（M3，功能设计说明书 §6.1）。

以独立进程运行：右下角 toast 形态（无边框、置顶、滑入动画），
展示操作描述与倒计时；按钮「批准一次」/「拒绝」；倒计时结束默认拒绝（fail-closed）。
人类决定写入结果文件，由 TkApprovalChannel 轮询消费。
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

_WIDTH, _HEIGHT = 440, 210
_MARGIN = 16          # 距屏幕右/下边缘
_TASKBAR = 48         # 任务栏预留
_SLIDE_STEPS = 10     # 滑入动画步数
_SLIDE_MS = 12        # 每步毫秒


def _toast_placement(screen_w: int, screen_h: int,
                     width: int = _WIDTH, height: int = _HEIGHT):
    """右下角 toast 落位：返回 (x, y_start, y_final)；y_start 在屏外供滑入。"""
    x = max(0, screen_w - width - _MARGIN)
    y_final = max(0, screen_h - height - _TASKBAR - _MARGIN)
    return x, screen_h, y_final


def main() -> None:
    desc_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    timeout_s = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    try:
        description = desc_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        description = "(审批描述读取失败)"

    root = tk.Tk()
    root.title("DeskPilot 审批")
    root.overrideredirect(True)                  # 无边框 toast
    root.attributes("-topmost", True)
    root.configure(bg="#FFFFFF")

    x, y_start, y_final = _toast_placement(
        root.winfo_screenwidth(), root.winfo_screenheight())
    root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y_start}")

    card = tk.Frame(root, bg="#FFFFFF", highlightthickness=1,
                    highlightbackground="#D4D4D4")
    card.pack(fill="both", expand=True)
    tk.Frame(card, bg="#C50F1F", height=4).pack(fill="x")      # 警示色条

    tk.Label(card, text="⚠ DeskPilot 审批", bg="#FFFFFF", fg="#1F1F1F",
             font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(
        padx=20, pady=(12, 2), fill="x")
    tk.Label(card, text=description, bg="#FFFFFF", fg="#333333",
             wraplength=_WIDTH - 44, justify="left",
             font=("Microsoft YaHei", 10), anchor="w").pack(
        padx=20, pady=4, fill="x")

    remaining = [timeout_s]
    timer_label = tk.Label(card, text=f"{remaining[0]} 秒后默认拒绝",
                           bg="#FFFFFF", fg="#8A8A8A",
                           font=("Microsoft YaHei", 9), anchor="w")
    timer_label.pack(padx=20, fill="x")

    decided = [False]

    def decide(value: str) -> None:
        if decided[0]:
            return
        decided[0] = True
        try:
            result_path.write_text(value, encoding="utf-8")
        except OSError:
            pass
        root.destroy()

    def _flat(btn: tk.Button, base: str, hover: str) -> None:
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda e: btn.configure(bg=base))

    bar = tk.Frame(card, bg="#FFFFFF")
    bar.pack(pady=(10, 14))
    approve = tk.Button(bar, text="批准一次", width=12, relief="flat",
                        bg="#107C10", fg="#FFFFFF",
                        activebackground="#0B5A0B", activeforeground="#FFFFFF",
                        font=("Microsoft YaHei", 10),
                        command=lambda: decide("approve"))
    approve.pack(side="left", padx=6)
    _flat(approve, "#107C10", "#0B5A0B")
    deny = tk.Button(bar, text="拒绝", width=12, relief="flat",
                     bg="#E1E1E1", fg="#1F1F1F",
                     activebackground="#C7C7C7", activeforeground="#1F1F1F",
                     font=("Microsoft YaHei", 10),
                     command=lambda: decide("deny"))
    deny.pack(side="left", padx=6)
    _flat(deny, "#E1E1E1", "#C7C7C7")

    def tick() -> None:
        remaining[0] -= 1
        if remaining[0] <= 0:
            decide("timeout")
            return
        timer_label.config(text=f"{remaining[0]} 秒后默认拒绝")
        root.after(1000, tick)

    def slide(y: int) -> None:
        step = max(1, (y_start - y_final) // _SLIDE_STEPS)
        y = max(y_final, y - step)
        root.geometry(f"+{x}+{y}")
        if y > y_final:
            root.after(_SLIDE_MS, lambda: slide(y))

    root.after(1000, tick)
    slide(y_start)
    root.mainloop()


if __name__ == "__main__":
    main()
