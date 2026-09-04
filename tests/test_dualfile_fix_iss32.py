"""ISS-0032【修改引入】用户数据文件全链路修正测试(TC-DL-01~11,问题单 §3 v0.1)。

层级:单元(tmp 目录/静态源码断言;断言=文件内容/异常/审计事件/脚本源码形态,直出)。
入口(设计):policy.migrate_whitelist/_merge_local_whitelist/load_policy /
WhitelistAdmin 双文件 / main._run_migrate_policy。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from deskpilot.errors import PolicyError
from deskpilot.policy import load_policy, migrate_whitelist
from deskpilot.whitelist_admin import WhitelistAdmin

ROOT = Path(__file__).resolve().parents[1]

BASE = """whitelist:
  - { process: notepad.exe, max_level: L2 }
terminal_apps: [cmd.exe]
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestMigrateRespectsLocal:
    """TC-DL-01/02:迁移绝不覆写 local 已有条目(墓碑与显式)。"""

    def test_dl01_tombstone_survives_migration(self, tmp_path):
        old = _write(tmp_path / "old.yml",
                     BASE.replace("notepad.exe", "seeyou.exe"))
        new = _write(tmp_path / "new.yml", BASE)
        local = _write(tmp_path / "policy.local.yml",
                       "whitelist:\n  - { process: seeyou.exe, max_level: null }\n")
        migrated = migrate_whitelist(old, new, local)
        assert migrated == []                        # 已有条目不迁移(直出)
        data = yaml.safe_load(Path(local).read_text(encoding="utf-8"))
        assert {"process": "seeyou.exe", "max_level": None} in \
            data["whitelist"]                        # 墓碑原样(直出)
        p = load_policy(new, local_path=local)
        assert "seeyou.exe" not in p.whitelist       # 撤回仍生效(直出)

    def test_dl02_explicit_entry_not_overwritten(self, tmp_path):
        old = _write(tmp_path / "old.yml", BASE.replace("notepad.exe", "x.exe"))
        new = _write(tmp_path / "new.yml", BASE)
        local = _write(tmp_path / "policy.local.yml",
                       "whitelist:\n  - { process: x.exe, max_level: L1 }\n")
        assert migrate_whitelist(old, new, local) == []
        data = yaml.safe_load(Path(local).read_text(encoding="utf-8"))
        assert data["whitelist"] == [{"process": "x.exe", "max_level": "L1"}]


class TestMergeFailClosed:
    """TC-DL-04:缺 max_level 键显式报错;TC-DL-09:坏 base 先炸。"""

    def test_dl04_missing_max_level_key_rejected(self, tmp_path):
        base = _write(tmp_path / "policy.yml", BASE)
        local = _write(tmp_path / "policy.local.yml",
                       "whitelist:\n  - { process: x.exe }\n")
        with pytest.raises(PolicyError):
            load_policy(base, local_path=local)

    def test_dl09_broken_base_fails_before_merge(self, tmp_path):
        base = _write(tmp_path / "policy.yml",
                      "terminal_apps: [cmd.exe]\nkeys:\n  l2_allow: [enter]\n"
                      "  l3_controlled: [delete]\n")   # 缺 whitelist 节
        local = _write(tmp_path / "policy.local.yml",
                       "whitelist:\n  - { process: x.exe, max_level: L2 }\n")
        with pytest.raises(PolicyError) as ei:
            load_policy(base, local_path=local)
        assert "缺少必填节" in str(ei.value)


class TestTombstoneAlways:
    """TC-DL-05/06:撤回一律墓碑;双文件缺 base_whitelist 报错。"""

    def test_dl05_remove_local_added_leaves_tombstone(self, tmp_path):
        base = _write(tmp_path / "policy.yml", BASE)
        local = _write(tmp_path / "policy.local.yml", "whitelist: []\n")
        admin = WhitelistAdmin(base, {"notepad.exe": "L2"},
                               local_path=local,
                               base_whitelist={"notepad.exe"})
        admin.add_permanent("x.exe")
        assert admin.remove("x.exe") == "static"
        data = yaml.safe_load(Path(local).read_text(encoding="utf-8"))
        assert {"process": "x.exe", "max_level": None} in \
            data["whitelist"]                        # 墓碑永续(直出)
        p = load_policy(base, local_path=local)
        assert "x.exe" not in p.whitelist

    def test_dl06_dual_mode_requires_base(self, tmp_path):
        with pytest.raises(PolicyError):
            WhitelistAdmin(str(tmp_path / "policy.yml"), {},
                           local_path=str(tmp_path / "policy.local.yml"),
                           base_whitelist=None)


class TestMigrateRobustness:
    """TC-DL-07/08/10/11:坏输入收敛/原子写/审计锚定/级别 strip。"""

    def test_dl07_bad_input_converges_to_policy_error(self, tmp_path):
        old = _write(tmp_path / "old.yml", "- just\n- a list\n")
        new = _write(tmp_path / "new.yml", BASE)
        local = str(tmp_path / "policy.local.yml")
        with pytest.raises(PolicyError):
            migrate_whitelist(old, new, local)

    def test_dl08_migrate_atomic_backup(self, tmp_path):
        old = _write(tmp_path / "old.yml",
                     BASE.replace("notepad.exe", "seeyou.exe"))
        new = _write(tmp_path / "new.yml", BASE)
        local = _write(tmp_path / "policy.local.yml", "whitelist: []\n")
        migrate_whitelist(old, new, local)
        assert (tmp_path / "policy.local.yml.bak").exists()   # 原子写留档(直出)

    def test_dl10_audit_anchored_to_new_policy(self, tmp_path, monkeypatch):
        new = _write(tmp_path / "new" / "policy.yml", BASE)   # audit_dir ./audit
        old = _write(tmp_path / "new" / "old.yml",
                     BASE.replace("notepad.exe", "seeyou.exe"))
        local = str(tmp_path / "new" / "policy.local.yml")
        (tmp_path / "elsewhere").mkdir()
        monkeypatch.chdir(tmp_path / "elsewhere")             # 干扰 CWD
        from deskpilot.main import _run_migrate_policy
        rc = _run_migrate_policy([old, new, local])
        assert rc == 0
        logs = (tmp_path / "new" / "audit" / "logs").glob("*.jsonl")
        content = "".join(p.read_text(encoding="utf-8") for p in logs)
        assert "入白迁移" in content                    # 落新策略旁(直出)
        assert not (tmp_path / "elsewhere" / "audit").exists()  # 不流浪(直出)

    def test_dl11_level_stripped(self, tmp_path):
        old = _write(tmp_path / "old.yml",
                     BASE.replace("- { process: notepad.exe, max_level: L2 }",
                                  '- { process: x.exe, max_level: "L2 " }'))
        new = _write(tmp_path / "new.yml", BASE)
        local = str(tmp_path / "policy.local.yml")
        assert migrate_whitelist(old, new, local) == ["x.exe"]
        data = yaml.safe_load(Path(local).read_text(encoding="utf-8"))
        assert data["whitelist"] == [{"process": "x.exe", "max_level": "L2"}]
        load_policy(new, local_path=local)             # 重载不炸(直出)


class TestInstallerExitCodeGuard:
    """TC-DL-03:install.ps1 原生命令后必查退出码(静态形态)。"""

    def test_dl03_native_calls_check_exit_code(self):
        src = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        idx_call = src.index("& $exe.FullName --migrate-policy")
        idx_check = src.index("$LASTEXITCODE", idx_call)
        assert idx_check > idx_call
        assert "LASTEXITCODE" in src
