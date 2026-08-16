"""测试基建：固件窗口替身、假探测、假审批通道、假执行层、测试时钟。

所有替身均实现设计文档定义的公开接口（WindowProbe / ApprovalChannel / Executor），
测试断言只基于被调方法的返回值或持久化数据（审计 JSONL）。
"""

from __future__ import annotations

import json
from pathlib import Path

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

    def hwnd_alive(self, hwnd: int) -> bool:
        return self.alive.get(hwnd, False)

    def process_of(self, hwnd: int) -> str:
        return self.processes.get(hwnd, "")

    def rect_of(self, hwnd: int):
        return self.rects.get(hwnd, (0, 0, 0, 0))


class FakeApprover:
    """模拟审批通道（实现 approval.ApprovalChannel 公开接口）。"""

    def __init__(self):
        self.decision = False          # 是否批准
        self.requests: list[dict] = []  # 送达通道的审批请求

    def request(self, description: str, fingerprint: str) -> bool:
        self.requests.append({"description": description, "fingerprint": fingerprint})
        return self.decision


class FakeExecutor:
    """假执行层（实现 executor.Executor 公开入口；记录收到的指令）。"""

    def __init__(self):
        self.instructions: list[dict] = []
        self.focus_type: str | None = "Edit"
        self.error: ExecutorError | None = None
        self.result = {"status": "ok", "before_shot": "shots/b.png",
                       "after_shot": "shots/a.png"}

    def execute(self, instruction: dict) -> dict:
        if self.error is not None:
            raise self.error
        self.instructions.append(instruction)
        return dict(self.result)

    def focused_control_type(self) -> str | None:
        return self.focus_type


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
        l0_during_freeze=True, corner_hold_ms=200,
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
