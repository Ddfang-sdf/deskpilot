"""强制层（Enforcement.submit 四道闸）单元测试。

覆盖：TC-S-BIND-01、TC-S-WL-02/03/04、TC-S-KEY-01～06、TC-S-TOK-01/03/06、
TC-S-EST-03/04、TC-S-ATK-05、TC-S-AUD-01/03、TC-E-CC-01、TC-E-ST-05/06、
TC-N-APR-01/03、TC-E-ENV-01、launch_app 豁免规则（DDS §8.7）。
断言值来源：submit 返回的 Decision、executor 收到的指令、审计 JSONL 持久化数据。
"""

from __future__ import annotations

import pytest

from deskpilot import errors
from deskpilot.models import OperationRequest
from deskpilot.errors import ExecutorError

from .conftest import (FIXTURE_HWND, FIXTURE_HWND_B, FIXTURE_RECT,
                       FIXTURE_RECT_B, read_audit)

WRITE_TOOLS_WITH_BINDING = ["activate_window", "click_element", "type_element",
                            "click", "type_text", "key", "set_clipboard", "drag"]


def _req(tool, params=None, token=None):
    return OperationRequest(tool=tool, params=params or {}, binding_token=token)


class TestGate1Binding:
    def test_no_binding_all_write_tools(self, enforcement, executor):
        """TC-S-BIND-01：无令牌调用全部写工具一律 NO_BINDING，执行层零接触。"""
        for tool in WRITE_TOOLS_WITH_BINDING:
            d = enforcement.submit(_req(tool, token=None))
            assert d.allowed is False
            assert d.reason_code == errors.NO_BINDING, tool
        assert executor.instructions == []

    def test_low_profile_write_tools_need_binding(self, enforcement):
        """TC-S-ATK-05：scroll / set_clipboard 无绑定同标准拒绝。"""
        d1 = enforcement.submit(_req("scroll", {"direction": "down", "amount": 3}))
        d2 = enforcement.submit(_req("set_clipboard", {"text": "x"}))
        assert d1.reason_code == errors.NO_BINDING
        assert d2.reason_code == errors.NO_BINDING


class TestGate2Whitelist:
    def test_process_not_whitelisted(self, enforcement, bindings, probe):
        """TC-S-WL-02：目标进程不在白名单 → NOT_WHITELISTED，含申请说明。"""
        probe.processes[FIXTURE_HWND] = "evil.exe"
        rec = bindings.create(FIXTURE_HWND, "evil.exe", FIXTURE_RECT)
        d = enforcement.submit(_req("type_text", {"text": "x"}, rec.token))
        assert d.allowed is False
        assert d.reason_code == errors.NOT_WHITELISTED
        assert "白名单" in d.message                 # 附申请加入白名单说明

    def test_policy_violation_level_cap(self, enforcement, bindings, probe):
        """TC-S-WL-03：explorer.exe 上限 L1，发起 L2 写入 → POLICY_VIOLATION。"""
        probe.processes[FIXTURE_HWND] = "explorer.exe"
        rec = bindings.create(FIXTURE_HWND, "explorer.exe", FIXTURE_RECT)
        d = enforcement.submit(_req("type_text", {"text": "x"}, rec.token))
        assert d.allowed is False
        assert d.reason_code == errors.POLICY_VIOLATION

    def test_process_name_case_insensitive(self, enforcement, bindings, probe):
        """TC-S-WL-04：进程名大小写归一后正常判定。"""
        probe.processes[FIXTURE_HWND] = "NOTEPAD.EXE"
        rec = bindings.create(FIXTURE_HWND, "NOTEPAD.EXE", FIXTURE_RECT)
        d = enforcement.submit(_req("type_text", {"text": "x"}, rec.token))
        assert d.allowed is True


class TestGate3Keys:
    def test_dangerous_key_needs_approval(self, enforcement, bound_record, approver):
        """TC-S-KEY-01：危险键无批准 → NEEDS_APPROVAL，附完整操作描述并发起审批。"""
        d = enforcement.submit(_req("key", {"key": "alt+f4"}, bound_record.token))
        assert d.allowed is False
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert "alt+f4" in d.message                 # 操作描述含按键
        assert "notepad.exe" in d.message            # 含目标进程
        assert len(approver.requests) == 1           # 已向审批通道发起请求
        assert "alt+f4" in approver.requests[0]["description"]


class TestDescribePlainLanguage:
    """审批描述的人话层：标题行动作翻译 + 窗口标题，技术行置底保留。"""

    def test_altf4_with_window_title(self, enforcement, bindings):
        """alt+f4 → 「关闭窗口『标题』」；技术行保留按键/进程/句柄。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT,
                              window_title="无标题 - 记事本")
        d = enforcement.submit(_req("key", {"key": "alt+f4"}, rec.token))
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert "关闭窗口" in d.message
        assert "「无标题 - 记事本」" in d.message
        assert "alt+f4" in d.message                 # 技术行保留
        assert "notepad.exe" in d.message
        assert f"句柄 {FIXTURE_HWND}" in d.message

    def test_live_title_overrides_stale_binding(self, enforcement, bindings, executor):
        """窗口标题以审批时刻的活值为准（绑定快照可能已过期）。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT,
                              window_title="旧标题")
        executor.live_windows = [{"hwnd": FIXTURE_HWND,
                                  "title": "settings.json - Notepad"}]
        d = enforcement.submit(_req("key", {"key": "alt+f4"}, rec.token))
        assert "settings.json - Notepad" in d.message
        assert "旧标题" not in d.message

    def test_key_without_title_falls_back_to_process(self, enforcement, bindings):
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        d = enforcement.submit(_req("key", {"key": "delete"}, rec.token))
        assert "Delete" in d.message
        assert "notepad.exe" in d.message

    def test_launch_app_plain_action(self, enforcement):
        """非白名单 launch_app 升 L3：人话为「启动应用 xxx」。"""
        d = enforcement.submit(_req("launch_app", {"app": "evil.exe"}))
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert "启动应用 evil.exe" in d.message

    def test_type_text_plain_action(self, enforcement, bound_record):
        d = enforcement.submit(_req("key", {"key": "ctrl+shift+escape"},
                                    bound_record.token))
        assert "任务管理器" in d.message


class TestApprovalTargetShot:
    """闸四发起审批时实拍目标窗口，图像路径随审批请求传递。"""

    def test_l3_request_captures_target_window(self, enforcement, bound_record,
                                               approver, executor):
        d = enforcement.submit(_req("key", {"key": "alt+f4"}, bound_record.token))
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert executor.approval_shot_rects == [FIXTURE_RECT]
        assert approver.requests[0]["image_path"] == executor.approval_shot_path

    def test_capture_failure_still_sends_request(self, enforcement, bound_record,
                                                 approver, executor):
        """截图失败（窗口最小化等）不得阻断审批流，image_path 置 None。"""
        executor.approval_shot_error = True
        d = enforcement.submit(_req("key", {"key": "alt+f4"}, bound_record.token))
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert approver.requests[0]["image_path"] is None

    def test_no_binding_no_capture(self, enforcement, approver, executor):
        """launch_app 等无绑定审批不截图（目标尚不存在）。"""
        d = enforcement.submit(_req("launch_app", {"app": "evil.exe"}))
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert executor.approval_shot_rects == []
        assert approver.requests[0]["image_path"] is None

    @pytest.mark.parametrize("danger", [
        "delete", "escape", "ctrl+w", "ctrl+shift+escape", "alt+f4",
        "alt+tab", "win+e",                          # 含 Alt / Win 组合按规则升 L3
    ])
    def test_all_dangerous_keys(self, enforcement, bound_record, danger):
        """TC-S-KEY-02：危险键表逐一拒绝。"""
        d = enforcement.submit(_req("key", {"key": danger}, bound_record.token))
        assert d.reason_code == errors.NEEDS_APPROVAL, danger

    def test_enter_notepad_allowed_terminal_denied(self, enforcement, bindings,
                                                   probe, bound_record, executor):
        """TC-S-KEY-03：Enter 在记事本是 L2 放行，在终端类绑定下升级 L3 拒绝。"""
        d1 = enforcement.submit(_req("key", {"key": "enter"}, bound_record.token))
        assert d1.allowed is True

        probe.processes[FIXTURE_HWND_B] = "cmd.exe"
        term = bindings.create(FIXTURE_HWND_B, "cmd.exe", FIXTURE_RECT_B)
        d2 = enforcement.submit(_req("key", {"key": "enter"}, term.token))
        assert d2.allowed is False
        assert d2.reason_code == errors.NEEDS_APPROVAL

    def test_unknown_key(self, enforcement, bound_record):
        """TC-S-KEY-04：未收录按键 fail-closed。"""
        d = enforcement.submit(_req("key", {"key": "ctrl+shift+f8"}, bound_record.token))
        assert d.reason_code == errors.KEY_UNKNOWN

    def test_reset_hotkey_never_allowed(self, enforcement, bound_record):
        """TC-S-EST-03 关联：复位组合键永不进许可表 → KEY_UNKNOWN。"""
        d = enforcement.submit(_req("key", {"key": "ctrl+shift+f11"},
                                    bound_record.token))
        assert d.reason_code == errors.KEY_UNKNOWN

    @pytest.mark.parametrize("alias,expect_ok", [
        ("Return", True), ("ENTER", True),                 # 别名归一为 enter（L2）
        ("alt+F4", False), ("F4+Alt", False),              # 变形仍判危险键
    ])
    def test_alias_normalization(self, enforcement, bound_record, alias, expect_ok):
        """TC-S-KEY-05：别名/大小写/修饰键顺序变形后一致判定。"""
        d = enforcement.submit(_req("key", {"key": alias}, bound_record.token))
        assert d.allowed is expect_ok, alias
        if not expect_ok:
            assert d.reason_code == errors.NEEDS_APPROVAL

    def test_backspace_input_scenario_allowed(self, enforcement, bound_record, executor):
        """TC-S-KEY-06：焦点为 Edit 控件（输入场景）→ Backspace 放行。"""
        executor.focus_type = "Edit"
        d = enforcement.submit(_req("key", {"key": "backspace"}, bound_record.token))
        assert d.allowed is True

    def test_backspace_non_input_scenario_denied(self, enforcement, bound_record, executor):
        """TC-S-KEY-06：焦点非编辑控件 → KEY_DENIED。"""
        executor.focus_type = "MenuItem"
        d = enforcement.submit(_req("key", {"key": "backspace"}, bound_record.token))
        assert d.allowed is False
        assert d.reason_code == errors.KEY_DENIED

    def test_backspace_probe_failure_denied(self, enforcement, bound_record, executor):
        """TC-S-KEY-06：焦点探测失败按非许可场景处理（fail-closed）。"""
        executor.focus_type = None
        d = enforcement.submit(_req("key", {"key": "backspace"}, bound_record.token))
        assert d.reason_code == errors.KEY_DENIED


class TestGate4Approval:
    def test_approved_retry_passes_once(self, enforcement, bound_record, approver,
                                        executor):
        """TC-N-APR-01 + TC-S-TOK-01：批准→原样重试放行一次→第三次拒绝。"""
        approver.decision = True
        req = _req("key", {"key": "alt+f4"}, bound_record.token)
        d1 = enforcement.submit(req)
        assert d1.reason_code == errors.NEEDS_APPROVAL

        d2 = enforcement.submit(req)               # 完全相同参数原样重试
        assert d2.allowed is True
        assert len(executor.instructions) == 1

        d3 = enforcement.submit(req)               # 令牌已消费 → 再次拒绝
        assert d3.reason_code == errors.NEEDS_APPROVAL

    def test_param_variation_rejected(self, enforcement, bound_record, approver):
        """TC-S-TOK-03：批准后改动任一参数，指纹不匹配拒绝。"""
        approver.decision = True
        enforcement.submit(_req("key", {"key": "delete"}, bound_record.token))
        # 换一个仍为 L3 的按键（参数不同 → 指纹不同；shift+delete 未收录
        # 会在闸三命中 KEY_UNKNOWN，不适用本用例，故选 escape）
        d = enforcement.submit(_req("key", {"key": "escape"},
                                    bound_record.token))
        assert d.reason_code == errors.NEEDS_APPROVAL

    def test_self_declared_force_flag_useless(self, enforcement, bound_record, approver):
        """TC-S-TOK-06：自报 force 参数不改变裁决；无批准仍拒绝。"""
        approver.decision = False
        d = enforcement.submit(
            _req("key", {"key": "alt+f4", "force": True}, bound_record.token))
        assert d.allowed is False
        assert d.reason_code == errors.NEEDS_APPROVAL

    def test_terminal_binding_all_writes_l3(self, enforcement, bindings, probe):
        """TC-N-APR-03 关联：终端类绑定下 type_text 也升级 L3。"""
        probe.processes[FIXTURE_HWND_B] = "cmd.exe"
        term = bindings.create(FIXTURE_HWND_B, "cmd.exe", FIXTURE_RECT_B)
        d = enforcement.submit(_req("type_text", {"text": "dir"}, term.token))
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert d.effective_level == "L3"

    def test_regate_after_approval_window_gone(self, enforcement, bound_record,
                                               approver, probe):
        """TC-E-ST-05：批准等待期间窗口关闭，重过闸拒绝。"""
        approver.decision = True
        req = _req("key", {"key": "alt+f4"}, bound_record.token)
        enforcement.submit(req)
        probe.alive[FIXTURE_HWND] = False          # 批准等待期间窗口被关
        d = enforcement.submit(req)
        assert d.allowed is False
        assert d.reason_code == errors.NO_BINDING

    def test_regate_after_approval_frozen(self, enforcement, bound_record, approver,
                                          estop):
        """TC-E-ST-06：批准后进入冻结态，重过闸拒绝。"""
        approver.decision = True
        req = _req("key", {"key": "alt+f4"}, bound_record.token)
        enforcement.submit(req)
        estop.on_trigger_hotkey()
        d = enforcement.submit(req)
        assert d.reason_code == errors.EMERGENCY_STOP


class TestFrozen:
    def test_frozen_all_writes_denied(self, enforcement, bound_record, estop):
        """TC-S-EST-04：冻结期全部写工具 EMERGENCY_STOP。"""
        estop.on_trigger_hotkey()
        for tool in WRITE_TOOLS_WITH_BINDING:
            d = enforcement.submit(_req(tool, token=bound_record.token))
            assert d.reason_code == errors.EMERGENCY_STOP, tool

    def test_frozen_before_binding_check(self, enforcement, estop):
        """TC-E-CC-01 关联：冻结检查在闸一之前（G0 最先）。"""
        estop.on_trigger_hotkey()
        d = enforcement.submit(_req("key", {"key": "a"}, token=None))
        assert d.reason_code == errors.EMERGENCY_STOP   # 而非 NO_BINDING


class TestLaunchAppExemption:
    def test_launch_app_no_binding_needed(self, enforcement, executor):
        """DDS §8.7 豁免规则：launch_app 豁免闸一，白名单内直接放行。"""
        d = enforcement.submit(_req("launch_app", {"app": "notepad.exe"}))
        assert d.allowed is True
        assert len(executor.instructions) == 1

    def test_launch_app_non_whitelist_escalates(self, enforcement):
        """launch 非白名单目标 → 升级 L3 → NEEDS_APPROVAL。"""
        d = enforcement.submit(_req("launch_app", {"app": "mspaint.exe"}))
        assert d.allowed is False
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert d.effective_level == "L3"


class TestExecutionAndAudit:
    def test_allowed_calls_executor_with_instruction(self, enforcement, bound_record,
                                                     executor):
        """放行路径：执行层收到完整指令；裁决返回执行结果数据。"""
        d = enforcement.submit(_req("type_text", {"text": "hello"},
                                    bound_record.token))
        assert d.allowed is True
        assert len(executor.instructions) == 1
        ins = executor.instructions[0]
        assert ins["tool"] == "type_text"
        assert ins["params"]["text"] == "hello"
        assert ins["binding_hwnd"] == FIXTURE_HWND
        assert d.data == executor.result

    def test_executor_error_surfaces(self, enforcement, bound_record, executor):
        """执行期错误码透传（如 OUT_OF_BOUNDS）。"""
        executor.error = ExecutorError(errors.OUT_OF_BOUNDS, "落点在窗口外")
        d = enforcement.submit(_req("click", {"x": 1, "y": 1}, bound_record.token))
        assert d.allowed is False
        assert d.reason_code == errors.OUT_OF_BOUNDS

    def test_every_decision_audited(self, enforcement, bindings, probe,
                                    bound_record, audit_log, tmp_path):
        """TC-S-AUD-01：四条闸拒绝 + 一次放行均有审计记录。"""
        enforcement.submit(_req("type_text", {"text": "x"}))                     # 闸一
        probe.processes[FIXTURE_HWND_B] = "evil.exe"
        evil = bindings.create(FIXTURE_HWND_B, "evil.exe", FIXTURE_RECT_B)
        enforcement.submit(_req("type_text", {"text": "x"}, evil.token))        # 闸二
        enforcement.submit(_req("key", {"key": "ctrl+shift+f8"},
                                bound_record.token))                            # 闸三
        enforcement.submit(_req("key", {"key": "delete"}, bound_record.token))  # 闸四
        enforcement.submit(_req("type_text", {"text": "ok"}, bound_record.token))

        records = read_audit(str(tmp_path / "audit"))
        denied = [r for r in records if r["decision"] == "拒绝"]
        assert len(denied) == 4
        assert [r["reason_code"] for r in denied] == [
            errors.NO_BINDING, errors.NOT_WHITELISTED,
            errors.KEY_UNKNOWN, errors.NEEDS_APPROVAL]
        assert any(r["decision"] == "放行" for r in records)

    def test_audit_failure_blocks_execution(self, enforcement, bound_record, executor,
                                            audit_log, monkeypatch):
        """TC-S-AUD-03 / TC-E-ENV-01：审计写失败 → 操作失败且执行层未被调用。"""
        def boom(entry):
            raise errors.AuditFailure("磁盘不可写")
        monkeypatch.setattr(audit_log, "record", boom)
        d = enforcement.submit(_req("type_text", {"text": "x"}, bound_record.token))
        assert d.allowed is False
        assert d.reason_code == errors.AUDIT_FAILURE
        assert executor.instructions == []         # 动作未生效

    def test_short_circuit_gate_order(self, enforcement):
        """短路：无绑定 + 危险键 → 闸一先拒（NO_BINDING 而非 KEY_*）。"""
        d = enforcement.submit(_req("key", {"key": "alt+f4"}, token=None))
        assert d.reason_code == errors.NO_BINDING


class TestAttachGate:
    """attach 过闸（不落执行层；终端类 attach 即 L3）。"""

    def test_attach_whitelisted_allowed_no_executor(self, enforcement, executor):
        d = enforcement.submit(_req("attach", {"process": "notepad.exe"}))
        assert d.allowed is True
        assert executor.instructions == []          # attach 不落执行层

    def test_attach_not_whitelisted(self, enforcement):
        d = enforcement.submit(_req("attach", {"process": "evil.exe"}))
        assert d.reason_code == errors.NOT_WHITELISTED

    def test_attach_terminal_is_l3(self, enforcement):
        d = enforcement.submit(_req("attach", {"process": "cmd.exe"}))
        assert d.reason_code == errors.NEEDS_APPROVAL
        assert d.effective_level == "L3"


class TestLaunchPathNormalization:
    """launch_app 按完整路径启动时，白名单按进程基名归一匹配。"""

    def test_full_path_launch_allowed(self, enforcement, executor):
        d = enforcement.submit(OperationRequest(
            tool="launch_app",
            params={"app": "C:/Windows/System32/notepad.exe"},
            binding_token=None))
        assert d.allowed is True
        assert executor.instructions[0]["params"]["app"].endswith("notepad.exe")

    def test_bare_name_still_allowed(self, enforcement):
        d = enforcement.submit(OperationRequest(
            tool="launch_app", params={"app": "notepad.exe"},
            binding_token=None))
        assert d.allowed is True
