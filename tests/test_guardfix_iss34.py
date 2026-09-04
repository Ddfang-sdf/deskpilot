"""ISS-0034【修改引入】守护机制修正测试(TC-GD-01~05,问题单 §3 v0.1)。

层级:单元(守望 check_once/refresh/回调,替身与临时文件直出)+源码形态静态断言。
入口(设计):_PolicyWatchThread.check_once/refresh / WhitelistAdmin(on_written)。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _audit_events(d: Path) -> str:
    logs_dir = d / "logs"
    if not logs_dir.is_dir():
        return ""
    return "".join(p.read_text(encoding="utf-8")
                   for p in sorted(logs_dir.glob("*.jsonl")))


class TestWatcherInternalWrite:
    """TC-GD-01/02:内部写入刷新后零假警;真外部改动仍报警(事件直出)。"""

    def _make_watch(self, tmp_path, audit, event_name="用户策略数据被外部修改"):
        from deskpilot.main import _PolicyWatchThread
        target = tmp_path / "policy.local.yml"
        target.write_text("whitelist: []\n", encoding="utf-8")
        from deskpilot.whitelist_admin import file_sha256
        t = _PolicyWatchThread(str(target), audit, 60.0,
                               file_sha256(str(target)),
                               event_name=event_name)
        return t, target

    def test_gd01_internal_write_refresh_no_false_alarm(self, tmp_path):
        from deskpilot.audit import AuditLogger
        from deskpilot.whitelist_admin import file_sha256
        audit = AuditLogger(str(tmp_path / "audit"))
        t, target = self._make_watch(tmp_path, audit)
        # 模拟内部写入:文件改后同步 refresh(与 on_written 回调同路径)
        target.write_text("whitelist:\n  - { process: x.exe, max_level: L2 }\n",
                          encoding="utf-8")
        t.refresh(file_sha256(str(target)))
        t.check_once()
        assert "外部修改" not in _audit_events(tmp_path / "audit")

    def test_gd02_real_external_change_alarms(self, tmp_path):
        from deskpilot.audit import AuditLogger
        audit = AuditLogger(str(tmp_path / "audit"))
        t, target = self._make_watch(tmp_path, audit)
        target.write_text("whitelist:\n  - { process: evil.exe, max_level: L2 }\n",
                          encoding="utf-8")
        t.check_once()
        assert "用户策略数据被外部修改" in _audit_events(tmp_path / "audit")


class TestOnWrittenCallback:
    """TC-GD-03:双文件落盘后触发回调,参数为新指纹(替身记录直出)。"""

    def test_gd03_callback_fires_with_new_fingerprint(self, tmp_path):
        from deskpilot.whitelist_admin import WhitelistAdmin, file_sha256
        base = tmp_path / "policy.yml"
        base.write_text("whitelist:\n  - { process: notepad.exe, max_level: L2 }\n",
                        encoding="utf-8")
        local = tmp_path / "policy.local.yml"
        local.write_text("whitelist: []\n", encoding="utf-8")
        calls = []
        admin = WhitelistAdmin(str(base), {"notepad.exe": "L2"},
                               local_path=str(local),
                               base_whitelist={"notepad.exe"},
                               on_written=lambda fp: calls.append(fp))
        admin.add_permanent("x.exe")
        assert len(calls) == 1
        assert calls[0] == file_sha256(str(local))       # 参数=新指纹(直出)


class TestCIGuardWiring:
    """TC-GD-04/05:CI 真实接线与陈旧产物清理(静态形态直出)。"""

    def test_gd04_release_yml_wired(self):
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8")
        assert "verify_policy_sync" in wf

    def test_gd05_stale_release_policy_gone(self):
        assert not (ROOT / "release" / "policy.yml").exists()
