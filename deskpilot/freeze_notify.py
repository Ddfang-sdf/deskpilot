"""冻结通知 owner 侧（详细设计 §11.6，ISS-0004 / ISS-0006 / ISS-0092）。

estop 持有进程（daemon / 本地直跑）装配本类：
- on_state_change：seq 共享单调自增，随 estop 置位/复位原子重写状态文件
  （ISS-0092 ②：经 _write_shared_state 有限重试，终败审计不上抛）；
  置位时拉起弹窗（不做存活猜测，单例由子进程命名互斥体兜底）；
- check_reset_request：由甩角轮询线程 50ms tick 兼任调用，按 ISS-0006 §6
  协议（先验后删；ISS-0092 ③：复位成功才删，失败保留下轮重试）消费弹窗的
  "立即解冻"请求；
- sync_local_with_shared_state：本地 frozen ∧ 共享 frozen=false 时本地复位
  （解冻全局生效）；ISS-0092 ④反向对账：本地未冻 ∧ 共享 frozen=true →
  以本地内存态为权威修复共享 frozen=false（禁止反向灌回=绕过人类解冻通道）。
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
# ISS-0061:弹窗心跳锁两常量已删(孤儿死代码)——弹窗单例自 ISS-0046 B
# 起收口到命名互斥体,锁文件机制整体退役,勿再引入


class FreezeNotifier:
    """冻结通知装配器：状态文件 + 弹窗单例 + 解冻请求消费。"""

    def __init__(self, audit_dir: str, clock=time.monotonic, spawn=None,
                 remind_interval: float = DEFAULT_FREEZE_REMIND_INTERVAL,
                 dialog_service=None, audit=None):
        self._dir = Path(audit_dir)
        self._clock = clock
        self._spawn = spawn or self._default_spawn
        self._remind = remind_interval
        self._dialog_service = dialog_service   # ISS-0008 P6：线程弹窗（可选）
        self._audit = audit          # ISS-0092 ⑤：写失败/对账修复审计（可选）
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
            self._spawn(str(self._dir))

    def check_reset_request(self, estop) -> None:
        """50ms tick：消费弹窗解冻请求（ISS-0006 §6 协议，先验后删）。

        设共享 seq 为 S、req 序号为 N：
        N<S → 删除（陈旧清理）；N=S ∧ estop 已冻结 → 复位成功才删除
        （ISS-0092 ③：先复位后删——复位失败 req 保留下轮重试，_reset
        未冻结时 no-op 幂等，estop.py 复位语义；失败审计「解冻请求复位
        失败」，异常不上抛：调用线程不许死）；
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
                    try:
                        estop.dialog_reset()
                    except Exception as e:                    # noqa: BLE001
                        if self._audit is not None:
                            self._audit.record_event(
                                "解冻请求复位失败",
                                f"req={req.name}: {e!r}（保留待下轮重试）")
                        continue
                    req.unlink(missing_ok=True)
                elif not shared_frozen:
                    req.unlink(missing_ok=True)
                # else: 共享仍冻结而本进程未冻结 → 保留给冻结中的 owner
            # else: N > S → 保留

    def sync_local_with_shared_state(self, estop) -> bool:
        """解冻全局同步（ISS-0006 §6）：本地 frozen ∧ 共享 frozen=false
        → 调 estop.shared_sync_reset() 并返回 True。

        ISS-0092 ④双向对账：本地未冻结 ∧ 共享 frozen=true → 以本地内存态
        为权威（owner 协议单属主，ISS-0084）重写共享 frozen=false 并审计
        「共享状态对账修复」，返回 True（写失败则 False 下轮再试）。
        **禁止反向**：共享 true 灌回本地 = 绕过人类解冻通道（fail-closed
        方向性，解冻仅人类通道：热键/CLI/弹窗）。
        """
        shared = self._read_shared_state()
        if (estop.is_frozen() and shared is not None
                and shared.get("frozen") is False):
            estop.shared_sync_reset()
            return True
        if (not estop.is_frozen() and shared is not None
                and shared.get("frozen") is True):
            self._seq = int(shared.get("seq", 0)) + 1
            state = {"frozen": False, "seq": self._seq,
                     "source": "共享状态对账修复",
                     "ts": datetime.now().astimezone().isoformat()}
            if not self._write_shared_state(state):
                return False
            if self._audit is not None:
                self._audit.record_event(
                    "共享状态对账修复",
                    f"本地未冻结而共享 frozen=true（原 seq="
                    f"{shared.get('seq')},源={shared.get('source')}），"
                    f"已重写 frozen=false seq={self._seq}")
            return True
        return False

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
                "共享状态写失败",
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

    def _default_spawn(self, audit_dir: str) -> None:
        """拉起弹窗（ISS-0008 P6：有 DialogService 走共享线程；
        否则回退子进程——onefile 经打包入口分发；剥离 _MEIPASS2，
        与 approval_ui 同款约束）。"""
        if self._dialog_service is not None:
            # ISS-0007 B：冻结弹窗按鼠标所在屏落位
            self._dialog_service.show(
                "freeze", {"audit_dir": audit_dir, "interval": self._remind,
                           "target_screen": self._mouse_screen()})
            return
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

    @staticmethod
    def _mouse_screen() -> dict | None:
        """ISS-0097 裁定(2026-09-20 sdfang):冻结弹窗一律主屏——废止
        ISS-0007 B 的鼠标所在屏跟随(方法名留兼容,语义已改)。"""
        from .monitors import enum_monitors
        mons = enum_monitors()
        return next((m for m in mons if m.get("is_primary")),
                    mons[0] if mons else None)
