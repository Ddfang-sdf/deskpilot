"""ISS-0018 路径与配置一致性测试（问题单 §4.1）。

层级：截图路径=单元(直出);真源一致=集成(数据层哈希直出);流水线=文件断言。
入口（设计）：executor.screenshot 返回 path / file_sha256 / release.yml。
"""

from __future__ import annotations

from pathlib import Path

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
    """TC-B:policy 单源化——同步后真源与运行副本哈希一致;流水线含同步步骤。
    断言:file_sha256 与 YAML 步骤(数据层直出)。"""

    def test_repo_and_dist_hash_equal(self):
        from deskpilot.whitelist_admin import file_sha256
        repo = ROOT / "policy.yml"
        dist = ROOT / "dist" / "policy.yml"
        assert file_sha256(str(repo)) == file_sha256(str(dist))

    def test_release_pipeline_has_policy_sync(self):
        wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml"
                             ).read_text(encoding="utf-8"))
        runs = "\n".join(s.get("run", "")
                         for s in wf["jobs"]["build"]["steps"])
        assert "policy.yml" in runs
