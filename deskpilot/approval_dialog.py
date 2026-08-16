"""审批弹窗独立进程（M3，功能设计说明书 §6.1）。

以独立进程运行：展示操作描述、操作指纹说明与倒计时；
按钮「批准一次」/「拒绝」；倒计时结束默认拒绝（fail-closed）。
人类决定写入结果文件，由 TkApprovalChannel 轮询消费。
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path


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
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(root, text="以下操作需要你的批准：",
             font=("Microsoft YaHei", 11, "bold")).pack(
        padx=28, pady=(18, 6))
    tk.Label(root, text=description, wraplength=420, justify="left",
             font=("Microsoft YaHei", 10)).pack(padx=28, pady=6)

    remaining = [timeout_s]
    timer_label = tk.Label(
        root, text=f"{remaining[0]} 秒后默认拒绝",
        font=("Microsoft YaHei", 9), fg="gray")
    timer_label.pack(pady=(2, 8))

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

    bar = tk.Frame(root)
    bar.pack(pady=(2, 18))
    tk.Button(bar, text="批准一次", width=12,
              command=lambda: decide("approve")).pack(side="left", padx=8)
    tk.Button(bar, text="拒绝", width=12,
              command=lambda: decide("deny")).pack(side="left", padx=8)

    def tick() -> None:
        remaining[0] -= 1
        if remaining[0] <= 0:
            decide("timeout")
            return
        timer_label.config(text=f"{remaining[0]} 秒后默认拒绝")
        root.after(1000, tick)

    root.after(1000, tick)
    root.mainloop()


if __name__ == "__main__":
    main()
