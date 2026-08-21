"""冻结提示弹窗（详细设计 §11.6，ISS-0004）——独立子进程（Tk toast）。

滑入弹出：冻结事实 + 触发来源 + [立即解冻] [稍后提醒] + 热键提示；
250ms 轮询状态文件，任何来源复位后滑出自动消失。
本模块的纯逻辑函数（状态读取/请求写入/重提醒判定/动画位移序列）
不依赖 tkinter，可单独测试；main() 为生产弹窗入口。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .freeze_notify import LOCK_FILE, REQ_FILE, STATE_FILE

FRAME_MS = 16               # 动画帧间隔（约 60fps）
SLIDE_MS = 240              # 滑入/滑出时长（对称原则：同长反向）
POLL_MS = 250               # 状态文件轮询间隔
WIN_W = 440                 # 弹窗尺寸
WIN_H = 210
MARGIN_RIGHT = 16           # 落位：主屏右下角
MARGIN_BOTTOM = 48          # 避开任务栏


def read_state(audit_dir: str) -> dict | None:
    """读 estop-state.json；不存在/非法返回 None。"""
    try:
        return json.loads((Path(audit_dir) / STATE_FILE)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_reset_request(audit_dir: str, seq: int) -> None:
    """写 estop-reset.req（立即解冻请求，携带其响应的状态 seq）。"""
    (Path(audit_dir) / REQ_FILE).write_text(
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


def slide_in_xs(screen_w: int, win_w: int = WIN_W) -> list[int]:
    """滑入 x 位移序列（屏外右缘 → 右下角，ease-out 三次方）。"""
    n = SLIDE_MS // FRAME_MS                     # 15 帧
    start, target = screen_w, screen_w - win_w - MARGIN_RIGHT
    out = []
    for i in range(n):
        t = i / (n - 1)                          # 0 → 1（含首尾）
        ease = 1 - (1 - t) ** 3
        out.append(round(start + (target - start) * ease))
    return out


def slide_out_xs(screen_w: int, win_w: int = WIN_W) -> list[int]:
    """滑出 x 位移序列：与滑入逐帧反向（对称原则）。"""
    return list(reversed(slide_in_xs(screen_w, win_w)))


def main() -> None:
    """生产弹窗入口（Tk 主循环 + 状态机）。

    argv: <audit_dir> <remind_interval>
    状态机：SLIDE_IN → SHOWN ⇄ SNOOZED → SLIDE_OUT → 退出；
    状态文件 frozen=false（任何来源复位）即滑出退出。
    """
    import tkinter as tk

    audit_dir = sys.argv[1]
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0

    root = tk.Tk()
    root.title("DeskPilot 急停")
    root.overrideredirect(True)                  # toast 形态：无边框
    root.attributes("-topmost", True)
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    xs_in = slide_in_xs(screen_w, WIN_W)
    xs_out = slide_out_xs(screen_w, WIN_W)
    y = screen_h - WIN_H - MARGIN_BOTTOM
    root.geometry(f"{WIN_W}x{WIN_H}+{xs_in[0]}+{y}")

    tk.Label(root, text="DeskPilot 已冻结",
             font=("Microsoft YaHei UI", 13, "bold")).pack(pady=(16, 4))
    src = tk.Label(root, text="", font=("Microsoft YaHei UI", 9),
                   fg="#555555", wraplength=WIN_W - 40, justify="left")
    src.pack()
    tk.Label(root, text="AI 的写操作已全部拒绝（EMERGENCY_STOP）；"
                        "可随时按 Ctrl+Shift+F11 直接解冻，本窗口会自动消失",
             font=("Microsoft YaHei UI", 9), fg="#333333",
             wraplength=WIN_W - 40, justify="left").pack(pady=4)
    btns = tk.Frame(root)
    btns.pack(pady=8)

    holder = {"state": "SLIDE_IN", "snooze_start": 0.0, "frames": list(xs_in),
              "last_seq": None}

    def refresh_source():
        st = read_state(audit_dir)
        if st:
            holder["last_seq"] = int(st.get("seq", 0))
            src.config(text=f"触发：{st.get('source', '')} · "
                            f"{str(st.get('ts', ''))[:19]}")

    def on_reset_now():
        # 点击即时反馈：先置灰再发请求；若请求未被消费（仍冻结），
        # poll 会在下一拍恢复按钮——点没点中一眼可辨（ISS-0004 v0.4）。
        st = read_state(audit_dir)
        seq = int(st["seq"]) if st and "seq" in st else holder["last_seq"]
        if seq is None:
            return
        write_reset_request(audit_dir, seq)
        btn_reset.config(text="解冻请求已发送…", state="disabled")

    def on_snooze():
        import time
        holder["state"] = "SNOOZE_OUT"
        holder["frames"] = list(xs_out)
        holder["snooze_start"] = time.monotonic()
        root.after(FRAME_MS, slide_step)         # 按钮回调须自启动画链

    btn_reset = tk.Button(btns, text="立即解冻", width=12,
                          command=on_reset_now)
    btn_reset.pack(side="left", padx=10)
    tk.Button(btns, text=f"稍后提醒（{interval:.0f}s）", width=16,
              command=on_snooze).pack(side="left", padx=10)

    def heartbeat():
        try:
            (Path(audit_dir) / LOCK_FILE).write_text(
                f"pid={os.getpid()}", encoding="utf-8")
        except OSError:
            pass
        root.after(1000, heartbeat)

    def slide_step():
        """滑动画帧驱动：frames 播完进入下一阶段。"""
        frames = holder["frames"]
        if frames:
            x = frames.pop(0)
            root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
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
        # 点击反馈的回落：请求发出后一拍（250ms）仍冻结 = 未被消费，恢复按钮可重试
        if (state == "SHOWN" and frozen
                and str(btn_reset["state"]) == "disabled"):
            btn_reset.config(text="立即解冻", state="normal")
        if state == "SHOWN":
            if next_action("SHOWN", frozen) == "slide_out_exit":
                holder["state"] = "SLIDE_OUT"
                holder["frames"] = list(xs_out)
                root.after(FRAME_MS, slide_step)
                return
        elif state == "SNOOZED":
            if not frozen:
                root.destroy()                   # 已隐藏，直接退出
                return
            if should_remind(holder["snooze_start"], time.monotonic(),
                             True, interval):
                holder["state"] = "SLIDE_IN"
                holder["frames"] = list(xs_in)
                root.deiconify()
                refresh_source()
                root.after(FRAME_MS, slide_step)
                return
        root.after(POLL_MS, poll)

    refresh_source()
    heartbeat()
    root.after(FRAME_MS, slide_step)
    root.mainloop()
    try:
        (Path(audit_dir) / LOCK_FILE).unlink(missing_ok=True)
    except OSError:
        pass
