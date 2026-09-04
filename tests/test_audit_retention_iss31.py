"""ISS-0031 审计数据保留策略测试(TC-AU-01~07,问题单 §4 v0.1 评审通过)。

层级:单元(tmp 目录/合成 mtime;断言=文件存在性/统计/审计事件/字段,直出)。
入口(设计):janitor.run_janitor(新签名) / make_policy 默认 / load_policy。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from deskpilot.audit import AuditLogger
from deskpilot.janitor import run_janitor
from deskpilot.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400.0


def _touch(path: Path, age_s: float, size: int = 100):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    old = time.time() - age_s
    os.utime(path, (old, old))


def _audit_events(d: Path) -> str:
    logs_dir = d / "logs"
    if not logs_dir.is_dir():
        return ""
    return "".join(p.read_text(encoding="utf-8")
                   for p in sorted(logs_dir.glob("*.jsonl")))


class TestLogRetention:
    """TC-AU-01/02:日志仅按 90 天年龄清理(文件存在性+统计直出)。"""

    def test_au01_expired_log_deleted(self, tmp_path):
        d = tmp_path / "audit"
        _touch(d / "logs" / "audit-20260101.jsonl", 91 * DAY)
        _touch(d / "logs" / "audit-20260501.jsonl", 30 * DAY)
        _touch(d / "logs" / "audit-20260904.jsonl", 60)     # 当天
        stats = run_janitor(str(d), time.time(),
                            logs_max_age_s=90 * DAY,
                            shots_max_age_s=90 * DAY,
                            shots_max_bytes=10**9, grace_s=600)
        assert not (d / "logs" / "audit-20260101.jsonl").exists()
        assert (d / "logs" / "audit-20260501.jsonl").exists()
        assert (d / "logs" / "audit-20260904.jsonl").exists()
        assert stats["logs_deleted"] == 1                    # 直出

    def test_au02_in_age_logs_untouched(self, tmp_path):
        d = tmp_path / "audit"
        _touch(d / "logs" / "audit-20260701.jsonl", 60 * DAY)
        stats = run_janitor(str(d), time.time(),
                            logs_max_age_s=90 * DAY,
                            shots_max_age_s=90 * DAY,
                            shots_max_bytes=10**9, grace_s=600)
        assert stats["logs_deleted"] == 0
        assert (d / "logs" / "audit-20260701.jsonl").exists()


class TestSeparationAndImmunity:
    """TC-AU-03/04:分档互不挤兑;审计根目录状态文件豁免。"""

    def test_au03_tiers_independent(self, tmp_path):
        d = tmp_path / "audit"
        _touch(d / "logs" / "audit-old.jsonl", 100 * DAY)
        # shots 超量:grace 免疫 fresh 后,可删集 a+mid 共 10000 > 8000,
        # 按龄删最旧的 a;mid 保留
        _touch(d / "shots" / "a.png", 10 * DAY, size=5000)
        _touch(d / "shots" / "mid.png", 5 * DAY, size=5000)
        _touch(d / "shots" / "fresh.png", 30, size=5000)
        stats = run_janitor(str(d), time.time(),
                            logs_max_age_s=90 * DAY,
                            shots_max_age_s=90 * DAY,
                            shots_max_bytes=8000, grace_s=600)
        # 日志按龄删、截图按容量删(旧者先)、当日新鲜截图存活
        assert not (d / "logs" / "audit-old.jsonl").exists()
        assert not (d / "shots" / "a.png").exists()
        assert (d / "shots" / "mid.png").exists()
        assert (d / "shots" / "fresh.png").exists()
        assert stats["logs_deleted"] == 1
        assert stats["shots_deleted"] == 1
        assert stats["deleted"] == 2                          # 总数兼容(直出)

    def test_au04_root_state_files_immune(self, tmp_path):
        d = tmp_path / "audit"
        _touch(d / "estop-state.json", 100 * DAY)
        _touch(d / "logs" / "audit-old.jsonl", 100 * DAY)
        run_janitor(str(d), time.time(),
                    logs_max_age_s=90 * DAY,
                    shots_max_age_s=90 * DAY,
                    shots_max_bytes=10**9, grace_s=600)
        assert (d / "estop-state.json").exists()             # 永不入清理面(直出)
        assert not (d / "logs" / "audit-old.jsonl").exists()


class TestPolicyDefaults:
    """TC-AU-05/06:装配默认与生产策略加载(字段直出)。"""

    def test_au05_fixture_defaults(self, policy):
        assert policy.logs_max_age_days == 90.0
        assert policy.shots_max_age_days == 90.0
        assert policy.shots_max_bytes == 471859200            # 450MB(直出)

    def test_au06_repo_policy_loads_cleanup(self):
        p = load_policy(str(ROOT / "policy.yml"))
        assert p.logs_max_age_days == 90.0
        assert p.shots_max_age_days == 90.0
        assert p.shots_max_bytes == 471859200


class TestAuditEvent:
    """TC-AU-07:日志清理审计事件(持久化直出)。"""

    def test_au07_log_cleanup_event_recorded(self, tmp_path):
        d = tmp_path / "audit"
        _touch(d / "logs" / "audit-old.jsonl", 100 * DAY)
        audit_log = AuditLogger(str(d))
        run_janitor(str(d), time.time(),
                    logs_max_age_s=90 * DAY,
                    shots_max_age_s=90 * DAY,
                    shots_max_bytes=10**9, grace_s=600,
                    audit_log=audit_log)
        assert "审计日志清理" in _audit_events(d)
