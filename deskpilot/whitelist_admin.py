"""运行期白名单管理（ISS-0012 §6，方案 A/D/E 核心）。

static（启动加载 + 永久入白热生效）与 session（会话放行，仅内存）两视图；
一切落盘修改由本模块原子完成（先写 .bak，临时文件替换），AI 全程无策略写路径。
自保护铁律：NEVER_ENROLL 进程（deskpilot.exe 自身）永不可入白。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from pathlib import Path
from typing import Mapping

import yaml

from .errors import PolicyError

# 自保护铁律（ISS-0012 约束）：本服务进程永不可入白——
# 防止 AI 用 deskpilot 自己的工具点击审批/管理窗口完成自我加白
NEVER_ENROLL = frozenset({"deskpilot.exe"})

_VALID_LEVELS = frozenset({"L0", "L1", "L2"})


def file_sha256(path: str) -> str:
    """ISS-0012 §6：文件 SHA-256 小写 hex（策略指纹用，纯函数）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class WhitelistAdmin:
    """ISS-0012 §6：运行期白名单状态（静态 ∪ 会话）与落盘。

    policy_path 为 None 时仅内存态（测试/兼容装配），永久变更与静态撤回
    报 PolicyError（fail-closed，不静默退化为内存）。
    """

    def __init__(self, policy_path: str | None, static: Mapping[str, str],
                 never_enroll: frozenset = NEVER_ENROLL, audit=None):
        self._path = Path(policy_path) if policy_path else None
        self._static: dict[str, str] = {str(k).strip().lower(): v
                                        for k, v in static.items()}
        self._session: dict[str, str] = {}
        self._never = frozenset(never_enroll)
        self._audit = audit
        self._lock = threading.Lock()
        self.notify_permanent = None     # 装配侧挂 E4 入白确认 toast 回调

    # ---- 查询 ----

    def cap_of(self, process: str) -> str | None:
        """进程级别上限（静态 ∪ 会话合并视图；进程名小写归一）。"""
        p = str(process).strip().lower()
        with self._lock:
            if p in self._session:
                return self._session[p]
            return self._static.get(p)

    def entries(self) -> dict:
        """{"static": {...}, "session": {...}}（快照副本）。"""
        with self._lock:
            return {"static": dict(self._static),
                    "session": dict(self._session)}

    # ---- 变更 ----

    def add_session(self, process: str, level: str = "L2") -> None:
        """会话放行（仅内存，重启失效）。"""
        p = self._norm(process)
        lv = self._check_level(level)
        self._check_enrollable(p)
        with self._lock:
            self._session[p] = lv

    def add_permanent(self, process: str, level: str = "L2") -> None:
        """永久入白：原子写 policy.yml（先 .bak）+ 内存热生效 + 审计。"""
        p = self._norm(process)
        lv = self._check_level(level)
        self._check_enrollable(p)
        with self._lock:
            self._write_disk(p, lv, remove=False)
            self._static[p] = lv
            self._session.pop(p, None)
        self._event("白名单入白-永久", f"{p} {lv}")
        if self.notify_permanent is not None:
            try:
                self.notify_permanent(p)       # E4 入白确认 toast（含撤销）
            except Exception:
                pass                           # 通知层异常不影响入白事实

    def remove(self, process: str) -> str | None:
        """撤回：静态命中改盘返回 "static"；会话命中返回 "session"；否则 None。"""
        p = str(process).strip().lower()
        with self._lock:
            if p in self._static:
                self._write_disk(p, None, remove=True)
                del self._static[p]
                self._event("白名单移除", p)
                return "static"
            if p in self._session:
                del self._session[p]
                return "session"
            return None

    def clear_session(self) -> int:
        """清空会话放行，返回清除条数。"""
        with self._lock:
            n = len(self._session)
            self._session.clear()
            return n

    # ---- 内部 ----

    def _norm(self, process: str) -> str:
        p = str(process).strip().lower()
        if not p:
            raise PolicyError("进程名不能为空")
        if "/" in p or "\\" in p:
            raise PolicyError(f"进程名非法（含路径分隔符）: {process!r}")
        return p

    def _check_level(self, level: str) -> str:
        lv = str(level).strip().upper()
        if lv not in _VALID_LEVELS:
            raise PolicyError(f"级别非法: {level}（须 L0/L1/L2）")
        return lv

    def _check_enrollable(self, proc: str) -> None:
        if proc in self._never:
            raise PolicyError(f"进程 {proc} 属自保护集，永不可入白")

    def _write_disk(self, proc: str, level: str | None, remove: bool) -> None:
        """原子改盘：读全量 → 改 whitelist 节 → 先 .bak → 临时文件替换。"""
        if self._path is None:
            raise PolicyError("无策略文件路径，永久变更不可用（fail-closed）")
        data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise PolicyError("策略文件顶层非映射，拒绝改写")
        wl = data.get("whitelist") or []
        if remove:
            wl = [i for i in wl
                  if str(i.get("process", "")).strip().lower() != proc]
        elif not any(str(i.get("process", "")).strip().lower() == proc
                     for i in wl):
            wl = wl + [{"process": proc, "max_level": level}]
        data["whitelist"] = wl
        try:
            shutil.copy2(self._path,
                         self._path.with_suffix(self._path.suffix + ".bak"))
        except OSError as e:
            raise PolicyError(f"策略备份失败，拒绝改写（fail-closed）: {e}") from e
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
        os.replace(tmp, self._path)

    def _event(self, name: str, detail: str) -> None:
        if self._audit is None:
            return
        try:
            self._audit.record_event(name, detail)
        except Exception:
            pass            # 审计尽力而为；操作本身的强审计在强制层两阶段
