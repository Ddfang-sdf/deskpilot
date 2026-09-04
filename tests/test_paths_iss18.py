"""ISS-0018 路径与配置一致性测试(问题单 §4.1;ISS-0025 C 改写)。

层级:截图路径=单元(直出);同步校验=单元(verify_policy_sync 临时目录直出);
流水线=文件断言。
入口(设计):executor.screenshot 返回 path / whitelist_admin.verify_policy_sync
/ release.yml 同步步骤。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class TestScreenshotAbsolutePath:
    """TC-A:screenshot 返回绝对路径,客户端零猜测。
    断言:path 绝对性与文件存在性(直出)。"""

    def test_screenshot_path_absolute(self, estop, tmp_path, clock, probe):
        from deskpilot.executor import Executor
        from .conftest import FIXTURE_HWND
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      clock=clock, probe=probe)
        r = ex.screenshot("window", window=FIXTURE_HWND)
        p = Path(r["path"])
        assert p.is_absolute()
        assert p.exists()


class TestPolicySingleSource:
    """TC-B(ISS-0025 C 改写):构建期同步校验纯函数,不读生产目录。
    守卫由构建/CI 在同步后调用;断言:verify_policy_sync 返回值(直出)。"""

    def test_sync_verify_same_and_diff(self, tmp_path):
        from deskpilot.whitelist_admin import verify_policy_sync
        src = tmp_path / "s.yml"
        dst = tmp_path / "d.yml"
        src.write_text("whitelist: []\n", encoding="utf-8")
        dst.write_text("whitelist: []\n", encoding="utf-8")
        assert verify_policy_sync(str(src), str(dst)) is True
        dst.write_text("whitelist:\n  - { process: x.exe }\n",
                       encoding="utf-8")
        assert verify_policy_sync(str(src), str(dst)) is False

    def test_sync_verify_missing_source_fails_closed(self, tmp_path):
        from deskpilot.errors import PolicyError
        from deskpilot.whitelist_admin import verify_policy_sync
        with pytest.raises(PolicyError):
            verify_policy_sync(str(tmp_path / "no.yml"),
                               str(tmp_path / "d.yml"))

    def test_release_pipeline_has_policy_sync(self):
        wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml"
                             ).read_text(encoding="utf-8"))
        runs = "\n".join(s.get("run", "")
                         for s in wf["jobs"]["build"]["steps"])
        assert "policy.yml" in runs
        assert "--run-integration" in runs          # ISS-0025:CI 显式开集成
        assert "pytest-randomly" in runs            # ISS-0025:CI 随机序
