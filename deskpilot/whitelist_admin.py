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


def verify_policy_sync(src: str, dst: str) -> bool:
    """ISS-0025 C：构建期同步一致性校验（纯函数,构建/CI 调用）。

    源缺失抛 PolicyError（fail-closed）;目标缺失/内容不同返回 False。
    供构建流程断言"repo 真源 == 产物策略"。
    """
    if not Path(src).is_file():
        raise PolicyError(f"策略真源缺失: {src}")
    if not Path(dst).is_file():
        return False
    return file_sha256(src) == file_sha256(dst)


class WhitelistAdmin:
    """ISS-0012 §6：运行期白名单状态（静态 ∪ 会话）与落盘。

    policy_path 为 None 时仅内存态（测试/兼容装配），永久变更与静态撤回
    报 PolicyError（fail-closed，不静默退化为内存）。
    """

    def __init__(self, policy_path: str | None, static: Mapping[str, str],
                 never_enroll: frozenset = NEVER_ENROLL, audit=None,
                 local_path: str | None = None,
                 base_whitelist: Mapping[str, str] | None = None):
        """ISS-0030：local_path 提供时为双文件模式——落盘只写
        policy.local.yml(出厂 base 永不写);撤回出厂条目以墓碑
        (max_level: null) 记录。local_path 缺省维持单文件旧语义
        (测试/兼容装配)。base_whitelist 为出厂白名单进程集(墓碑判定)。"""
        self._path = Path(policy_path) if policy_path else None
        self._local = Path(local_path) if local_path else None
        self._base = {str(k).strip().lower() for k in (base_whitelist or {})}
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
        """原子改盘：读全量 → 改 whitelist 节 → 先 .bak → 临时文件替换。

        ISS-0030 双文件模式(local_path 提供):只写 policy.local.yml;
        撤回出厂条目(proc∈base_whitelist)写墓碑 max_level: null,
        出厂 base 文件永不触碰。单文件旧语义不变。
        """
        if self._local is not None:
            target = self._local
            data = (yaml.safe_load(target.read_text(encoding="utf-8")) or {}
                    if target.is_file() else {})
            if not isinstance(data, dict):
                raise PolicyError("用户策略数据顶层非映射，拒绝改写")
            wl = [i for i in (data.get("whitelist") or [])
                  if str(i.get("process", "")).strip().lower() != proc]
            if remove and proc in self._base:
                wl = wl + [{"process": proc, "max_level": None}]   # 墓碑
            elif not remove:
                wl = wl + [{"process": proc, "max_level": level}]
            data["whitelist"] = wl
            self._atomic_write(target, data)
            return
        # 单文件旧语义(兼容装配/测试)
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
        self._atomic_write(self._path, data)

    def _atomic_write(self, target: Path, data: dict) -> None:
        """先 .bak 后临时文件 os.replace 原子替换(目标尚不存在则无备份可留)。"""
        if target.is_file():
            try:
                shutil.copy2(target,
                             target.with_suffix(target.suffix + ".bak"))
            except OSError as e:
                raise PolicyError(f"策略备份失败，拒绝改写（fail-closed）: {e}") from e
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
        os.replace(tmp, target)

    def _event(self, name: str, detail: str) -> None:
        if self._audit is None:
            return
        try:
            self._audit.record_event(name, detail)
        except Exception:
            pass            # 审计尽力而为；操作本身的强审计在强制层两阶段
