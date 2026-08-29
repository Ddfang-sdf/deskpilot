"""本地审批弹窗通道（M3，功能设计说明书 §6.1）。

同步阻塞语义（ISS-0003）：request() 挂起调用方，同步等待人类裁决——
弹窗以独立进程运行（tkinter 对话框：批准一次 / 拒绝，60 秒倒计时，
超时默认拒绝），裁决结果经结果文件回传；返回 "approve" / "deny" / "timeout"。
授权记录由 ApprovalManager 在服务内部签发，不经 AI（INV-4）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

_DIALOG_TIMEOUT_SECONDS = 60.0
_POLL_INTERVAL = 0.1


class TkApprovalChannel:
    """M3 生产审批通道（同步等待裁决）。"""

    def __init__(self, timeout: float = _DIALOG_TIMEOUT_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 popen_factory: Callable[..., Any] | None = None,
                 result_root: str | None = None,
                 dialog_service=None):
        self._timeout = timeout
        self._clock = clock
        self._popen = popen_factory or subprocess.Popen
        self._dialog_service = dialog_service   # ISS-0008 P6：线程弹窗（可选）
        self._result_root = Path(result_root) if result_root else Path(
            sys.executable).parent.parent  # 默认服务工作目录
        self.last_request: dict[str, str] | None = None   # 测试观测口

    def request(self, description: str, fingerprint: str,
                image_path: str | None = None) -> str:
        """向人类请求批准并同步等待裁决（ISS-0003）。

        弹窗独立进程运行，裁决经结果文件回传；返回 "approve" / "deny" /
        "timeout"。任何异常（描述写盘失败、结果读取失败、非法内容）一律按
        拒绝类返回（fail-closed）。"""
        request_id = uuid.uuid4().hex[:16]
        result_path = self._result_root / f"deskpilot-approval-{request_id}.result"
        desc_path = self._result_root / f"deskpilot-approval-{request_id}.desc"
        try:
            desc_path.write_text(description, encoding="utf-8")
        except OSError:
            return "deny"
        self.last_request = {"description": description,
                             "fingerprint": fingerprint,
                             "result_path": str(result_path)}
        self._spawn_dialog(desc_path, result_path, image_path or "")
        deadline = self._clock() + self._timeout
        while self._clock() < deadline:
            try:
                if result_path.exists():
                    decision = result_path.read_text(encoding="utf-8").strip()
                    result_path.unlink(missing_ok=True)
                    if decision in ("approve", "deny", "timeout"):
                        return decision
                    return "deny"      # 非法内容按拒绝（fail-closed）
            except OSError:
                return "deny"
            time.sleep(_POLL_INTERVAL)
        return "timeout"

    # ---- 内部 ----

    def _spawn_dialog(self, desc_path: Path, result_path: Path,
                      image_path: str = "") -> None:
        timeout = f"{self._timeout:.0f}"
        if self._dialog_service is not None:
            # ISS-0008 P6：共享 Tk 线程内建窗，替代拉起子进程 exe
            try:
                description = desc_path.read_text(encoding="utf-8",
                                                  errors="replace")
            except OSError:
                description = "(审批描述读取失败)"
            self._dialog_service.show("approval", {
                "description": description, "result_path": str(result_path),
                "timeout_s": self._timeout, "image_path": image_path})
            return
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
