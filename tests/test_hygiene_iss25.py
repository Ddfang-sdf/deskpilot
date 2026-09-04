"""ISS-0025 测试卫生(TC-HY-01~06,问题单 §4/§5 v0.2 评审通过)。

层级:TC-HY-03/04 单元(verify_policy_sync 纯函数);
TC-HY-05 形态静态断言;
TC-HY-01/02/06 子进程外表面(真 pytest 子进程:退出码/输出/进程计数)。
meta 类整体 integration 标记——子进程用例自身会开真窗口,不得混入
默认零副作用套件;CI --run-integration 全量覆盖。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TESTS_DIR = ROOT / "tests"


def _run_pytest(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)


def _notepad_count() -> int:
    import ctypes
    import re
    import subprocess as sp
    out = sp.run(["powershell", "-NoProfile", "-Command",
                  "(Get-Process notepad -ErrorAction SilentlyContinue).Count"],
                 capture_output=True, text=True, timeout=30)
    m = re.search(r"\d+", out.stdout or "")
    return int(m.group()) if m else 0


@pytest.mark.integration
class TestDefaultZeroSideEffect:
    """TC-HY-01/02:默认跳过真机,显式开关启用(子进程外表面)。"""

    def test_hy01_default_run_skips_integration(self):
        """TC-HY-01:无开关跑 notepad 集成所在文件——跳过+零进程副作用。"""
        before = _notepad_count()
        proc = _run_pytest([str(TESTS_DIR / "test_uia_com_iss16.py")])
        after = _notepad_count()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "skipped" in proc.stdout                # 集成被默认跳过(直出)
        assert before == after                         # 零副作用(系统外表面)

    def test_hy02_flag_enables_integration(self):
        """TC-HY-02:--run-integration 显式启用单条真机用例(开-关自净)。"""
        before = _notepad_count()
        proc = _run_pytest([
            str(TESTS_DIR / "test_uia_com_iss16.py") +
            "::TestUiaThroughDaemon::test_get_ui_tree_real_notepad",
            "--run-integration"])
        after = _notepad_count()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "1 passed" in proc.stdout               # 真机执行(直出)
        assert before == after                         # 自净(系统外表面)


@pytest.mark.integration
class TestSingleRunIndependent:
    """TC-HY-06:顺序依赖用例单跑绿(退出码直出)。"""

    def test_hy06_tk_test_runs_alone(self):
        proc = _run_pytest([
            str(TESTS_DIR / "test_whitelist_iss12.py") +
            "::TestEnrollDialog::test_image_reference_kept_on_window"])
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "1 passed" in proc.stdout


class TestPolicySyncGuard:
    """TC-HY-03/04:构建期同步校验纯函数(临时目录直出)。"""

    def test_hy03_same_content_true(self, tmp_path):
        from deskpilot.whitelist_admin import verify_policy_sync
        src = tmp_path / "s.yml"
        dst = tmp_path / "d.yml"
        src.write_text("whitelist: []\n", encoding="utf-8")
        dst.write_text("whitelist: []\n", encoding="utf-8")
        assert verify_policy_sync(str(src), str(dst)) is True

    def test_hy04_different_content_false(self, tmp_path):
        from deskpilot.whitelist_admin import verify_policy_sync
        src = tmp_path / "s.yml"
        dst = tmp_path / "d.yml"
        src.write_text("whitelist: []\n", encoding="utf-8")
        dst.write_text("whitelist:\n  - { process: x.exe }\n",
                       encoding="utf-8")
        assert verify_policy_sync(str(src), str(dst)) is False


class TestNoProductionPathInOldGuard:
    """TC-HY-05:旧哈希用例源码不得再引用 dist(形态静态断言)。"""

    def test_hy05_no_dist_reference(self):
        text = (TESTS_DIR / "test_paths_iss18.py").read_text(
            encoding="utf-8")
        assert "dist" not in text
