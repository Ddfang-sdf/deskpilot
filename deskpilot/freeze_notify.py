"""冻结通知 owner 侧（详细设计 §11.6，ISS-0004 / ISS-0006 / ISS-0092 / ISS-0093）。

estop 持有进程（daemon / 本地直跑）装配本类：
- on_state_change：seq 共享单调自增，随 estop 置位/复位原子重写状态文件
  （ISS-0092 ②：经 _write_shared_state 有限重试，终败审计不上抛）；
  置位时拉起弹窗（不做存活猜测，单例由子进程命名互斥体兜底），并持有
  本轮子进程 Popen 句柄（只存属主内存,每轮新起=一次性）；
- check_dialog_exit：由甩角轮询线程 50ms tick 兼任调用（ISS-0093 §9.2
  退出码通道——子进程点「立即解冻」= 关窗 + 退出码 EXIT_RESET(73)；
  零文件、零 socket、零命名管道,req 文件邮箱已整体废止）；
- sync_local_with_shared_state：单向对账（ISS-0093 §9.4 v0.5）——本地
  内存态恒为权威：shared frozen=false ∧ 本地冻结 → 修共享回 true,
  **绝不本地复位**（E7 旁路关闭,任何进程写 state 文件不再能解冻）；
  本地未冻 ∧ shared frozen=true → 修共享为 false（ISS-0092 ④ fg04 语义）。
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
from .audit_events import (EV_SHARED_STATE_RECONCILED,
                           EV_SHARED_STATE_WRITE_FAILED)

STATE_FILE = "estop-state.json"
# ISS-0093:req 文件邮箱协议(命名常量+消费方法)整体废止——文件的存在
# 不构成人类意愿的证明,持 MCP 的 AI 可自行复现解冻。
# ISS-0061:弹窗心跳锁两常量已删(孤儿死代码)——弹窗单例自 ISS-0046 B
# 起收口到命名互斥体,锁文件机制整体退役,勿再引入


class FreezeNotifier:
    """冻结通知装配器：状态文件 + 弹窗单例 + 解冻请求消费。"""

    def __init__(self, audit_dir: str, clock=time.monotonic, spawn=None,
                 remind_interval: float = DEFAULT_FREEZE_REMIND_INTERVAL,
                 dialog_service=None, audit=None, on_reset=None):
        self._dir = Path(audit_dir)
        self._clock = clock
        self._spawn = spawn or self._default_spawn
        self._remind = remind_interval
        self._dialog_service = dialog_service   # ISS-0008 P6：线程弹窗（可选）
        self._audit = audit          # ISS-0092 ⑤：写失败/对账修复审计（可选）
        # ISS-0093 §9.1：进程内形态「立即解冻」直调回调（装配侧注入
        # estop.dialog_reset）；§9.2：本轮子进程 Popen 句柄（退出码通道,
        # 只存属主内存,每轮冻结新起新句柄=一次性）
        self.on_reset = on_reset
        self._dialog_proc = None
        self._seq = 0
        self._state_cache: dict | None = None    # ISS-0008 P7：读缓存（仅读时更新）
        self._state_mtime: float | None = None
        self._state_reads_n = 0

    @property
    def seq(self) -> int:
        """当前状态序号（测试观测口）。"""
        return self._seq

    @property
    def state_reads(self) -> int:
        """共享状态文件实际读取次数（ISS-0008 §6 测试观测口；mtime 跳读不计）。"""
        return self._state_reads_n

    def on_state_change(self, frozen: bool, source: str) -> None:
        """estop 状态变化回调：seq 共享单调自增，原子重写状态文件；
        置位时拉起弹窗（owner 不做存活猜测，单例由子进程互斥兜底，ISS-0006）。

        ISS-0092 ②：写回经 _write_shared_state 有限重试；终败只留审计
        不上抛（调用线程不许死）；frozen 边沿弹窗照拉（fail-safe：
        写失败不吞冻结通知，人类必须看得见冻结）。
        """
        self._seq = self._read_shared_seq() + 1
        state = {"frozen": frozen, "seq": self._seq, "source": source,
                 "ts": datetime.now().astimezone().isoformat()}
        self._write_shared_state(state)
        if frozen:
            # ISS-0093 §9.2：持有本轮 Popen 句柄(一次性;spawn 替身/线程
            # 弹窗形态返回 None,退出码消费自然空转)
            self._dialog_proc = self._spawn(str(self._dir))

    def check_dialog_exit(self, estop) -> None:
        """50ms tick：子进程弹窗退出码消费（ISS-0093 §9.2，定案通道）。

        poll 本轮 Popen 句柄：退出码==EXIT_RESET(73)=人类点击「立即解冻」
        → estop.dialog_reset()；其余退出码（关窗/snooze/被杀）与 None
        （仍在运行）不具解冻语义，维持既有重提醒逻辑。句柄一次性：
        进程终态即消费完毕释放，等下轮冻结边沿新起。
        """
        proc = self._dialog_proc
        if proc is None:
            return
        from .freeze_dialog import EXIT_RESET
        code = proc.poll()
        if code is None:
            return                              # 子进程仍在运行
        self._dialog_proc = None                # 一次性：终态即消费
        if code == EXIT_RESET:
            estop.dialog_reset()

    def sync_local_with_shared_state(self, estop) -> bool:
        """共享状态单向对账（ISS-0093 §9.4 v0.5）：本地内存态恒为权威，
        两个方向都只修共享、绝不改本地。

        本地冻结 ∧ 共享 frozen=false → 修共享回 true（E7 旁路关闭：
        任何进程直写 state 文件 false 不再能解冻；「复位-共享同步」
        事件与 shared_sync_reset 已退役，绝不本地复位）；
        本地未冻 ∧ 共享 frozen=true → 修共享为 false（ISS-0092 ④ fg04
        语义沿用：本地权威防假象）。
        修复成功返回 True；写失败返回 False 下轮再试；无对账需求 False。
        """
        shared = self._read_shared_state()
        if shared is None:
            return False
        local = estop.is_frozen()
        shared_frozen = bool(shared.get("frozen"))
        if local == shared_frozen:
            return False
        return self._repair_shared_frozen(local, shared)

    def _repair_shared_frozen(self, frozen: bool, shared: dict) -> bool:
        """以本地内存态为权威重写共享 frozen（单向对账的落盘半）。"""
        self._seq = int(shared.get("seq", 0)) + 1
        state = {"frozen": frozen, "seq": self._seq,
                 "source": EV_SHARED_STATE_RECONCILED,
                 "ts": datetime.now().astimezone().isoformat()}
        if not self._write_shared_state(state):
            return False
        if self._audit is not None:
            self._audit.record_event(
                EV_SHARED_STATE_RECONCILED,
                f"本地 frozen={frozen} 而共享 frozen={not frozen}"
                f"（原 seq={shared.get('seq')},源={shared.get('source')}），"
                f"已按本地权威重写 frozen={frozen} seq={self._seq}")
        return True

    # ---- 内部 ----

    def _write_shared_state(self, state: dict) -> bool:
        """共享状态原子重写（ISS-0092 ②）：os.replace 失败有限重试
        （退避 0.05/0.15/0.45s），每轮先预清同名旧 tmp；终败审计
        「共享状态写失败」+ 清孤儿 tmp，返回 False 不上抛——
        写回失败不得杀死调用线程（实机事故：异常曾沿甩角线程致死）。
        """
        tmp = self._dir / (STATE_FILE + ".tmp")
        payload = json.dumps(state, ensure_ascii=False)
        last: OSError | None = None
        for attempt, backoff in enumerate((0.05, 0.15, 0.45), start=1):
            try:
                tmp.unlink(missing_ok=True)      # 预清同名旧 tmp（孤儿残留）
                tmp.write_text(payload, encoding="utf-8")
                os.replace(tmp, self._dir / STATE_FILE)  # 原子重写，防读半截
            except OSError as e:
                last = e
                time.sleep(backoff)
                continue
            self._state_mtime = None             # 写后显式使读缓存失效
            self._state_cache = None
            return True
        if self._audit is not None:
            self._audit.record_event(
                EV_SHARED_STATE_WRITE_FAILED,
                f"重试 {attempt} 次仍失败: {last!r}; seq={state.get('seq')}")
        tmp.unlink(missing_ok=True)              # 清孤儿 tmp
        return False

    def _read_shared_seq(self) -> int:
        """共享 seq 读取（方案 C）：状态文件缺失/非法按 0 计（跨进程不回退）。"""
        st = self._read_shared_state()
        return int(st.get("seq", 0)) if st else 0

    def _read_shared_state(self) -> dict | None:
        """读 estop-state.json；不存在/非法返回 None。

        ISS-0008 P7 快路：mtime 未变直接命中缓存，不重复读盘解析。
        """
        path = self._dir / STATE_FILE
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if mtime == self._state_mtime and self._state_cache is not None:
            return self._state_cache
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        self._state_reads_n += 1
        self._state_mtime = mtime
        self._state_cache = data
        return data

    def _default_spawn(self, audit_dir: str):
        """拉起弹窗（ISS-0008 P6：有 DialogService 走共享线程；
        否则回退子进程——onefile 经打包入口分发；剥离 _MEIPASS2，
        与 approval_ui 同款约束）。

        返回值（ISS-0093 §9.2）：子进程形态返回 Popen 句柄（属主持有,
        退出码通道）；线程弹窗形态返回 None（on_reset 进程内直调,无句柄）。
        """
        if self._dialog_service is not None:
            # ISS-0093 §9.1：freeze payload 注入进程内回调 on_reset
            # （模式同构 enroll_notice 的 payload["on_undo"] 先例）
            self._dialog_service.show(
                "freeze", {"audit_dir": audit_dir, "interval": self._remind,
                           "target_screen": self._mouse_screen(),
                           "on_reset": self.on_reset})
            return None
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--freeze-notify", audit_dir,
                   f"{self._remind:.0f}"]
            env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2"}
        else:
            cmd = [sys.executable, "-m", "deskpilot.freeze_dialog", audit_dir,
                   f"{self._remind:.0f}"]
            env = None
        try:
            return subprocess.Popen(cmd, env=env)
        except OSError:
            return None             # 弹窗是通知层，拉起失败不影响冻结语义

    @staticmethod
    def _mouse_screen() -> dict | None:
        """ISS-0097 裁定(2026-09-20 sdfang):冻结弹窗一律主屏——废止
        ISS-0007 B 的鼠标所在屏跟随(方法名留兼容,语义已改)。"""
        from .monitors import enum_monitors
        mons = enum_monitors()
        return next((m for m in mons if m.get("is_primary")),
                    mons[0] if mons else None)
