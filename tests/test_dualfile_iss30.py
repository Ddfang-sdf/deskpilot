"""ISS-0030 出厂策略与用户数据分离测试(TC-SP-01~07,问题单 §4/§5 v0.2)。

层级:单元(临时目录装配;数据层断言=文件内容/sha256/审计 JSONL)。
入口(设计):policy.load_policy(base, local) / WhitelistAdmin 双文件写盘 /
policy.migrate_whitelist / main.local_policy_sha256_audit。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from deskpilot.errors import PolicyError
from deskpilot.policy import load_policy, migrate_whitelist
from deskpilot.whitelist_admin import WhitelistAdmin, file_sha256

BASE = """whitelist:
  - { process: notepad.exe, max_level: L2 }
terminal_apps:
  - cmd.exe
keys:
  l2_allow: [enter]
  l3_controlled: [delete]
timeouts:
  binding_ttl: 600
  approval_ttl: 60
  wait_poll_interval: 0.5
  wait_timeout_max: 300
audit_dir: ./audit
"""


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestDualLoad:
    """TC-SP-01~03:双文件加载合并与 fail-closed(直出)。"""

    def test_sp01_local_add_merged(self, tmp_path):
        base = _write(tmp_path / "policy.yml", BASE)
        local = _write(tmp_path / "policy.local.yml",
                       "whitelist:\n  - { process: x.exe, max_level: L2 }\n")
        p = load_policy(base, local_path=local)
        assert "x.exe" in p.whitelist
        assert "notepad.exe" in p.whitelist          # 出厂条目保留(直出)

    def test_sp02_local_tombstone_overrides_base(self, tmp_path):
        base = _write(tmp_path / "policy.yml", BASE)
        local = _write(tmp_path / "policy.local.yml",
                       "whitelist:\n  - { process: notepad.exe, max_level: null }\n")
        p = load_policy(base, local_path=local)
        assert "notepad.exe" not in p.whitelist      # 墓碑撤回出厂(直出)

    def test_sp03_local_security_section_rejected(self, tmp_path):
        base = _write(tmp_path / "policy.yml", BASE)
        local = _write(tmp_path / "policy.local.yml",
                       "keys:\n  l2_allow: [enter]\n")
        with pytest.raises(PolicyError):             # 安全参数不可本地放宽
            load_policy(base, local_path=local)


class TestDualWrite:
    """TC-SP-04/05:入白只写 local,升级覆盖 base 数据完好(数据层直出)。"""

    def test_sp04_enroll_writes_local_only(self, tmp_path):
        base = _write(tmp_path / "policy.yml", BASE)
        local = _write(tmp_path / "policy.local.yml", "whitelist: []\n")
        before = file_sha256(base)
        admin = WhitelistAdmin(base, {"notepad.exe": "L2"},
                               local_path=local,
                               base_whitelist={"notepad.exe"})
        admin.add_permanent("x.exe")
        assert file_sha256(base) == before           # base 永不写(直出)
        data = yaml.safe_load(Path(local).read_text(encoding="utf-8"))
        assert {"process": "x.exe", "max_level": "L2"} in data["whitelist"]

    def test_sp05_upgrade_keeps_user_data(self, tmp_path):
        base = _write(tmp_path / "policy.yml", BASE)
        local = _write(tmp_path / "policy.local.yml", "whitelist: []\n")
        admin = WhitelistAdmin(base, {"notepad.exe": "L2"},
                               local_path=local,
                               base_whitelist={"notepad.exe"})
        admin.add_permanent("x.exe")
        # 模拟安装器整文件覆盖 base(出厂升级)
        _write(tmp_path / "policy.yml", BASE.replace("notepad.exe", "mspaint.exe"))
        p = load_policy(base, local_path=local)
        assert "x.exe" in p.whitelist                # 用户数据完好(直出)
        assert "mspaint.exe" in p.whitelist           # 新出厂条目生效(直出)
        assert "notepad.exe" not in p.whitelist


class FakeAudit:
    def __init__(self):
        self.events: list[tuple] = []

    def record_event(self, name, detail):
        self.events.append((name, detail))


class TestMigrationAndFingerprint:
    """TC-SP-06/07:一次性迁移与双指纹事件(直出)。"""

    def test_sp06_migrate_surplus_entries(self, tmp_path):
        old = _write(tmp_path / "old.yml",
                     BASE.replace("notepad.exe", "seeyou.exe"))
        new = _write(tmp_path / "new.yml", BASE)
        local = str(tmp_path / "policy.local.yml")
        audit = FakeAudit()
        migrated = migrate_whitelist(old, new, local, audit=audit)
        assert migrated == ["seeyou.exe"]            # 差额迁入(直出)
        data = yaml.safe_load(Path(local).read_text(encoding="utf-8"))
        assert {"process": "seeyou.exe", "max_level": "L2"} in \
            data["whitelist"]
        assert ("入白迁移", "seeyou.exe") in audit.events

    def test_sp06b_no_difference_no_touch(self, tmp_path):
        old = _write(tmp_path / "old.yml", BASE)
        new = _write(tmp_path / "new.yml", BASE)
        local = str(tmp_path / "policy.local.yml")
        audit = FakeAudit()
        assert migrate_whitelist(old, new, local, audit=audit) == []
        assert not Path(local).exists()              # 零差异零落盘(直出)
        assert audit.events == []

    def test_sp07_local_fingerprint_event(self, tmp_path):
        from deskpilot.audit import AuditLogger
        from deskpilot.main import local_policy_sha256_audit
        local = _write(tmp_path / "policy.local.yml", "whitelist: []\n")
        audit = AuditLogger(str(tmp_path / "audit"))
        local_policy_sha256_audit(local, audit)
        events = [r["event"] for r in _read_audit(tmp_path / "audit")]
        assert "用户策略数据指纹" in events          # 双轨事件(持久化直出)


def _read_audit(audit_dir: Path) -> list[dict]:
    log_dir = audit_dir / "logs"
    if not log_dir.is_dir():
        return []
    records: list[dict] = []
    for f in sorted(log_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records
