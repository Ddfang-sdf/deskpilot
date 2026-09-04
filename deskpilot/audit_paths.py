"""审计受管目录（ISS-0010 §6，方案 A/B）。

resolve_audit_dir：相对 audit_dir 按形态锚定（冻结=exe 目录、源码=policy.yml 目录）。
AuditPaths：三类受管子目录（shots/client_shots/approval）单点产出、惰性创建。
"""

from __future__ import annotations

import sys
from pathlib import Path


def resolve_audit_dir(configured: str, policy_path: str | None = None) -> Path:
    """ISS-0010 §6：相对 audit_dir 锚定解析。

    绝对路径原样；相对路径：冻结形态锚 Path(sys.executable).parent，
    源码形态锚 Path(policy_path).parent（无 policy_path 回退 cwd）。
    """
    p = Path(configured)
    if p.is_absolute():
        return p
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / p
    if policy_path:
        return Path(policy_path).resolve().parent / p
    return Path.cwd() / p


class AuditPaths:
    """ISS-0010 §6：受管子目录单点产出（惰性 mkdir）。"""

    def __init__(self, audit_dir: str):
        self._root = Path(audit_dir)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def logs(self) -> Path:
        d = self._root / "logs"
        return d

    @property
    def shots(self) -> Path:
        d = self._root / "shots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def client_shots(self) -> Path:
        d = self._root / "shots" / "client"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def approval(self) -> Path:
        d = self._root / "approval"
        d.mkdir(parents=True, exist_ok=True)
        return d
