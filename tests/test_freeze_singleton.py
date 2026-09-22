"""冻结弹窗互斥与乐观关闭（ISS-0006 §6 接口）单元测试。

入口：freeze_dialog 公开函数 acquire_singleton / release_singleton /
reset_click_action、常量 SINGLETON_NAME。
断言值来源：被调函数返回值 / 子进程 stdout。

ISS-0093 §11 退役登记:TC-ISS6-03(TestWriteResetRequestNaming)随
write_reset_request/req 协议整体删除而退役。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from deskpilot.freeze_dialog import (SINGLETON_NAME, acquire_singleton,
                                     release_singleton, reset_click_action)

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
    """TC-ISS6-02 「立即解冻」点击决策（ISS-0093：token 随 req 废止更名）。

    ISS-0093 v0.6 适配登记(放宽双闸门·裁决 4 授权):token
    write_req_and_slide_out → reset_and_slide_out;不再探测「点击写 req」
    ——req 通道本身不复存在(§11 退役登记),SHOWN 门控语义不变。"""

    def test_shown_resets_and_slides_out(self):
        assert reset_click_action("SHOWN") == "reset_and_slide_out"

    def test_other_states_wait(self):
        assert reset_click_action("SNOOZED") == "wait"
        assert reset_click_action("SLIDE_IN") == "wait"
