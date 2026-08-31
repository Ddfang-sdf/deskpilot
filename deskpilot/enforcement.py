"""强制层程序（详细设计 §8）——安全核心。

写操作唯一入口：四道闸裁决（绑定校验 → 白名单 → 按键许可 → L3 令牌），
判定依据全部来自程序可验证的事实；冻结标志前置检查；放行与被拒全覆盖审计。
审计决策记录先于执行落盘——审计不可缺失，审计失败则动作不发生（INV-6）。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .approval import ApprovalManager, compute_fingerprint
from .audit import AuditLogger
from .binding import BindingManager
from .errors import (APPROVAL_DENIED, APPROVAL_TIMEOUT, AUDIT_FAILURE,
                     EMERGENCY_STOP, INVALID_PARAMS, KEY_DENIED,
                     KEY_UNKNOWN, NO_BINDING, NOT_WHITELISTED,
                     POLICY_VIOLATION, AuditFailure, ExecutorError)
from .estop import EstopMonitor
from .executor import Executor
from .models import (BINDING_REQUIRED_TOOLS, L0, L1, L2, L3, TOOL_LEVELS,
                     AuditEntry, BindingRecord, Decision, OperationRequest,
                     Policy)
from .policy import normalize_key

_LEVEL_ORDER = {L0: 0, L1: 1, L2: 2, L3: 3}
_TEXT_TOOLS = {"type_text", "type_element", "set_clipboard"}


class Enforcement:
    """四道闸裁决器。"""

    def __init__(self, policy: Policy, bindings: BindingManager,
                 approvals: ApprovalManager, estop: EstopMonitor,
                 executor: Executor, audit_log: AuditLogger):
        self._policy = policy
        self._bindings = bindings
        self._approvals = approvals
        self._estop = estop
        self._executor = executor
        self._audit = audit_log

    def submit(self, request: OperationRequest) -> Decision:
        """对写操作请求执行四道闸裁决（详细设计 §8.7 流程）。"""
        t0 = time.monotonic()
        tool = request.tool
        level = TOOL_LEVELS.get(tool)
        if level is None:
            return self._deny(request, "", INVALID_PARAMS, f"未知工具: {tool}", t0)

        # G0 冻结检查（最先，详细设计 §8.7）
        if self._estop.is_frozen():
            return self._deny(request, level, EMERGENCY_STOP,
                              "急停冻结中：停止一切写尝试，等待人类复位", t0)

        # 闸一 绑定校验（INV-1；launch_app 豁免，见 §8.7 豁免规则）
        binding: BindingRecord | None = None
        if tool in BINDING_REQUIRED_TOOLS:
            binding = self._bindings.validate(request.binding_token)
            if binding is None:
                return self._deny(request, level, NO_BINDING,
                                  "无有效绑定：请先 attach；原绑定可能已超时或窗口已关",
                                  t0)

        # 有效级别 = max(静态级别, 动态升级)（§8.6）
        eff = level
        target_proc = (binding.process_name if binding else
                       str(request.params.get("process", "")).strip().lower())
        if target_proc and target_proc in self._policy.terminal_apps:
            eff = L3                          # 终端窗口规则（attach 终端即 L3）

        # 闸二 应用白名单（INV-2）
        if tool == "launch_app":
            target = str(request.params.get("app", "")).strip().lower()
            # 路径归一：允许按完整路径启动（取进程基名比对白名单）
            target = target.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            if target in self._policy.whitelist:
                cap = self._policy.whitelist[target]
            else:
                cap = L3
                eff = L3                                      # launch 非白名单升 L3
        else:
            cap = self._policy.whitelist.get(target_proc)
            if cap is None and target_proc in self._policy.terminal_apps:
                cap = L3            # 终端类成员资格满足闸二（attach 已经 L3 审批）
            if cap is None:
                return self._deny(
                    request, eff, NOT_WHITELISTED,
                    f"目标进程 {target_proc} 不在白名单。如需加入：请人类管理员在 "
                    f"policy.yml 的 whitelist 节添加该进程并重启服务（INV-9）", t0)
        if _LEVEL_ORDER[eff] > _LEVEL_ORDER[cap]:
            return self._deny(request, eff, POLICY_VIOLATION,
                              f"操作级别 {eff} 超出该进程白名单条目上限 {cap}", t0)

        # 闸三 按键许可表（仅 key 类触发；含输入场景判定）
        if tool == "key":
            norm = normalize_key(str(request.params.get("key", "")))
            cls = self._classify_key(norm)
            if cls == "unknown":
                return self._deny(request, eff, KEY_UNKNOWN,
                                  f"按键未收录（fail-closed）: {norm}", t0)
            if cls == "scenario_l2":
                focus = self._executor.focused_control_type()
                if focus is None or focus not in self._policy.input_control_types:
                    return self._deny(
                        request, eff, KEY_DENIED,
                        f"场景受限键 {norm} 仅在输入场景放行（焦点为 "
                        f"{'/'.join(sorted(self._policy.input_control_types))}）；"
                        f"判定失败按非许可场景处理", t0)
            if cls == "l3":
                eff = L3                              # 危险键升级 L3（§8.6）

        # 闸四 L3 同步审批（ISS-0003：同步等待人类裁决，AI 自发起后退出环路）
        if eff == L3:
            fp = compute_fingerprint(tool, self._fingerprint_params(request))
            desc = self._describe(request, binding)
            image_path = self._capture_target(binding)
            # ISS-0007 B：审批弹窗按目标窗口所在屏落位
            target_rect = binding.window_rect if binding else None
            decision = self._approvals.request_approval(
                desc, fp, image_path=image_path, target_rect=target_rect)
            if decision != "approve":
                code = APPROVAL_TIMEOUT if decision == "timeout" \
                    else APPROVAL_DENIED
                guidance = ("审批超时：人类未在时限内裁决，请留意本地审批弹窗后"
                            "重新发起" if decision == "timeout" else
                            "受控操作未获人类批准")
                return self._deny(request, eff, code,
                                  f"{guidance}：{desc}", t0)
            self._approvals.verify_and_consume(fp)    # 即验即销（服务内部闭环）
            # 执行前复核（ISS-0003 整改项 E + 冻结双检查 §9.7）：
            # 同步等待裁决期间可能已触发急停、目标窗口可能已失效
            if self._estop.is_frozen():
                return self._deny(request, eff, EMERGENCY_STOP,
                                  "急停冻结中：停止一切写尝试，等待人类复位", t0)
            if binding is not None and \
                    self._bindings.validate(request.binding_token) is None:
                return self._deny(request, eff, NO_BINDING,
                                  "批准等待期间目标绑定已失效（窗口已关或超时）", t0)

        # attach / detach 仅过闸不落执行层（绑定动作由工具层完成）
        if tool in {"attach", "detach"}:
            if not self._write_audit(request, eff, "放行", "", "ok", "", "", t0):
                return Decision(False, AUDIT_FAILURE, "审计写盘失败，操作未执行", eff)
            return Decision(True, "", "ok", eff)

        # 放行 → 决策记录先于执行落盘 → 执行 → 完成记录
        if not self._write_audit(request, eff, "放行", "", "执行中", "", "", t0):
            return Decision(False, AUDIT_FAILURE, "审计写盘失败，操作未执行", eff)
        instruction = {"tool": tool, "params": params_of(request),
                       "binding_hwnd": binding.hwnd if binding else None}
        try:
            result = self._executor.execute(instruction)
        except ExecutorError as e:
            self._write_audit(request, eff, "放行", e.code, e.message, "", "", t0)
            return Decision(False, e.code, e.message, eff)
        if not self._write_audit(request, eff, "放行", "", "ok",
                                 str(result.get("before_shot", "")),
                                 str(result.get("after_shot", "")), t0):
            return Decision(False, AUDIT_FAILURE, "审计写盘失败（完成记录）", eff)
        return Decision(True, "", "ok", eff, data=result)

    # ---- 内部 ----

    def _classify_key(self, norm: str) -> str:
        """按键分类：l2 / scenario_l2 / l3 / unknown（§8.6）。"""
        if len(norm) == 1 and norm.isprintable():
            return "l2"                                       # 字符
        if norm in self._policy.l2_keys:
            return "scenario_l2" if norm in self._policy.input_scenario_keys else "l2"
        if norm in self._policy.l3_keys:
            return "l3"
        mods = norm.split("+")[:-1]
        if "alt" in mods or "win" in mods:
            return "l3"            # 任何含 Alt 的组合 / Win 系列
        return "unknown"

    def _fingerprint_params(self, request: OperationRequest) -> dict:
        params = dict(request.params)
        params["token"] = request.binding_token or ""
        return params

    # ---- 审批描述（人话层 + 技术底注）与目标实拍 ----

    _KEY_ACTIONS = {
        "alt+f4": "关闭窗口",
        "delete": "按 Delete 删除键",
        "escape": "按 Escape 键",
        "ctrl+w": "关闭当前标签页",
        "ctrl+shift+escape": "打开任务管理器",
    }
    _TOOL_ACTIONS = {
        "launch_app": "启动应用",
        "activate_window": "激活窗口",
        "click": "鼠标点击",
        "click_element": "点击控件",
        "type_text": "输入文本",
        "type_element": "向控件输入文本",
        "set_clipboard": "改写剪贴板内容",
        "drag": "鼠标拖拽",
        "key": "按键",
    }

    def _live_title(self, binding: BindingRecord) -> str:
        """窗口标题以当前活值为准；查不到退回绑定快照。"""
        try:
            wins = self._executor.find_windows(hwnd=binding.hwnd)
        except Exception:
            wins = []
        for w in wins:
            if w.get("title"):
                return w["title"]
        return binding.window_title

    def _capture_target(self, binding: BindingRecord | None) -> str | None:
        """闸四配套：实拍目标窗口供审批弹窗展示；任何失败不阻断审批流。"""
        if binding is None:
            return None
        try:
            return self._executor.capture_approval_shot(binding.window_rect)
        except Exception:
            return None

    def _describe(self, request: OperationRequest,
                  binding: BindingRecord | None) -> str:
        """两段式描述:人话标题行 + 「---」分隔 + 技术底注(进程/句柄保留)。"""
        tech_target = ""
        if binding is not None:
            title = self._live_title(binding)
            plain_target = (f"「{title}」" if title
                            else f"进程 {binding.process_name} 的窗口")
            tech_target = (f"进程 {binding.process_name} 的窗口"
                           f"（句柄 {binding.hwnd}）")
        else:
            plain_target = str(request.params.get("app", ""))
            tech_target = f"应用 {plain_target}"

        if request.tool == "key":
            key = normalize_key(str(request.params.get("key", "")))
            action = self._KEY_ACTIONS.get(key, f"按下 {key}")
            headline = f"{action}{plain_target}" if binding else f"{action}"
            tech = f"按键 {key} 作用于{tech_target}"
        elif request.tool == "launch_app":
            headline = f"启动应用 {plain_target}"
            tech = f"launch_app 作用于{tech_target}"
        else:
            action = self._TOOL_ACTIONS.get(request.tool, f"执行 {request.tool}")
            headline = f"{action}{plain_target}"
            tech = f"{request.tool}（参数 {self._digest(request)}）作用于{tech_target}"
        return f"{headline}\n---\n{tech}"

    def _digest(self, request: OperationRequest) -> str:
        return ", ".join(f"{k}={v}" for k, v in request.params.items())

    def _deny(self, request: OperationRequest, level: str, code: str,
              message: str, t0: float) -> Decision:
        self._write_audit(request, level, "拒绝", code, message, "", "", t0)
        return Decision(False, code, message, level)

    def _write_audit(self, request: OperationRequest, level: str, decision: str,
                     reason_code: str, result: str, before: str, after: str,
                     t0: float) -> bool:
        text = request.params.get("text", "")
        entry = AuditEntry(
            seq=0,
            timestamp=datetime.now().astimezone().isoformat(),
            tool=request.tool,
            params_digest=self._digest(request),
            params_full=str(text) if request.tool in _TEXT_TOOLS else "",
            level=level,
            decision=decision,
            reason_code=reason_code,
            result=result,
            duration_ms=int((time.monotonic() - t0) * 1000),
            before_shot=before,
            after_shot=after,
            binding_token=request.binding_token or "",
        )
        try:
            self._audit.record(entry)
            return True
        except AuditFailure:
            return False


def params_of(request: OperationRequest) -> dict[str, Any]:
    return dict(request.params)
