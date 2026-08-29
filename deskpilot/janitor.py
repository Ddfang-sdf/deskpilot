"""截图与临时文件清理者（ISS-0010 §6，方案 C）。

plan_deletions：纯函数核心——超龄必删、超量按龄删、grace 在场保护。
run_janitor：对受管目录执行一轮（shots/ 含 client 子目录 + approval/ 超龄
临时文件），写审计事件；单文件失败不中断；审计 JSONL 不在清理范围。
"""

from __future__ import annotations

import time
from pathlib import Path

from .audit_paths import AuditPaths


def plan_deletions(files: list[tuple[Path, float, int]], now: float,
                   max_age_s: float, max_bytes: int,
                   grace_s: float) -> list[Path]:
    """ISS-0010 §6：删除计划（时空双阈值 + 在场保护）。

    入参 files 为 (路径, mtime, 字节) 三元组：
    ① mtime < now - max_age_s 必删；
    ② 再按 mtime 从旧到新累计体积，超 max_bytes 部分按龄删；
    ③ mtime ≥ now - grace_s 的文件永不出现在删除集（在场保护）。
    """
    candidates = [(p, m, b) for p, m, b in files
                  if m < now - grace_s]               # ③ 在场保护先行
    out: list[Path] = []
    rest: list[tuple[Path, float, int]] = []
    for p, m, b in candidates:
        if m < now - max_age_s:                     # ① 超龄必删
            out.append(p)
        else:
            rest.append((p, m, b))
    rest.sort(key=lambda t: t[1])                   # ② 按龄从旧到新
    total = sum(b for _, _, b in rest)
    for p, m, b in rest:
        if total <= max_bytes:
            break
        out.append(p)
        total -= b
    return out


def _collect(root: Path) -> list[tuple[Path, float, int]]:
    files: list[tuple[Path, float, int]] = []
    if not root.is_dir():
        return files
    for p in root.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((p, st.st_mtime, st.st_size))
    return files


def run_janitor(audit_dir: str, now: float, max_age_s: float,
                max_bytes: int, grace_s: float,
                audit_log=None) -> dict:
    """ISS-0010 §6：执行一轮清理，返回统计并写审计事件。

    清理范围：shots/（含 client 子目录）与 approval/ 超龄临时文件；
    审计 JSONL 日志不在清理范围。单文件删除失败不中断。
    """
    ap = AuditPaths(audit_dir)
    files = _collect(ap.shots) + _collect(ap.approval)
    doomed = plan_deletions(files, now, max_age_s, max_bytes, grace_s)
    deleted = 0
    freed = 0
    sizes = {p: b for p, _, b in files}
    for p in doomed:
        try:
            freed += sizes.get(p, 0)
            p.unlink()
            deleted += 1
        except OSError:
            continue                                  # 单文件失败不中断
    current = sum(b for _, _, b in _collect(ap.shots))
    stats = {"deleted": deleted, "freed_bytes": freed,
             "current_bytes": current}
    if audit_log is not None:
        try:
            audit_log.record_event(
                "截图清理",
                f"删除 {deleted} 个文件,释放 {freed} 字节,当前占用 {current} 字节")
        except Exception:
            pass
    return stats
