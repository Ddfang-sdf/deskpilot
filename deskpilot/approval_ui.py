"""本地审批弹窗通道（M3，功能设计说明书 §6.1）。

fire-and-forget：request() 立即返回 False——AI 即时收到 NEEDS_APPROVAL，
不阻塞 MCP 处理与写锁（详细设计 §2.4）；审批弹窗以独立进程运行
（tkinter 对话框：批准一次 / 拒绝，60 秒倒计时，超时默认拒绝）。
人类批准后由本通道的后台轮询线程回调签发令牌——令牌不经 AI（INV-4）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

_DIALOG_TIMEOUT_SECONDS = 60.0
_POLL_INTERVAL = 0.1


class TkApprovalChannel:
    """M3 生产审批通道。"""

    def __init__(self, on_approved: Callable[[str], None],
                 timeout: float = _DIALOG_TIMEOUT_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 popen_factory: Callable[..., Any] | None = None,
                 result_root: str | None = None):
        self._on_approved = on_approved
        self._timeout = timeout
        self._clock = clock
        self._popen = popen_factory or subprocess.Popen
        self._result_root = Path(result_root) if result_root else Path(
            sys.executable).parent.parent  # 默认服务工作目录
        self._inflight: dict[str, float] = {}   # 指纹 -> 弹窗截止时间（在途去重）
        self.last_request: dict[str, str] | None = None   # 测试观测口

    def request(self, description: str, fingerprint: str,
                image_path: str | None = None) -> bool:
        now = self._clock()
        # 清理已过期在途项；同指纹弹窗在途期间不重复弹窗（AI 重试不产生弹窗堆叠）
        self._inflight = {fp: dl for fp, dl in self._inflight.items() if dl > now}
        if fingerprint in self._inflight:
            return False
        request_id = uuid.uuid4().hex[:16]
        result_path = self._result_root / f"deskpilot-approval-{request_id}.result"
        desc_path = self._result_root / f"deskpilot-approval-{request_id}.desc"
        try:
            desc_path.write_text(description, encoding="utf-8")
        except OSError:
            return False
        self.last_request = {"description": description,
                             "fingerprint": fingerprint,
                             "result_path": str(result_path)}
        self._inflight[fingerprint] = now + self._timeout
        self._spawn_dialog(desc_path, result_path, image_path or "")
        threading.Thread(
            target=self._poll_result, args=(fingerprint, result_path),
            daemon=True).start()
        return False

    # ---- 内部 ----

    def _spawn_dialog(self, desc_path: Path, result_path: Path,
                      image_path: str = "") -> None:
        timeout = f"{self._timeout:.0f}"
        if getattr(sys, "frozen", False):
            # PyInstaller onefile：sys.executable 是 deskpilot.exe 自身，
            # -m 参数无效，弹窗由打包入口按 --approval-dialog 分发。
            # 子进程须剥离 _MEIPASS2：否则与父进程共享 onefile 解压目录，
            # 父进程先退出会删除目录，子进程读取依赖文件中途崩溃。
            cmd = [sys.executable, "--approval-dialog",
                   str(desc_path), str(result_path), timeout, image_path]
            env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2"}
        else:
            cmd = [sys.executable, "-m", "deskpilot.approval_dialog",
                   str(desc_path), str(result_path), timeout, image_path]
            env = None
        try:
            self._popen(cmd, env=env)
        except OSError:
            pass

    def _poll_result(self, fingerprint: str, result_path: Path) -> None:
        deadline = self._clock() + self._timeout
        while self._clock() < deadline:
            try:
                if result_path.exists():
                    decision = result_path.read_text(encoding="utf-8").strip()
                    result_path.unlink(missing_ok=True)
                    if decision == "approve":
                        self._on_approved(fingerprint)
                    break
            except OSError:
                break
            time.sleep(_POLL_INTERVAL)
        self._inflight.pop(fingerprint, None)   # 批复/超时后解除在途标记
