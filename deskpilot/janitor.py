"""审计数据与临时文件清理者（ISS-0010 §6 + ISS-0031 分档保留）。

plan_deletions：纯函数核心——超龄必删、超量按龄删、grace 在场保护。
run_janitor：对受管目录执行一轮（logs/ 仅年龄档 + shots/ 含 client 子目录
双阈值 + approval/ 超龄临时文件），写审计事件；单文件失败不中断。
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


def run_janitor(audit_dir: str, now: float, logs_max_age_s: float,
                shots_max_age_s: float, shots_max_bytes: int, grace_s: float,
                audit_log=None) -> dict:
    """执行一轮清理，返回统计并写审计事件。

    ISS-0031 分档：logs/ 仅按年龄(体积微小不设容量档,90 天内的日志
    绝不被截图挤兑);shots/(含 client 子目录)双阈值;approval/ 超龄
    临时文件并入截图档。审计根目录状态文件(estop-state 等)永不入清理面。
    单文件删除失败不中断。
    """
    ap = AuditPaths(audit_dir)
    # 日志档:仅年龄
    log_files = _collect(ap.logs)
    doomed_logs = [p for p, m, _ in log_files if m < now - logs_max_age_s]
    logs_deleted = 0
    logs_freed = 0
    for p in doomed_logs:
        try:
            logs_freed += p.stat().st_size
            p.unlink()
            logs_deleted += 1
        except OSError:
            continue
    # 截图档:双阈值(原 ISS-0010 语义)
    files = _collect(ap.shots) + _collect(ap.approval)
    doomed = plan_deletions(files, now, shots_max_age_s, shots_max_bytes,
                            grace_s)
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
    stats = {"deleted": deleted + logs_deleted, "freed_bytes": freed + logs_freed,
             "current_bytes": current,
             "logs_deleted": logs_deleted, "shots_deleted": deleted}
    if audit_log is not None:
        try:
            audit_log.record_event(
                "截图清理",
                f"删除 {deleted} 个文件,释放 {freed} 字节,当前占用 {current} 字节")
        except Exception:
            pass
        if logs_deleted:
            try:
                audit_log.record_event(
                    "审计日志清理",
                    f"删除 {logs_deleted} 个文件,释放 {logs_freed} 字节")
            except Exception:
                pass
    return stats
