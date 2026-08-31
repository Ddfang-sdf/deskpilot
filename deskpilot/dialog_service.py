"""弹窗线程服务（ISS-0008 §6，P6）。

单 Tk 线程常驻：start() 幂等；show(kind, payload) 把弹窗请求投递到 Tk 线程；
弹窗异常不波及调用方线程；visible_latency_s / thread_count 为测试观测口。
生产形态下由本服务的共享 Tk root 承载各弹窗（Toplevel），替代每次拉起的
子进程 exe（一次性 onefile 冷解压 1~4s → 线程内 <300ms）。
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

_STOP = object()


class DialogService:
    """弹窗线程服务（ISS-0008 §6 公开入口）。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 window_factory: Callable[[str, dict], Any] | None = None):
        self._clock = clock
        # ISS-0013：默认装配必须接线——window_factory 缺省（生产形态）时
        # 触达真实 _default_factory；缺 or 接线曾致生产弹窗全静默（P0）
        self._factory = window_factory or self._default_factory
        self._use_tk = window_factory is None   # 仅默认工厂走共享 Tk 宿主
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._tk_root = None
        self.visible_latency_s: float = 0.0
        self.thread_count: int = 0

    def start(self) -> None:
        """启动弹窗线程（幂等）。"""
        if self._thread is not None:
            return
        if self._use_tk:
            target = self._tk_loop
        else:
            # 注入工厂形态（测试/定制）：纯队列循环，不创建 Tk（Tk 非线程安全）
            target = self._queue_loop
        self._thread = threading.Thread(target=target, daemon=True,
                                        name="deskpilot-dialogs")
        self._thread.start()
        self.thread_count = 1

    def show(self, kind: str, payload: dict) -> None:
        """投递一次弹窗请求（kind ∈ {"approval", "freeze"}）。"""
        self._queue.put((kind, payload, self._clock()))

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(_STOP)
            self._thread.join(timeout=3)
            self._thread = None
            self.thread_count = 0

    # ---- 内部 ----

    def _queue_loop(self) -> None:
        """纯队列循环（注入工厂形态）：无 Tk 依赖。"""
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            self._dispatch(item)

    def _tk_loop(self) -> None:
        """Tk 宿主线程：持有一个隐藏 root，50ms 排空队列并派发工厂。"""
        import tkinter as tk
        self._tk_root = tk.Tk()
        self._tk_root.withdraw()
        self._tk_root.after(50, self._drain)
        self._tk_root.mainloop()

    def _dispatch(self, item) -> None:
        kind, payload, t0 = item
        try:
            self._factory(kind, payload)
        except Exception:
            # ISS-0013 B：容错不阻断调用方的语义不变，但吞错必须留痕——
            # 静默吞异常曾让"默认工厂未接线"隐形两天（P0）
            import sys
            import traceback
            print(f"弹窗派发异常（{kind}）:", file=sys.stderr)
            traceback.print_exc()
        self.visible_latency_s = self._clock() - t0

    def _drain(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _STOP:
                self._tk_root.destroy()
                return
            self._dispatch(item)
        self._tk_root.after(50, self._drain)

    def _default_factory(self, kind: str, payload: dict) -> None:
        """生产工厂：在共享 Tk 线程内建窗（经各弹窗模块的 build_window）。"""
        if kind == "approval":
            from .approval_dialog import build_window
            build_window(self._tk_root, payload["description"],
                         payload["result_path"], payload["timeout_s"],
                         payload.get("image_path", ""),
                         target_screen=payload.get("target_screen"),
                         enroll=payload.get("enroll"))
        elif kind == "freeze":
            from .freeze_dialog import build_window
            build_window(self._tk_root, payload["audit_dir"],
                         payload["interval"],
                         target_screen=payload.get("target_screen"))
        elif kind == "enroll_notice":
            # ISS-0012 E4：入白确认 toast（[撤销] 回调由装配侧注入）
            from .whitelist_window import build_enroll_notice
            build_enroll_notice(self._tk_root, payload["process"],
                                on_undo=payload["on_undo"])
        elif kind == "revoke":
            # ISS-0012 E3：AI 请求撤回的人类确认窗
            from .whitelist_window import build_revoke_confirm
            build_revoke_confirm(self._tk_root, payload["process"],
                                 payload["result_path"], payload["timeout_s"])
        else:
            raise ValueError(f"未知弹窗类型: {kind}")


_SERVICE: DialogService | None = None


def get_dialog_service() -> DialogService:
    """进程级单例（装配侧使用）。"""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = DialogService()
        _SERVICE.start()
    return _SERVICE
