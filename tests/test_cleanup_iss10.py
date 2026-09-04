"""ISS-0010 截图治理单元测试（问题单 §6 接口定义）。

层级：单元测试（允许打桩；断言在纯函数返回值/持久化文件与目录结构/
替身调用记录，均直出）。
五要素：各类 docstring 标注。
入口（§6）：plan_deletions / run_janitor / resolve_audit_dir / AuditPaths /
Policy 四个清理策略字段 / TkApprovalChannel 临时文件归队。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from deskpilot.audit_paths import AuditPaths, resolve_audit_dir
from deskpilot.janitor import plan_deletions, run_janitor
from deskpilot.policy import load_policy


def _mk(files):
    """构造 (path, mtime, bytes) 三元组。"""
    return [(Path(p), m, b) for p, m, b in files]


# ---------- C Janitor 计划（时空双阈值 + 在场保护） ----------

class TestPlanDeletions:
    """场景:超龄必删、超量按龄删、grace 期内绝对免疫。
    断言:plan_deletions 返回的删除集(直出)。"""

    NOW = 1_000_000.0

    def test_age_expired_always_deleted(self):
        files = _mk([("a.png", self.NOW - 15 * 86400, 10),
                     ("b.png", self.NOW - 13 * 86400, 10)])
        out = plan_deletions(files, self.NOW, max_age_s=14 * 86400,
                             max_bytes=10**9, grace_s=0)
        assert out == [Path("a.png")]

    def test_over_bytes_deleted_oldest_first(self):
        files = _mk([("old.png", 1.0, 2 * 10**9),
                     ("mid.png", 2.0, 10**9),
                     ("new.png", self.NOW, 10**9)])
        out = plan_deletions(files, self.NOW, max_age_s=10**9,
                             max_bytes=2 * 10**9, grace_s=0)
        # 共 4GB 上限 2GB:删掉最旧的 old(2GB)即达标,其余保留
        assert out == [Path("old.png")]

    def test_grace_window_immune(self):
        files = _mk([("fresh.png", self.NOW - 300, 10)])
        out = plan_deletions(files, self.NOW, max_age_s=1,
                             max_bytes=0, grace_s=600)
        assert out == []

    def test_grace_immune_even_when_over_bytes(self):
        files = _mk([("f1.png", self.NOW - 100, 10**9),
                     ("f2.png", self.NOW - 200, 10**9),
                     ("f3.png", self.NOW - 300, 10**9)])
        out = plan_deletions(files, self.NOW, max_age_s=10**9,
                             max_bytes=1, grace_s=600)
        assert out == []


# ---------- C Janitor 执行（落盘删除 + 审计事件） ----------

class TestRunJanitor:
    """场景:对受管目录执行一轮清理,删除命中文件并写审计事件;在场文件保留。
    前提:tmp 目录构造 shots/ 与 approval/ 文件。
    断言:返回统计 dict、磁盘文件存在性、审计 JSONL 事件(持久化直出)。"""

    def _touch(self, path: Path, age_s: float, size: int = 100):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        old = time.time() - age_s
        os.utime(path, (old, old))

    def test_run_deletes_expired_and_keeps_fresh(self, tmp_path):
        d = tmp_path / "audit"
        self._touch(d / "shots" / "20260101" / "old.png", 15 * 86400)
        self._touch(d / "shots" / "client" / "old2.png", 15 * 86400)
        self._touch(d / "approval" / "x.desc", 15 * 86400)
        self._touch(d / "shots" / "20260101" / "new.png", 60)
        from deskpilot.audit import AuditLogger
        audit_log = AuditLogger(str(d))
        # ISS-0031 签名重指:logs 年龄档/截图双阈值分档
        stats = run_janitor(str(d), time.time(), logs_max_age_s=90 * 86400,
                            shots_max_age_s=14 * 86400,
                            shots_max_bytes=10**9, grace_s=600,
                            audit_log=audit_log)
        assert stats["deleted"] == 3
        assert not (d / "shots" / "20260101" / "old.png").exists()
        assert not (d / "shots" / "client" / "old2.png").exists()
        assert not (d / "approval" / "x.desc").exists()
        assert (d / "shots" / "20260101" / "new.png").exists()
        records = (d / "logs").glob("*.jsonl")
        content = "".join(p.read_text(encoding="utf-8")
                          for p in records)
        assert "清理" in content and "3" in content


# ---------- A 锚定解析 ----------

class TestResolveAuditDir:
    """场景:相对 audit_dir 按形态锚定;绝对路径原样。
    断言:resolve_audit_dir 返回路径(直出)。"""

    def test_absolute_passthrough(self):
        assert resolve_audit_dir("C:/abs/audit") == Path("C:/abs/audit")

    def test_relative_anchors_policy_dir(self, tmp_path, monkeypatch):
        monkeypatch.delattr("sys.frozen", raising=False)
        out = resolve_audit_dir("./audit", str(tmp_path / "policy.yml"))
        assert out == tmp_path / "audit"

    def test_relative_anchors_exe_when_frozen(self, tmp_path, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "x.exe"))
        out = resolve_audit_dir("./audit", None)
        assert out == tmp_path / "bin" / "audit"


# ---------- B AuditPaths 归队 ----------

class TestAuditPaths:
    """场景:三类受管子目录都在受管目录内且彼此隔离、惰性创建。
    断言:各属性 Path 值与磁盘目录存在性(直出)。"""

    def test_subdirs_under_root_and_created(self, tmp_path):
        ap = AuditPaths(str(tmp_path / "audit"))
        for sub in (ap.shots, ap.client_shots, ap.approval):
            assert str(sub).startswith(str(tmp_path / "audit"))
            assert sub.is_dir()
        assert ap.shots != ap.client_shots != ap.approval


# ---------- D 策略字段 ----------

class TestCleanupPolicyFields:
    """场景:policy.yml 缺失 cleanup 配置时按默认;显式配置时按值加载。
    断言:load_policy 后四个字段值(直出)。"""

    def _write(self, tmp_path, cleanup_yaml: str = ""):
        base = (tmp_path / "policy.yml")
        base.write_text(f"""
whitelist:
  - {{ process: notepad.exe, max_level: L2 }}
terminal_apps: [cmd.exe]
keys:
  l2_allow: [enter]
  l3_controlled: [delete]
  input_scenario_keys: [backspace]
  input_control_types: [Edit]
timeouts:
  binding_ttl: 600
  approval_ttl: 60
  wait_poll_interval: 0.5
  wait_timeout_max: 300
limits:
  input_max_chars: 65536
estop:
  l0_during_freeze: true
  corner_hold_ms: 200
audit_dir: ./audit
{cleanup_yaml}""", encoding="utf-8")
        return base

    def test_defaults_when_absent(self, tmp_path):
        p = load_policy(str(self._write(tmp_path)))
        # ISS-0031:默认值按 sdfang 裁定校准(日志 90 天/截图 90 天+450MB)
        assert p.logs_max_age_days == 90.0
        assert p.shots_max_age_days == 90.0
        assert p.shots_max_bytes == 471859200
        assert p.cleanup_grace_seconds == 600.0
        assert p.cleanup_interval_seconds == 3600.0

    def test_explicit_values(self, tmp_path):
        p = load_policy(str(self._write(tmp_path, """
cleanup:
  shots_max_age_days: 7
  shots_max_bytes: 1000000
  cleanup_grace_seconds: 120
  cleanup_interval_seconds: 60
""")))
        assert p.shots_max_age_days == 7.0
        assert p.shots_max_bytes == 1000000
        assert p.cleanup_grace_seconds == 120.0
        assert p.cleanup_interval_seconds == 60.0


# ---------- B 审批临时文件归队 ----------

class TestApprovalFilesManaged:
    """场景:审批通道提供 AuditPaths 时,desc/result 落 approval/ 子目录。
    断言:channel 发出的 desc/result 路径前缀(替身记录直出)。"""

    def test_temp_files_landed_in_approval_dir(self, tmp_path):
        from deskpilot.approval_ui import TkApprovalChannel
        ap = AuditPaths(str(tmp_path / "audit"))
        ch = TkApprovalChannel(popen_factory=lambda *a, **k: None,
                               audit_paths=ap)
        ch.request("危险操作", "fp-x")
        rp = ch.last_request["result_path"]
        assert str(rp).startswith(str(ap.approval))
