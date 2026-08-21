"""测试基建：固件窗口替身、假探测、假审批通道、假执行层、测试时钟。

所有替身均实现设计文档定义的公开接口（WindowProbe / ApprovalChannel / Executor），
测试断言只基于被调方法的返回值或持久化数据（审计 JSONL）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from deskpilot import models
from deskpilot.approval import ApprovalManager
from deskpilot.audit import AuditLogger
from deskpilot.binding import BindingManager
from deskpilot.enforcement import Enforcement
from deskpilot.errors import ExecutorError
from deskpilot.estop import EstopMonitor
from deskpilot.policy import load_policy
from deskpilot.tools import ToolContext

FIXTURE_HWND = 1001
FIXTURE_RECT = (100, 100, 800, 600)
FIXTURE_HWND_B = 1002
FIXTURE_RECT_B = (100, 100, 900, 700)


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeProbe:
    """窗口探测替身（实现 binding.WindowProbe 公开接口）。"""

    def __init__(self):
        self.alive = {FIXTURE_HWND: True, FIXTURE_HWND_B: True}
        self.processes = {FIXTURE_HWND: "notepad.exe", FIXTURE_HWND_B: "notepad.exe"}
        self.rects = {FIXTURE_HWND: FIXTURE_RECT, FIXTURE_HWND_B: FIXTURE_RECT_B}
        self.foreground = FIXTURE_HWND          # 默认绑定窗口已在前台
        self.activate_result = True

    def hwnd_alive(self, hwnd: int) -> bool:
        return self.alive.get(hwnd, False)

    def process_of(self, hwnd: int) -> str:
        return self.processes.get(hwnd, "")

    def rect_of(self, hwnd: int):
        return self.rects.get(hwnd, (0, 0, 0, 0))

    def is_foreground(self, hwnd: int) -> bool:
        return hwnd == self.foreground

    def activate(self, hwnd: int) -> bool:
        if not self.activate_result:
            return False
        self.foreground = hwnd
        return True


class FakeApprover:
    """模拟审批通道（实现 approval.ApprovalChannel 公开接口，同步裁决语义）。

    decision 为 "approve" / "deny" / "timeout"；也可赋可调用对象——
    在裁决返回前执行副作用（关窗/触发急停），模拟"延迟批准"场景（ISS-0003）。
    """

    def __init__(self):
        self.decision: Any = "deny"      # 同步裁决结果或可调用对象
        self.requests: list[dict] = []  # 送达通道的审批请求

    def request(self, description: str, fingerprint: str,
                image_path: str | None = None) -> str:
        self.requests.append({"description": description,
                              "fingerprint": fingerprint,
                              "image_path": image_path})
        d = self.decision
        return d() if callable(d) else d


class FakeExecutor:
    """假执行层（实现 executor.Executor 公开入口；记录收到的指令）。"""

    def __init__(self):
        self.instructions: list[dict] = []
        self.focus_type: str | None = "Edit"
        self.error: ExecutorError | None = None
        self.result = {"status": "ok", "before_shot": "shots/b.png",
                       "after_shot": "shots/a.png"}
        self.live_windows: list[dict] = []          # find_windows 数据源
        self.approval_shot_path = "shots/approval_fake.png"
        self.approval_shot_rects: list[tuple] = []   # 审批截图收到的窗口矩形
        self.approval_shot_error = False

    def execute(self, instruction: dict) -> dict:
        if self.error is not None:
            raise self.error
        self.instructions.append(instruction)
        return dict(self.result)

    def focused_control_type(self) -> str | None:
        return self.focus_type

    def find_windows(self, title=None, process=None, hwnd=None) -> list[dict]:
        if hwnd is None:
            return list(self.live_windows)
        return [w for w in self.live_windows if w.get("hwnd") == hwnd]

    def capture_approval_shot(self, rect) -> str:
        if self.approval_shot_error:
            raise ExecutorError("INTERNAL_ERROR", "shot fail")
        self.approval_shot_rects.append(tuple(rect))
        return self.approval_shot_path


def make_policy(audit_dir: str = "", **overrides) -> models.Policy:
    """直接装配策略对象（测试布置用；策略加载行为本身由 test_policy 覆盖）。"""
    base = dict(
        whitelist={"notepad.exe": "L2", "explorer.exe": "L1"},
        terminal_apps=frozenset(
            {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe"}),
        l2_keys=frozenset(
            {"enter", "tab", "backspace", "home", "end", "pageup", "pagedown",
             "up", "down", "left", "right", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z",
             "ctrl+y", "ctrl+s", "ctrl+home", "ctrl+end"}
            | {f"f{i}" for i in range(1, 13)}),
        l3_keys=frozenset({"delete", "escape", "alt+f4", "ctrl+w", "ctrl+shift+escape"}),
        input_scenario_keys=frozenset({"backspace"}),
        input_control_types=frozenset({"Edit", "Document"}),
        binding_ttl=600.0, approval_ttl=60.0, wait_poll_interval=0.5,
        wait_timeout_max=300.0, input_max_chars=65536,
        l0_during_freeze=True, corner_hold_ms=200, freeze_remind_interval=180.0,
        audit_dir=audit_dir,
    )
    base.update(overrides)
    return models.Policy(**base)


def policy_yaml_dict(audit_dir: str) -> dict:
    """合法策略文件内容（limits/estop/input_* 节缺省，用于验证默认值）。"""
    return {
        "whitelist": [{"process": "notepad.exe"},
                      {"process": "explorer.exe", "max_level": "L1"}],
        "terminal_apps": ["cmd.exe", "powershell.exe", "pwsh.exe",
                          "windowsterminal.exe", "wt.exe"],
        "keys": {
            "l2_allow": (["enter", "tab", "backspace", "home", "end", "pageup",
                          "pagedown", "up", "down", "left", "right"]
                         + [f"f{i}" for i in range(1, 13)]
                         + ["ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y",
                            "ctrl+s", "ctrl+home", "ctrl+end"]),
            "l3_controlled": ["delete", "escape", "alt+f4", "ctrl+w",
                              "ctrl+shift+escape"],
        },
        "timeouts": {"binding_ttl": 600, "approval_ttl": 60,
                     "wait_poll_interval": 0.5, "wait_timeout_max": 300},
        "audit_dir": audit_dir,
    }


def read_audit(audit_dir: str) -> list[dict]:
    """读取审计 JSONL（持久化数据断言通道）。"""
    log_dir = Path(audit_dir) / "logs"
    if not log_dir.is_dir():
        return []
    records: list[dict] = []
    for f in sorted(log_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


# ---------- fixtures ----------

@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def probe() -> FakeProbe:
    return FakeProbe()


@pytest.fixture
def policy(tmp_path) -> models.Policy:
    return make_policy(audit_dir=str(tmp_path / "audit"))


@pytest.fixture
def bindings(policy, probe, clock) -> BindingManager:
    return BindingManager(probe, policy.binding_ttl, clock)


@pytest.fixture
def approver() -> FakeApprover:
    return FakeApprover()


@pytest.fixture
def approvals(policy, approver, clock) -> ApprovalManager:
    return ApprovalManager(approver, policy.approval_ttl, clock)


@pytest.fixture
def audit_log(tmp_path) -> AuditLogger:
    return AuditLogger(str(tmp_path / "audit"))


@pytest.fixture
def estop(policy, clock, audit_log) -> EstopMonitor:
    return EstopMonitor(policy.corner_hold_ms, clock, audit_log)


@pytest.fixture
def executor() -> FakeExecutor:
    return FakeExecutor()


@pytest.fixture
def enforcement(policy, bindings, approvals, estop, executor, audit_log) -> Enforcement:
    return Enforcement(policy, bindings, approvals, estop, executor, audit_log)


@pytest.fixture
def ctx(policy, enforcement) -> ToolContext:
    return ToolContext(policy=policy, enforcement=enforcement)


@pytest.fixture
def bound_record(bindings) -> models.BindingRecord:
    """已建立的固件窗口绑定。"""
    return bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
