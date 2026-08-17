"""审批弹窗独立进程（M3，功能设计说明书 §6.1）。

以独立进程运行：右下角 toast 形态（无边框、置顶、滑入动画），
展示操作描述与倒计时；倒计时结束默认拒绝（fail-closed）。
人类决定写入结果文件，由 TkApprovalChannel 轮询消费。

视觉规范（Fluent ContentDialog / Material AlertDialog 业界实践）：
- 左侧警示色条 + 加粗标题 + 次级说明文字，层级分明
- 按钮右对齐、间距 12px：安全项「拒绝」在左且为默认焦点，
  后果项「批准一次」在右（绿色填充）——Esc = 拒绝，方向键/Tab 可切换
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

_WIDTH, _HEIGHT = 480, 216
_MARGIN = 16          # 距屏幕右/下边缘
_TASKBAR = 48         # 任务栏预留
_SLIDE_STEPS = 10     # 滑入动画步数
_SLIDE_MS = 12        # 每步毫秒

_BG = "#FFFFFF"
_BORDER = "#D0D0D0"
_ACCENT = "#C50F1F"   # 警示红
_TITLE_FG = "#1F1F1F"
_DESC_FG = "#424242"
_TIMER_FG = "#8A8A8A"
_APPROVE_BG, _APPROVE_HOVER = "#107C10", "#0B5A0B"      # 批准：绿
_DENY_BG, _DENY_HOVER = "#F0F0F0", "#DDDDDD"            # 拒绝：中性灰
_BTN_WIDTH, _BTN_GAP = 12, 12                         # 字符宽 / 像素距


def _toast_placement(screen_w: int, screen_h: int,
                     width: int = _WIDTH, height: int = _HEIGHT):
    """右下角 toast 落位：返回 (x, y_start, y_final)；y_start 在屏外供滑入。"""
    x = max(0, screen_w - width - _MARGIN)
    y_final = max(0, screen_h - height - _TASKBAR - _MARGIN)
    return x, screen_h, y_final


def _hover(btn: tk.Button, base: str, hover: str) -> None:
    btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
    btn.bind("<Leave>", lambda e: btn.configure(bg=base))


def main() -> None:
    desc_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    timeout_s = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    image_path = sys.argv[4] if len(sys.argv) > 4 else ""
    try:
        description = desc_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        description = "(审批描述读取失败)"
    headline, _, detail = description.partition("\n---\n")

    # 目标窗口实拍缩略图（可选）：最大化“这是哪个窗口”的可识别性
    photo = None
    img_h = 0
    if image_path:
        try:
            from PIL import Image, ImageTk
            im = Image.open(image_path)
            im.thumbnail((_WIDTH - 72, 150))
            img_h = im.height
        except Exception:
            im = None

    root = tk.Tk()
    root.title("DeskPilot 审批")
    root.overrideredirect(True)                  # 无边框 toast
    root.attributes("-topmost", True)
    root.configure(bg=_BG)

    height = _HEIGHT + (img_h + 8 if image_path and im is not None else 0)
    x, y_start, y_final = _toast_placement(
        root.winfo_screenwidth(), root.winfo_screenheight(), _WIDTH, height)
    root.geometry(f"{_WIDTH}x{height}+{x}+{y_start}")

    card = tk.Frame(root, bg=_BG, highlightthickness=1,
                    highlightbackground=_BORDER)
    card.pack(fill="both", expand=True)
    tk.Frame(card, bg=_ACCENT, width=4).pack(side="left", fill="y")   # 警示色条

    body = tk.Frame(card, bg=_BG)
    body.pack(side="left", fill="both", expand=True, padx=20, pady=(16, 14))

    header = tk.Frame(body, bg=_BG)
    header.pack(fill="x")
    tk.Label(header, text="⚠", bg=_BG, fg=_ACCENT,
             font=("Microsoft YaHei", 13, "bold")).pack(side="left")
    tk.Label(header, text="DeskPilot 审批", bg=_BG, fg=_TITLE_FG,
             font=("Microsoft YaHei", 11, "bold")).pack(side="left", padx=(8, 0))

    tk.Label(body, text=headline, bg=_BG, fg=_TITLE_FG,
             wraplength=_WIDTH - 64, justify="left",
             font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(
        fill="x", pady=(8, 0))

    if image_path and im is not None:
        photo = ImageTk.PhotoImage(im)
        tk.Label(body, image=photo, bg=_BG, bd=1, relief="solid").pack(
            fill="x", pady=(8, 0))

    if detail:
        tk.Label(body, text=detail, bg=_BG, fg=_TIMER_FG,
                 wraplength=_WIDTH - 64, justify="left",
                 font=("Microsoft YaHei", 8), anchor="w").pack(fill="x",
                                                                pady=(6, 0))

    remaining = [timeout_s]
    timer_label = tk.Label(body, text=f"{remaining[0]} 秒后默认拒绝",
                           bg=_BG, fg=_TIMER_FG,
                           font=("Microsoft YaHei", 9), anchor="w")
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
        root.destroy()

    # 按钮行右对齐：安全项在左（默认焦点），后果项在右
    bar = tk.Frame(body, bg=_BG)
    bar.pack(fill="x", pady=(14, 0))
    approve = tk.Button(bar, text="批准一次", width=_BTN_WIDTH, relief="flat",
                        bg=_APPROVE_BG, fg="#FFFFFF",
                        activebackground=_APPROVE_HOVER, activeforeground="#FFFFFF",
                        font=("Microsoft YaHei", 10), cursor="hand2",
                        command=lambda: decide("approve"))
    approve.pack(side="right")
    _hover(approve, _APPROVE_BG, _APPROVE_HOVER)
    deny = tk.Button(bar, text="拒绝", width=_BTN_WIDTH, relief="flat",
                     bg=_DENY_BG, fg=_TITLE_FG,
                     activebackground=_DENY_HOVER, activeforeground=_TITLE_FG,
                     font=("Microsoft YaHei", 10), cursor="hand2",
                     command=lambda: decide("deny"))
    deny.pack(side="right", padx=(0, _BTN_GAP))
    _hover(deny, _DENY_BG, _DENY_HOVER)
    deny.focus_set()                             # 默认焦点在安全项
    root.bind("<Escape>", lambda e: decide("deny"))

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
