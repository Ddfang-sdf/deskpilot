"""冻结弹窗互斥与乐观关闭（ISS-0006 §6 接口）单元测试。

入口：freeze_dialog 公开函数 acquire_singleton / release_singleton /
reset_click_action / write_reset_request、常量 SINGLETON_NAME。
断言值来源：被调函数返回值 / 子进程 stdout / req 文件持久化内容。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from deskpilot.freeze_dialog import (SINGLETON_NAME, acquire_singleton,
                                     release_singleton, reset_click_action,
                                     write_reset_request)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _child_acquire() -> str:
    """子进程尝试抢单例，回显其 acquire_singleton 返回值。"""
    code = ("from deskpilot.freeze_dialog import acquire_singleton;"
            "print('ACQ=' + str(acquire_singleton()))")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT),
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


class TestSingletonMutex:
    """TC-ISS6-01 命名互斥体单例（方案 A）。"""

    def test_first_acquire_true_and_release_reacquire(self):
        assert acquire_singleton() is True
        release_singleton()
        assert acquire_singleton() is True
        release_singleton()

    def test_second_process_cannot_acquire(self):
        assert acquire_singleton() is True
        try:
            assert _child_acquire() == "ACQ=False"
        finally:
            release_singleton()

    def test_acquire_after_release_by_other(self):
        assert acquire_singleton() is True
        release_singleton()
        assert _child_acquire() == "ACQ=True"

    def test_singleton_name_value(self):
        assert SINGLETON_NAME == r"Local\DeskPilotFreezeDialog"


class TestResetClickAction:
    """TC-ISS6-02 乐观关闭决策（方案 F）。"""

    def test_shown_writes_and_slides_out(self):
        assert reset_click_action("SHOWN") == "write_req_and_slide_out"

    def test_other_states_wait(self):
        assert reset_click_action("SNOOZED") == "wait"
        assert reset_click_action("SLIDE_IN") == "wait"


class TestWriteResetRequestNaming:
    """TC-ISS6-03 解冻请求文件按 seq 命名（方案 B）。"""

    def test_req_file_named_with_seq(self, tmp_path):
        write_reset_request(str(tmp_path), 7)
        req = tmp_path / "estop-reset-7.req"
        assert req.exists()
        assert json.loads(req.read_text(encoding="utf-8")) == {"seq": 7}
