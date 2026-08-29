"""冻结提示弹窗（详细设计 §11.6，ISS-0004）——独立子进程（Tk toast）。

滑入弹出：冻结事实 + 触发来源 + [立即解冻] [稍后提醒] + 热键提示；
250ms 轮询状态文件，任何来源复位后滑出自动消失。
本模块的纯逻辑函数（状态读取/请求写入/重提醒判定/动画位移序列）
不依赖 tkinter，可单独测试；main() 为生产弹窗入口。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .freeze_notify import STATE_FILE

FRAME_MS = 16               # 动画帧间隔（约 60fps）
SLIDE_MS = 240              # 滑入/滑出时长（对称原则：同长反向）
POLL_MS = 250               # 状态文件轮询间隔
WIN_W = 440                 # 弹窗尺寸
WIN_H = 210
MARGIN_RIGHT = 16           # 落位：主屏右下角
MARGIN_BOTTOM = 48          # 避开任务栏

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
    """乐观关闭决策（ISS-0006 §6）：
    "SHOWN" → "write_req_and_slide_out"；其他 → "wait"。"""
    return "write_req_and_slide_out" if state == "SHOWN" else "wait"

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


def write_reset_request(audit_dir: str, seq: int) -> None:
    """写 estop-reset-<seq>.req（立即解冻请求，携带其响应的状态 seq）。"""
    (Path(audit_dir) / f"estop-reset-{seq}.req").write_text(
        json.dumps({"seq": seq}), encoding="utf-8")


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


def main() -> None:
    """生产弹窗入口（Tk 主循环 + 状态机）。

    argv: <audit_dir> <remind_interval>
    状态机：SLIDE_IN → SHOWN ⇄ SNOOZED → SLIDE_OUT → 退出；
    状态文件 frozen=false（任何来源复位）即滑出退出。
    """
    import tkinter as tk

    audit_dir = sys.argv[1]
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0

    if not acquire_singleton():                   # ISS-0006：互斥单例，抢不到即退出
        return

    root = tk.Tk()
    root.title("DeskPilot 急停")
    root.overrideredirect(True)                  # toast 形态：无边框
    root.attributes("-topmost", True)
    root.config(bg=CHROMA)
    root.attributes("-transparentcolor", CHROMA)  # 色键抠除窗外区域 → 圆角生效
    root.attributes("-alpha", 0.0)               # 滑入从全透明开始
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    frames_in = slide_in_frames(screen_w, WIN_W)
    frames_out = slide_out_frames(screen_w, WIN_W)
    y = screen_h - WIN_H - MARGIN_BOTTOM
    root.geometry(f"{WIN_W}x{WIN_H}+{frames_in[0][0]}+{y}")

    # ---- 卡片装配（画布圆角卡片 + 绝对定位文本/按钮，ISS-0005 §3.2）----
    import math

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

    cv = tk.Canvas(root, width=WIN_W, height=WIN_H, bg=CHROMA,
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
    tk.Label(root, text="🛡️", font=("Segoe UI Emoji", 14),
             bg=card_bg).place(x=18, y=13)
    tk.Label(root, text="DeskPilot 已冻结", fg=STYLE["title_fg"], bg=card_bg,
             font=("Microsoft YaHei UI", 13, "bold")).place(x=48, y=15)
    src = tk.Label(root, text="", font=FG, fg=STYLE["source_fg"], bg=card_bg)
    src.place(x=48, y=45)
    tk.Label(root, text="AI 的写操作已全部拒绝（EMERGENCY_STOP）",
             font=FG, fg=STYLE["body_fg"], bg=card_bg).place(x=18, y=76)
    tk.Label(root, text="可随时按 Ctrl+Shift+F11 直接解冻，本窗口会自动消失",
             font=FG, fg=STYLE["hint_fg"], bg=card_bg).place(x=18, y=100)

    holder = {"state": "SLIDE_IN", "snooze_start": 0.0,
              "frames": list(frames_in), "last_seq": None}

    def refresh_source():
        st = read_state(audit_dir)
        if st:
            holder["last_seq"] = int(st.get("seq", 0))
            src.config(text=f"触发：{st.get('source', '')} · "
                            f"{str(st.get('ts', ''))[:19]}")

    def on_reset_now():
        # 乐观关闭（ISS-0006 方案 F）：写请求即滑出隐藏；请求若未被消费
        # （仍冻结），重提醒机制在下一周期自然补一个弹窗，而不是让用户连点。
        if reset_click_action(holder["state"]) != "write_req_and_slide_out":
            return
        st = read_state(audit_dir)
        seq = int(st["seq"]) if st and "seq" in st else holder["last_seq"]
        if seq is None:
            return
        write_reset_request(audit_dir, seq)
        import time
        holder["state"] = "SNOOZE_OUT"
        holder["frames"] = list(frames_out)
        holder["snooze_start"] = time.monotonic()
        root.after(FRAME_MS, slide_step)         # 按钮回调须自启动画链

    def on_snooze():
        import time
        holder["state"] = "SNOOZE_OUT"
        holder["frames"] = list(frames_out)
        holder["snooze_start"] = time.monotonic()
        root.after(FRAME_MS, slide_step)         # 按钮回调须自启动画链

    def _flat_button(text, cmd, spec, width_px):
        """扁平按钮：normal/hover/pressed 三态换色，禁用色经 disabledforeground。"""
        b = tk.Button(root, text=text, command=cmd, relief="flat", bd=0,
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

    # 按钮组整体居中：136 + 16 + 140 = 292，左右各 (440-292)/2 = 74
    btn_reset = _flat_button("立即解冻", on_reset_now, STYLE["primary"], 136)
    btn_reset.place(x=74, y=144)
    _flat_button(f"稍后提醒（{interval:.0f}s）", on_snooze,
                 STYLE["secondary"], 140).place(x=226, y=144)

    def slide_step():
        """滑动画帧驱动：frames (x, alpha) 播完进入下一阶段。"""
        frames = holder["frames"]
        if frames:
            x, alpha = frames.pop(0)
            root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
            root.attributes("-alpha", alpha)
            root.after(FRAME_MS, slide_step)
            return
        st = holder["state"]
        if st == "SLIDE_IN":
            holder["state"] = "SHOWN"
        elif st == "SNOOZE_OUT":
            holder["state"] = "SNOOZED"
            root.withdraw()
        elif st == "SLIDE_OUT":
            root.destroy()
            return
        root.after(POLL_MS, poll)

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
                root.after(FRAME_MS, slide_step)
                return
        elif state == "SNOOZED":
            if not frozen:
                root.destroy()                   # 已隐藏，直接退出
                return
            if should_remind(holder["snooze_start"], time.monotonic(),
                             True, interval):
                holder["state"] = "SLIDE_IN"
                holder["frames"] = list(frames_in)
                root.deiconify()
                refresh_source()
                root.after(FRAME_MS, slide_step)
                return
        root.after(POLL_MS, poll)

    refresh_source()
    root.after(FRAME_MS, slide_step)
    root.mainloop()
    release_singleton()
