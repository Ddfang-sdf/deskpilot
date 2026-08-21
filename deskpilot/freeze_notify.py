"""冻结通知 owner 侧（详细设计 §11.6，ISS-0004）。

estop 持有进程（daemon / 本地直跑）装配本类：
- on_state_change：随 estop 置位/复位原子重写状态文件；置位时单例拉起弹窗；
- check_reset_request：由甩角轮询线程 50ms tick 兼任调用，消费弹窗的
  "立即解冻"请求（seq 守卫防陈旧请求误解冻新一轮冻结）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .policy import DEFAULT_FREEZE_REMIND_INTERVAL

STATE_FILE = "estop-state.json"
REQ_FILE = "estop-reset.req"
LOCK_FILE = "estop-dialog.lock"
LOCK_MAX_AGE = 3.0          # 心跳龄超过 3s 视为弹窗已死，允许重新 spawn


class FreezeNotifier:
    """冻结通知装配器：状态文件 + 弹窗单例 + 解冻请求消费。"""

    def __init__(self, audit_dir: str, clock=time.monotonic, spawn=None,
                 remind_interval: float = DEFAULT_FREEZE_REMIND_INTERVAL):
        self._dir = Path(audit_dir)
        self._clock = clock
        self._spawn = spawn or self._default_spawn
        self._remind = remind_interval
        self._seq = 0

    @property
    def seq(self) -> int:
        """当前状态序号（测试观测口）。"""
        return self._seq

    def on_state_change(self, frozen: bool, source: str) -> None:
        """estop 状态变化回调：原子重写状态文件；置位时单例拉起弹窗。"""
        self._seq += 1
        state = {"frozen": frozen, "seq": self._seq, "source": source,
                 "ts": datetime.now().astimezone().isoformat()}
        tmp = self._dir / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._dir / STATE_FILE)      # 原子重写，防读半截
        if frozen and not self._dialog_alive():
            self._spawn(str(self._dir))

    def check_reset_request(self, estop) -> None:
        """50ms tick：消费弹窗解冻请求（seq 守卫，陈旧/未冻结一律丢弃）。"""
        req = self._dir / REQ_FILE
        try:
            if not req.exists():
                return
            data = json.loads(req.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        req.unlink(missing_ok=True)
        if not isinstance(data, dict):
            return
        if data.get("seq") == self._seq and estop.is_frozen():
            estop.dialog_reset()

    # ---- 内部 ----

    def _dialog_alive(self) -> bool:
        """单例守卫：lock 心跳龄 < LOCK_MAX_AGE 视为弹窗存活。"""
        try:
            return (time.time()
                    - (self._dir / LOCK_FILE).stat().st_mtime) < LOCK_MAX_AGE
        except OSError:
            return False

    def _default_spawn(self, audit_dir: str) -> None:
        """拉起弹窗子进程（onefile 经打包入口分发；剥离 _MEIPASS2，
        与 approval_ui 同款约束）。"""
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--freeze-notify", audit_dir,
                   f"{self._remind:.0f}"]
            env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2"}
        else:
            cmd = [sys.executable, "-m", "deskpilot.freeze_dialog", audit_dir,
                   f"{self._remind:.0f}"]
            env = None
        try:
            subprocess.Popen(cmd, env=env)
        except OSError:
            pass                    # 弹窗是通知层，拉起失败不影响冻结语义
