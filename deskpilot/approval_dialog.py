"""审批弹窗（M3，功能设计说明书 §6.1）。

两种承载形态：
- 独立子进程（main()）：非 daemon / stdio 回退路径；
- 共享线程内 Toplevel（build_window）：DialogService 投递路径（ISS-0008 P6）。

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


def _toast_placement(screen: dict, width: int = _WIDTH, height: int = _HEIGHT):
    """ISS-0007 §6：toast 在目标屏 work_area 右下角落位。

    入参 screen 为显示器 dict（含 rect/work_area）；返回 (x, y_start, y_final)，
    y_start 在该屏底缘外侧供滑入。单屏时与旧主屏语义一致。
    """
    _, _, sr, rb = screen["rect"]
    _, _, _, wb = screen["work_area"]
    x = sr - width - _MARGIN
    y_final = wb - height - _TASKBAR - _MARGIN
    return x, rb, y_final


def _hover(btn: tk.Button, base: str, hover: str) -> None:
    btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
    btn.bind("<Leave>", lambda e: btn.configure(bg=base))


def build_window(parent, description: str, result_path, timeout_s: float,
                 image_path: str = "", target_screen: dict | None = None,
                 enroll: str | None = None):
    """在 parent（共享 Tk root）线程内构建审批 toast（Toplevel，ISS-0008 P6）。

    人类决定写入结果文件（批准一次 / 拒绝）；倒计时结束默认拒绝（fail-closed）。
    image_path 非空时内嵌目标窗口实拍缩略图（动态增高）。
    target_screen（ISS-0007 §6）：显示器 dict 时 toast 落该屏右下角
    （审批调用方按目标窗口所在屏传入；缺省保持主屏右下）。
    enroll（ISS-0012 §6）：非 None 为入白审批——三按钮
    「本次允许(approve) / 永久加入(approve_always) / 拒绝」，
    标题与默认焦点不变（安全项优先）。
    """
    result_path = Path(result_path)

    # 目标窗口实拍缩略图（可选）：最大化“这是哪个窗口”的可识别性
    photo_im = None
    img_h = 0
    if image_path:
        try:
            from PIL import Image
            im = Image.open(image_path)
            im.thumbnail((_WIDTH - 72, 150))
            photo_im, img_h = im, im.height
        except Exception:
            photo_im = None

    height = _HEIGHT + (img_h + 8 if photo_im is not None else 0)

    win = tk.Toplevel(parent)
    win.title("DeskPilot 入白审批" if enroll else "DeskPilot 审批")
    win.overrideredirect(True)                  # 无边框 toast
    win.attributes("-topmost", True)
    win.configure(bg=_BG)

    if target_screen is None:                   # 缺省：主屏右下（现状语义）
        target_screen = {"rect": (0, 0, win.winfo_screenwidth(),
                                  win.winfo_screenheight()),
                         "work_area": (0, 0, win.winfo_screenwidth(),
                                       win.winfo_screenheight() - _TASKBAR)}
    x, y_start, y_final = _toast_placement(target_screen, _WIDTH, height)
    win.geometry(f"{_WIDTH}x{height}+{x}+{y_start}")

    card = tk.Frame(win, bg=_BG, highlightthickness=1,
                    highlightbackground=_BORDER)
    card.pack(fill="both", expand=True)
    tk.Frame(card, bg=_ACCENT, width=4).pack(side="left", fill="y")   # 警示色条

    body = tk.Frame(card, bg=_BG)
    body.pack(side="left", fill="both", expand=True, padx=20, pady=(16, 14))

    header = tk.Frame(body, bg=_BG)
    header.pack(fill="x")
    tk.Label(header, text="⚠", bg=_BG, fg=_ACCENT,
             font=("Microsoft YaHei", 13, "bold")).pack(side="left")
    tk.Label(header, text="DeskPilot 入白审批" if enroll else "DeskPilot 审批",
             bg=_BG, fg=_TITLE_FG,
             font=("Microsoft YaHei", 11, "bold")).pack(side="left", padx=(8, 0))

    headline, _, detail = description.partition("\n---\n")
    tk.Label(body, text=headline, bg=_BG, fg=_TITLE_FG,
             wraplength=_WIDTH - 64, justify="left",
             font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(
        fill="x", pady=(8, 0))

    if photo_im is not None:
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(photo_im)
        tk.Label(body, image=photo, bg=_BG, bd=1, relief="solid").pack(
            fill="x", pady=(8, 0))

    if detail:
        tk.Label(body, text=detail, bg=_BG, fg=_TIMER_FG,
                 wraplength=_WIDTH - 64, justify="left",
                 font=("Microsoft YaHei", 8), anchor="w").pack(fill="x",
                                                                pady=(6, 0))

    remaining = [int(timeout_s)]
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
        win.destroy()

    # 按钮行右对齐：安全项在左（默认焦点），后果项在右
    bar = tk.Frame(body, bg=_BG)
    bar.pack(fill="x", pady=(14, 0))
    if enroll:
        # ISS-0012 入白三态：本次允许（会话）/ 永久加入（落盘）/ 拒绝
        always = tk.Button(bar, text="永久加入", width=_BTN_WIDTH, relief="flat",
                           bg=_APPROVE_BG, fg="#FFFFFF",
                           activebackground=_APPROVE_HOVER,
                           activeforeground="#FFFFFF",
                           font=("Microsoft YaHei", 10), cursor="hand2",
                           command=lambda: decide("approve_always"))
        always.pack(side="right")
        _hover(always, _APPROVE_BG, _APPROVE_HOVER)
        once = tk.Button(bar, text="本次会话允许", width=_BTN_WIDTH, relief="flat",
                         bg=_DENY_BG, fg=_TITLE_FG,
                         activebackground=_DENY_HOVER,
                         activeforeground=_TITLE_FG,
                         font=("Microsoft YaHei", 10), cursor="hand2",
                         command=lambda: decide("approve"))
        once.pack(side="right", padx=(0, _BTN_GAP))
        _hover(once, _DENY_BG, _DENY_HOVER)
        deny_text = "拒绝"
    else:
        approve = tk.Button(bar, text="批准一次", width=_BTN_WIDTH,
                            relief="flat",
                            bg=_APPROVE_BG, fg="#FFFFFF",
                            activebackground=_APPROVE_HOVER,
                            activeforeground="#FFFFFF",
                            font=("Microsoft YaHei", 10), cursor="hand2",
                            command=lambda: decide("approve"))
        approve.pack(side="right")
        _hover(approve, _APPROVE_BG, _APPROVE_HOVER)
        deny_text = "拒绝"
    deny = tk.Button(bar, text=deny_text, width=_BTN_WIDTH, relief="flat",
                     bg=_DENY_BG, fg=_TITLE_FG,
                     activebackground=_DENY_HOVER, activeforeground=_TITLE_FG,
                     font=("Microsoft YaHei", 10), cursor="hand2",
                     command=lambda: decide("deny"))
    deny.pack(side="right", padx=(0, _BTN_GAP))
    _hover(deny, _DENY_BG, _DENY_HOVER)
    deny.focus_set()                             # 默认焦点在安全项
    win.bind("<Escape>", lambda e: decide("deny"))

    def tick() -> None:
        remaining[0] -= 1
        if remaining[0] <= 0:
            decide("timeout")
            return
        timer_label.config(text=f"{remaining[0]} 秒后默认拒绝")
        win.after(1000, tick)

    def slide(y: int) -> None:
        step = max(1, (y_start - y_final) // _SLIDE_STEPS)
        y = max(y_final, y - step)
        win.geometry(f"+{x}+{y}")
        if y > y_final:
            win.after(_SLIDE_MS, lambda: slide(y))

    win.after(1000, tick)
    slide(y_start)
    return win


def main() -> None:
    """独立子进程入口（非 daemon / stdio 回退路径）。

    argv: <desc_path> <result_path> <timeout_s> [image_path] [enroll_process]
    """
    desc_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    timeout_s = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    try:
        description = desc_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        description = "(审批描述读取失败)"

    root = tk.Tk()
    root.withdraw()
    image_path = sys.argv[4] if len(sys.argv) > 4 else ""
    enroll = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None
    win = build_window(root, description, result_path, timeout_s, image_path,
                       enroll=enroll)
    # 独立形态：本窗关闭即退出 mainloop（共享线程形态由服务托管，不绑此事件）
    win.bind("<Destroy>", lambda e: root.quit() if e.widget is win else None)
    root.mainloop()


if __name__ == "__main__":
    main()
