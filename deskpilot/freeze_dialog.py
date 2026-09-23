"""冻结提示弹窗（详细设计 §11.6，ISS-0004）——独立子进程（Tk toast）。

滑入弹出：冻结事实 + 触发来源 + [立即解冻] [稍后提醒] + 热键提示；
250ms 轮询状态文件，任何来源复位后滑出自动消失。
「立即解冻」直达通道（ISS-0093）：进程内形态直调 on_reset 回调，
子进程形态关窗并以退出码 EXIT_RESET 退出（零文件零接口）。
本模块的纯逻辑函数（状态读取/重提醒判定/动画位移序列）
不依赖 tkinter，可单独测试；main() 为生产弹窗入口。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .freeze_notify import STATE_FILE
from .i18n import tr
from .monitors import TASKBAR_RESERVE

FRAME_MS = 16               # 动画帧间隔（约 60fps）
SLIDE_MS = 240              # 滑入/滑出时长（对称原则：同长反向）
POLL_MS = 250               # 状态文件轮询间隔
WIN_W = 440                 # 弹窗尺寸
WIN_H = 210
MARGIN_RIGHT = 16           # 落位：主屏右下角
MARGIN_BOTTOM = TASKBAR_RESERVE  # 避开任务栏(ISS-0057:避让边距单源)

# ISS-0093 §9.2：子进程形态「立即解冻」退出码通道（公开常量,非秘密）。
# P1 空壳:仅常量定名,退出码语义(关窗 exit/属主 poll 消费)随 P3 实现。
EXIT_RESET = 73

# ---- 单例互斥（ISS-0006 §6）----
SINGLETON_NAME = r"Local\DeskPilotFreezeDialog"
_mutex_handle = None


def acquire_singleton(name: str = SINGLETON_NAME) -> bool:
    """抢到命名互斥体并持有 → True；已被他进程持有或系统调用失败 → False。"""
    global _mutex_handle
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return False                              # 系统调用失败：不建窗
    if kernel32.GetLastError() == 183:            # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def release_singleton() -> None:
    """释放单例互斥体；重复调用安全。"""
    global _mutex_handle
    if _mutex_handle:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


def reset_click_action(state: str) -> str:
    """「立即解冻」点击决策（ISS-0093 §9.1：req 邮箱废止,直调/退出码）：
    "SHOWN" → "reset_and_slide_out"；其他 → "wait"。"""
    return "reset_and_slide_out" if state == "SHOWN" else "wait"

# ---- 视觉样式（ISS-0005，Tk 逻辑像素；改外观只动这里）----
CHROMA = "#010101"          # 色键透明色：禁止与任何样式色相同（TC-N-EST-15）
STYLE = {
    "card_bg": "#FFFFFF",      # 卡片白底
    "card_border": "#EDEBE9",  # 卡片描边
    "accent": "#D83B01",       # 警示色条/主按钮（Windows warning 橙）
    "title_fg": "#1F1F1F",     # 三级文字层级 + 热键提示弱化
    "source_fg": "#605E5C",
    "body_fg": "#323130",
    "hint_fg": "#8A8886",
    "radius": 8,               # 卡片圆角半径
    "accent_w": 4,             # 警示色条宽
    "primary": {               # 主按钮（立即解冻）四态
        "bg": "#D83B01", "fg": "#FFFFFF",
        "hover_bg": "#C33401", "pressed_bg": "#A82C01",
        "disabled_bg": "#F3F2F1", "disabled_fg": "#8A8886",
    },
    "secondary": {             # 次按钮（稍后提醒）两态
        "bg": "#FFFFFF", "fg": "#323130", "border": "#8A8886",
        "hover_bg": "#F3F2F1",
    },
}


def read_state(audit_dir: str) -> dict | None:
    """读 estop-state.json；不存在/非法返回 None。"""
    try:
        return json.loads((Path(audit_dir) / STATE_FILE)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ISS-0103：急停触发源显示侧翻译——state.source 携的是 estop 硬编码中文
# 字面量(协议字段含显示串是设计异味,token 化改动面大,备案不实施);
# 显示侧映射已知来源到 i18n 键,未知来源原样透传(不静默吞)。
_TRIGGER_SRC_KEYS = {
    "鼠标甩角": "estop.src.corner",
    "热键 Ctrl+Shift+F12": "estop.src.hotkey",
}


def source_display(source: str) -> str:
    """急停触发源 → 当前语言显示串(已知映射,未知原样透传)。"""
    key = _TRIGGER_SRC_KEYS.get(source)
    return tr(key) if key else source


def _measure_text(text: str) -> int:
    """按钮文本像素宽(测试缝:替身注入;生产=tkfont 实测,无根窗/实测
    失败时按字宽估算——量宽是显示辅助,估算兜底不炸建窗)。"""
    try:
        from tkinter import font as tkfont
        return tkfont.Font(family="Microsoft YaHei UI", size=10).measure(text)
    except Exception:
        # 估算:ASCII ~7px,宽字符(CJK/全角) ~14px(size 10 经验值)
        return sum(14 if ord(c) > 0x2E7F else 7 for c in text)


def should_remind(snooze_start: float, now: float, frozen: bool,
                  interval: float) -> bool:
    """SNOOZED 重提醒判定：到点且仍冻结。"""
    return frozen and (now - snooze_start) >= interval


def next_action(state: str, frozen: bool) -> str:
    """SHOWN 轮询判定：复位（frozen=false）→ 滑出退出。"""
    if state == "SHOWN" and not frozen:
        return "slide_out_exit"
    return "wait"


def slide_in_frames(screen_w: int, win_w: int = WIN_W) -> list[tuple[int, float]]:
    """滑入帧序列 (x, alpha)：屏外右缘 → 右下角，ease-out 三次方；
    alpha 与位移共用同一缓动表，同帧 0.0 → 1.0（ISS-0005 复合动画）。"""
    n = SLIDE_MS // FRAME_MS                     # 15 帧
    start, target = screen_w, screen_w - win_w - MARGIN_RIGHT
    out = []
    for i in range(n):
        t = i / (n - 1)                          # 0 → 1（含首尾）
        ease = 1 - (1 - t) ** 3
        out.append((round(start + (target - start) * ease), round(ease, 3)))
    return out


def slide_out_frames(screen_w: int, win_w: int = WIN_W) -> list[tuple[int, float]]:
    """滑出帧序列：与滑入逐帧反向（对称原则，位移+透明度同步反向）。"""
    return list(reversed(slide_in_frames(screen_w, win_w)))


def slide_in_xs(screen_w: int, win_w: int = WIN_W) -> list[int]:
    """滑入 x 位移序列（TC-N-EST-12 观测口；轨迹与 slide_in_frames 一致）。"""
    return [x for x, _ in slide_in_frames(screen_w, win_w)]


def slide_out_xs(screen_w: int, win_w: int = WIN_W) -> list[int]:
    """滑出 x 位移序列：与滑入逐帧反向（对称原则）。"""
    return [x for x, _ in slide_out_frames(screen_w, win_w)]


def build_window(parent, audit_dir: str, interval: float,
                 target_screen: dict | None = None, on_reset=None):
    """在 parent（共享 Tk root）线程内构建冻结提示 toast（Toplevel，ISS-0008 P6）。

    状态机：SLIDE_IN → SHOWN ⇄ SNOOZED → SLIDE_OUT → 退出；
    状态文件 frozen=false（任何来源复位）即滑出退出。
    target_screen（ISS-0007 §6）：显示器 dict 时 toast 落该屏右下角
    （冻结调用方按鼠标所在屏传入；缺省保持主屏右下）。
    on_reset（ISS-0093 §9.1）：进程内形态注入「立即解冻」直调回调
    （装配侧=estop.dialog_reset；点击直调,不写 req 文件、不读 state seq）；
    子进程形态缺省 None（§9.2 退出码通道：点击=关窗+EXIT_RESET）。
    """
    import math
    import tkinter as tk

    # ISS-0046 B:跨进程单例收口到建窗点——共享线程路径(dialog_service)
    # 与子进程路径(main)同锁;抢不到不建窗(多进程同时冻结也只弹一框);
    # 窗毁(Destroy)释放,add="+" 与调用方既有 Destroy 绑定共存。
    if not acquire_singleton():
        return None
    win = tk.Toplevel(parent)
    win.bind("<Destroy>",
             lambda e: release_singleton() if e.widget is win else None,
             add="+")
    win.title(tr("freeze.title"))
    win.overrideredirect(True)                  # toast 形态：无边框
    win.attributes("-topmost", True)
    win.config(bg=CHROMA)
    win.attributes("-transparentcolor", CHROMA)  # 色键抠除窗外区域 → 圆角生效
    win.attributes("-alpha", 0.0)               # 滑入从全透明开始
    if target_screen is not None:
        # ISS-0007：以目标屏右缘/工作区底缘充当"屏宽/屏高"参与现有轨迹计算
        screen_w = target_screen["rect"][2]
        screen_h = target_screen["work_area"][3]
    else:
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
    frames_in = slide_in_frames(screen_w, WIN_W)
    frames_out = slide_out_frames(screen_w, WIN_W)
    y = screen_h - WIN_H - MARGIN_BOTTOM
    win.geometry(f"{WIN_W}x{WIN_H}+{frames_in[0][0]}+{y}")

    # ---- 卡片装配（画布圆角卡片 + 绝对定位文本/按钮，ISS-0005 §3.2）----
    def _card_points(x1, y1, x2, y2, r):
        """圆角矩形顶点（四角各 5 点圆弧，配合 create_polygon smooth）。"""
        corners = [((x2 - r, y1 + r), 90, 0), ((x2 - r, y2 - r), 0, -90),
                   ((x1 + r, y2 - r), -90, -180), ((x1 + r, y1 + r), 180, 90)]
        pts = []
        for (cx, cy), a0, a1 in corners:
            for i in range(5):
                a = math.radians(a0 + (a1 - a0) * i / 4)
                pts.extend((cx + r * math.cos(a), cy - r * math.sin(a)))
        return pts

    cv = tk.Canvas(win, width=WIN_W, height=WIN_H, bg=CHROMA,
                   highlightthickness=0, bd=0)
    cv.place(x=0, y=0)
    r = STYLE["radius"]
    cv.create_polygon(_card_points(1, 1, WIN_W - 1, WIN_H - 1, r),
                      smooth=True, fill=STYLE["card_bg"],
                      outline=STYLE["card_border"], width=1)
    aw = STYLE["accent_w"]
    cv.create_rectangle(1, 3, 1 + aw, WIN_H - 3, fill=STYLE["accent"],
                        outline="")              # 警示色条：全高、收进圆角内

    FG = ("Microsoft YaHei UI", 9)
    card_bg = STYLE["card_bg"]
    tk.Label(win, text="🛡️", font=("Segoe UI Emoji", 14),
             bg=card_bg).place(x=18, y=13)
    tk.Label(win, text=tr("freeze.frozen"), fg=STYLE["title_fg"], bg=card_bg,
             font=("Microsoft YaHei UI", 13, "bold")).place(x=48, y=15)
    src = tk.Label(win, text="", font=FG, fg=STYLE["source_fg"], bg=card_bg)
    src.place(x=48, y=45)
    tk.Label(win, text=tr("freeze.allwrites"),
             font=FG, fg=STYLE["body_fg"], bg=card_bg).place(x=18, y=76)
    tk.Label(win, text=tr("freeze.hotkey_hint"),
             font=FG, fg=STYLE["hint_fg"], bg=card_bg).place(x=18, y=100)

    holder = {"state": "SLIDE_IN", "snooze_start": 0.0,
              "frames": list(frames_in), "last_seq": None}

    def refresh_source():
        st = read_state(audit_dir)
        if st:
            holder["last_seq"] = int(st.get("seq", 0))
            src.config(text=tr("freeze.source",
                               source=source_display(str(st.get("source", ""))),
                               ts=str(st.get("ts", ""))[:19]))

    def on_reset_now():
        # ISS-0093 §9.1/9.2：解冻指令直达,零文件零接口——
        # 进程内形态(on_reset 给定):直调回调(=estop.dialog_reset),随后
        # 滑出退出(复位直达,不再走 SNOOZED 重提醒兜底);子进程形态
        # (on_reset=None):关窗并以退出码 EXIT_RESET 退出,属主 poll 消费。
        if reset_click_action(holder["state"]) != "reset_and_slide_out":
            return
        if on_reset is None:
            win.reset_requested = True         # main() 据此以 73 退出(见下)
            win.destroy()
            # Tk 回调内 SystemExit 会被 tkinter 吞(report_callback_exception),
            # 真实退出码由 freeze_dialog.main() 在 mainloop 返回后产出;
            # 此处 raise 保证非 Tk 驱动(测试/直调)下同步语义一致(§9.2)。
            raise SystemExit(EXIT_RESET)
        on_reset()
        holder["state"] = "SLIDE_OUT"
        holder["frames"] = list(frames_out)
        win.after(FRAME_MS, slide_step)          # 按钮回调须自启动画链

    def on_snooze():
        import time
        holder["state"] = "SNOOZE_OUT"
        holder["frames"] = list(frames_out)
        holder["snooze_start"] = time.monotonic()
        win.after(FRAME_MS, slide_step)          # 按钮回调须自启动画链

    def _flat_button(text, cmd, spec, width_px):
        """扁平按钮：normal/hover/pressed 三态换色，禁用色经 disabledforeground。"""
        b = tk.Button(win, text=text, command=cmd, relief="flat", bd=0,
                      font=("Microsoft YaHei UI", 10), cursor="hand2",
                      bg=spec["bg"], fg=spec["fg"],
                      activebackground=spec.get("pressed_bg",
                                                spec.get("hover_bg")),
                      activeforeground=spec["fg"],
                      disabledforeground=spec.get("disabled_fg",
                                                  spec["fg"]),
                      highlightthickness=1,
                      highlightbackground=spec.get("border", spec["bg"]))
        b.bind("<Enter>", lambda _e: b.config(
            bg=spec["hover_bg"]) if str(b["state"]) == "normal" else None)
        b.bind("<Leave>", lambda _e: b.config(
            bg=spec["bg"]) if str(b["state"]) == "normal" else None)
        b.place(width=width_px, height=34)
        return b

    # ISS-0103：按钮宽按实测文本(先量后排,同 ISS-0098 纪律)——英文长文
    # 不再裁边;秒数括号随语言(i18n 模板槽)。组按实测总宽居中。
    _pad = 28                                # 按钮左右内边距合计
    _min_w = (136, 140)                      # zh 时代既有宽(下限,不缩)
    reset_text = tr("freeze.btn.reset_now")
    snooze_text = tr("freeze.btn.snooze", n=int(interval))
    w_reset = max(_min_w[0], _measure_text(reset_text) + _pad)
    w_snooze = max(_min_w[1], _measure_text(snooze_text) + _pad)
    total = w_reset + 16 + w_snooze
    x_reset = (WIN_W - total) // 2
    btn_reset = _flat_button(reset_text, on_reset_now,
                             STYLE["primary"], w_reset)
    btn_reset.place(x=x_reset, y=144)
    _flat_button(snooze_text, on_snooze, STYLE["secondary"],
                 w_snooze).place(x=x_reset + w_reset + 16, y=144)

    def slide_step():
        """滑动画帧驱动：frames (x, alpha) 播完进入下一阶段。"""
        frames = holder["frames"]
        if frames:
            x, alpha = frames.pop(0)
            win.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
            win.attributes("-alpha", alpha)
            win.after(FRAME_MS, slide_step)
            return
        st = holder["state"]
        if st == "SLIDE_IN":
            holder["state"] = "SHOWN"
        elif st == "SNOOZE_OUT":
            holder["state"] = "SNOOZED"
            win.withdraw()
        elif st == "SLIDE_OUT":
            win.destroy()
            return
        win.after(POLL_MS, poll)

    def poll():
        import time
        st = read_state(audit_dir)
        frozen = bool(st and st.get("frozen"))
        state = holder["state"]
        if st:
            holder["last_seq"] = int(st.get("seq", 0))
        if state == "SHOWN":
            if next_action("SHOWN", frozen) == "slide_out_exit":
                holder["state"] = "SLIDE_OUT"
                holder["frames"] = list(frames_out)
                win.after(FRAME_MS, slide_step)
                return
        elif state == "SNOOZED":
            if not frozen:
                win.destroy()                    # 已隐藏，直接退出
                return
            if should_remind(holder["snooze_start"], time.monotonic(),
                             True, interval):
                holder["state"] = "SLIDE_IN"
                holder["frames"] = list(frames_in)
                win.deiconify()
                refresh_source()
                win.after(FRAME_MS, slide_step)
                return
        win.after(POLL_MS, poll)

    refresh_source()
    win.after(FRAME_MS, slide_step)
    return win


def main() -> None:
    """独立子进程入口（非 daemon / stdio 回退路径）。

    argv: <audit_dir> <remind_interval>
    """
    import tkinter as tk

    audit_dir = sys.argv[1]
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0

    root = tk.Tk()
    root.withdraw()
    # ISS-0046 B:单例互斥收口进 build_window(共享/子进程同锁);
    # 未抢到 → None,本进程直接退出(等价原"抢不到即退出")。
    win = build_window(root, audit_dir, interval)
    if win is None:
        return
    # 独立形态：本窗关闭即退出 mainloop（共享线程形态由服务托管，不绑此事件）
    win.bind("<Destroy>", lambda e: root.quit() if e.widget is win else None,
             add="+")
    root.mainloop()
    # ISS-0093 §9.2：子进程「立即解冻」退出码通道——Tk 回调内的 SystemExit
    # 会被 tkinter 吞掉,退出码在 mainloop 返回后据此产出(点击已关窗)。
    if getattr(win, "reset_requested", False):
        sys.exit(EXIT_RESET)
