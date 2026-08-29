"""冻结通知 owner 侧（详细设计 §11.6，ISS-0004 / ISS-0006）。

estop 持有进程（daemon / 本地直跑）装配本类：
- on_state_change：seq 共享单调自增，随 estop 置位/复位原子重写状态文件；
  置位时拉起弹窗（不做存活猜测，单例由子进程命名互斥体兜底）；
- check_reset_request：由甩角轮询线程 50ms tick 兼任调用，按 ISS-0006 §6
  协议（先验后删）消费弹窗的"立即解冻"请求；
- sync_local_with_shared_state：本地 frozen ∧ 共享 frozen=false 时本地复位
  （解冻全局生效）。
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
REQ_PREFIX = "estop-reset-"       # ISS-0006 §6：req 文件名 <REQ_PREFIX><seq>.req
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
        """estop 状态变化回调：seq 共享单调自增，原子重写状态文件；
        置位时拉起弹窗（owner 不做存活猜测，单例由子进程互斥兜底，ISS-0006）。"""
        self._seq = self._read_shared_seq() + 1
        state = {"frozen": frozen, "seq": self._seq, "source": source,
                 "ts": datetime.now().astimezone().isoformat()}
        tmp = self._dir / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._dir / STATE_FILE)      # 原子重写，防读半截
        if frozen:
            self._spawn(str(self._dir))

    def check_reset_request(self, estop) -> None:
        """50ms tick：消费弹窗解冻请求（ISS-0006 §6 协议，先验后删）。

        设共享 seq 为 S、req 序号为 N：
        N<S → 删除（陈旧清理）；N=S ∧ estop 已冻结 → 复位并删除；
        N=S ∧ estop 未冻结 ∧ 共享 frozen=false → 删除（请求作废）；
        N=S ∧ estop 未冻结 ∧ 共享 frozen=true → 保留（留给冻结中的 owner）；
        N>S → 保留（异常时序，不得删除）。
        """
        shared = self._read_shared_state()
        if shared is None:
            return
        s = int(shared.get("seq", 0))
        shared_frozen = bool(shared.get("frozen"))
        for req in sorted(self._dir.glob(f"{REQ_PREFIX}*.req")):
            try:
                n = int(req.stem.removeprefix(REQ_PREFIX))
            except ValueError:
                req.unlink(missing_ok=True)          # 非协议命名，按垃圾清理
                continue
            if n < s:
                req.unlink(missing_ok=True)
            elif n == s:
                if estop.is_frozen():
                    req.unlink(missing_ok=True)
                    estop.dialog_reset()
                elif not shared_frozen:
                    req.unlink(missing_ok=True)
                # else: 共享仍冻结而本进程未冻结 → 保留给冻结中的 owner
            # else: N > S → 保留

    def sync_local_with_shared_state(self, estop) -> bool:
        """解冻全局同步（ISS-0006 §6）：本地 frozen ∧ 共享 frozen=false
        → 调 estop.shared_sync_reset() 并返回 True；否则 False。"""
        shared = self._read_shared_state()
        if (estop.is_frozen() and shared is not None
                and shared.get("frozen") is False):
            estop.shared_sync_reset()
            return True
        return False

    # ---- 内部 ----

    def _read_shared_seq(self) -> int:
        """共享 seq 读取（方案 C）：状态文件缺失/非法按 0 计（跨进程不回退）。"""
        st = self._read_shared_state()
        return int(st.get("seq", 0)) if st else 0

    def _read_shared_state(self) -> dict | None:
        """读 estop-state.json；不存在/非法返回 None。"""
        try:
            return json.loads((self._dir / STATE_FILE)
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

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
