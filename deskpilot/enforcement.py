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
                     ELEVATION_REQUIRED, EMERGENCY_STOP, INVALID_PARAMS,
                     KEY_DENIED, KEY_UNKNOWN, NO_BINDING, NOT_WHITELISTED,
                     POLICY_VIOLATION, AuditFailure, ExecutorError)
from .estop import EstopMonitor
from .executor import Executor
from .models import (BINDING_REQUIRED_TOOLS, L0, L1, L2, L3, TOOL_LEVELS,
                     AuditEntry, BindingRecord, Decision, OperationRequest,
                     Policy)
from .policy import normalize_key
from .whitelist_admin import NEVER_ENROLL, WhitelistAdmin

_LEVEL_ORDER = {L0: 0, L1: 1, L2: 2, L3: 3}
_TEXT_TOOLS = {"type_text", "type_element", "set_clipboard"}


# ---------- ISS-0017 B：提权级别解析（公开接缝，测试可替身） ----------

def _elevation_of_process(pid: int) -> str:
    """进程提权级别:"full"(管理员) / "limited"(标准) / "default"(随父)。
    打开/查询失败抛 OSError——由调用方按 fail-closed 拒绝。"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    adv = ctypes.windll.advapi32
    h = k32.OpenProcess(0x1000, False, pid)      # QUERY_LIMITED_INFORMATION
    if not h:
        raise OSError(f"OpenProcess 失败 pid={pid}")
    try:
        token = wintypes.HANDLE()
        if not adv.OpenProcessToken(h, 0x0008, ctypes.byref(token)):
            raise OSError(f"OpenProcessToken 失败 pid={pid}")
        try:
            etype = wintypes.DWORD()
            out_len = wintypes.DWORD()
            if not adv.GetTokenInformation(token, 18, ctypes.byref(etype),
                                           ctypes.sizeof(etype),
                                           ctypes.byref(out_len)):
                raise OSError(f"GetTokenInformation 失败 pid={pid}")
            return {1: "default", 2: "full", 3: "limited"}.get(
                etype.value, "default")
        finally:
            k32.CloseHandle(token)
    finally:
        k32.CloseHandle(h)


def _self_elevation() -> str:
    """本进程提权级别（同上语义）。"""
    import ctypes
    return _elevation_of_process(ctypes.windll.kernel32.GetCurrentProcessId())


def _pid_of_hwnd(hwnd: int) -> int | None:
    import ctypes
    from ctypes import wintypes
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _truncate_show(text: str, limit: int) -> str:
    """展示截断:压缩空白,≤limit 字;超出以 … 结尾并标注总长。"""
    t = " ".join(str(text).split())
    if len(t) <= limit:
        return t
    return f"{t[:limit]}…(共 {len(t)} 字)"


class Enforcement:
    """四道闸裁决器。"""

    def __init__(self, policy: Policy, bindings: BindingManager,
                 approvals: ApprovalManager, estop: EstopMonitor,
                 executor: Executor, audit_log: AuditLogger,
                 whitelist_admin: WhitelistAdmin | None = None):
        self._policy = policy
        self._bindings = bindings
        self._approvals = approvals
        self._estop = estop
        self._executor = executor
        self._audit = audit_log
        # ISS-0012 §6：运行期白名单视图（静态∪会话）；缺省内存态兼容装配
        self._admin = whitelist_admin or WhitelistAdmin(None, policy.whitelist)

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

        # 闸二 应用白名单（INV-2；ISS-0012 A：未命中 → 本地审批入白三态）
        if tool == "launch_app":
            proc = str(request.params.get("app", "")).strip().lower()
            # 路径归一：允许按完整路径启动（取进程基名比对白名单）
            proc = proc.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        else:
            proc = target_proc
        cap = self._admin.cap_of(proc) if proc else None
        if cap is None and proc in self._policy.terminal_apps:
            cap = L3            # 终端类成员资格满足闸二（attach 已经 L3 审批）；
            if tool == "launch_app":
                eff = L3        # launch 终端维持升 L3 逐次审批（禁永久入白终端）
        if cap is None and proc and proc in NEVER_ENROLL:
            # 自保护铁律（ISS-0012 约束）：本服务进程永不可入白、不走审批
            return self._deny(request, eff, NOT_WHITELISTED,
                              f"目标进程 {proc} 未经本地授权"
                              f"（该进程受系统保护，不可加入白名单）", t0)
        if cap is None and proc:
            # 审批入白：人类三态裁决（本次允许=会话 / 永久加入=落盘 / 拒绝）
            fp = compute_fingerprint(tool, self._fingerprint_params(request))
            desc = self._describe_enroll(request, binding, proc)
            decision = self._approvals.request_enroll(
                proc, desc, fp, image_path=self._capture_target(binding),
                target_rect=binding.window_rect if binding else None)
            if decision == "approve_always":
                self._admin.add_permanent(proc, L2)
                cap = L2
            elif decision == "approve":
                self._admin.add_session(proc, L2)
                cap = L2
            else:
                code = APPROVAL_TIMEOUT if decision == "timeout" \
                    else APPROVAL_DENIED
                guidance = ("入白审批超时：人类未在时限内裁决，请留意本地审批"
                            "弹窗后重新发起" if decision == "timeout" else
                            "非白名单进程未获人类授权")
                return self._deny(request, eff, code, f"{guidance}：{proc}", t0)
        if cap is None:
            return self._deny(request, eff, NOT_WHITELISTED,
                              "目标进程未经本地授权", t0)
        if _LEVEL_ORDER[eff] > _LEVEL_ORDER[cap]:
            return self._deny(request, eff, POLICY_VIOLATION,
                              f"操作级别 {eff} 超出该进程白名单条目上限 {cap}", t0)

        # ISS-0017 B：写前提权边界（fail-closed）——目标提权高于自身显式拒绝
        if binding is not None:
            pid = _pid_of_hwnd(binding.hwnd)
            if pid:
                try:
                    target_lvl = _elevation_of_process(pid)
                except OSError:
                    return self._deny(
                        request, eff, ELEVATION_REQUIRED,
                        f"目标进程 {target_proc} 提权级别不可检测"
                        f"（fail-closed 拒绝）", t0)
                if target_lvl == "full" and _self_elevation() != "full":
                    return self._deny(
                        request, eff, ELEVATION_REQUIRED,
                        f"目标进程 {target_proc} 以管理员身份运行，"
                        f"请以管理员身份重启 daemon 后再操作", t0)

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
            # ISS-0019：批量授权——同窗口同工具会话内后续同类免批
            # （终端类与 key 类永不适用）
            excluded = (tool == "key") or (
                binding is not None
                and binding.process_name in self._policy.terminal_apps)
            if (binding is not None and not excluded
                    and self._approvals.session_scope_of(tool, binding.token)
                    == "window_session"):
                pass                              # 批量命中：不弹窗直接放行
            else:
                fp = compute_fingerprint(tool, self._fingerprint_params(request))
                desc = self._describe(request, binding)
                image_path = self._capture_target(binding, request)
                # ISS-0007 B：审批弹窗按目标窗口所在屏落位
                target_rect = binding.window_rect if binding else None
                decision = self._approvals.request_approval(
                    desc, fp, image_path=image_path,
                    target_rect=target_rect,
                    tool=tool,
                    binding_token=binding.token if binding else None,
                    allow_scope=not excluded)
                if decision not in ("approve", "approve_session"):
                    code = APPROVAL_TIMEOUT if decision == "timeout" \
                        else APPROVAL_DENIED
                    guidance = ("审批超时：人类未在时限内裁决，请留意本地审批弹窗后"
                                "重新发起" if decision == "timeout" else
                                "受控操作未获人类批准")
                    return self._deny(request, eff, code,
                                      f"{guidance}：{desc}", t0)
                self._approvals.verify_and_consume(fp)  # 即验即销（服务内部闭环）
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

    def _capture_target(self, binding: BindingRecord | None,
                        request: OperationRequest | None = None) -> str | None:
        """闸四配套：实拍目标窗口供审批弹窗展示。

        ISS-0020 C：无绑定时按请求目标进程反查窗口实拍;反查不到退化全屏
        （底注标注来源）。ISS-0020 D：取图失败写审计事件"审批取图失败"
        （不再静默）；失败不阻断审批流。
        """
        self._capture_note = ""
        try:
            if binding is not None:
                return self._executor.capture_approval_shot(binding.window_rect)
            # 无绑定:按请求目标进程反查窗口(取可见且矩形在屏上的候选)
            proc = str(request.params.get("process", "")) if request else ""
            if proc:
                cands = [w for w in self._executor.find_windows(process=proc)
                         if w.get("visible", True)
                         and (w["rect"][2] - w["rect"][0]) > 50
                         and (w["rect"][3] - w["rect"][1]) > 50
                         and w["rect"][2] > 0 and w["rect"][3] > 0]
                if cands:
                    self._capture_note = f"（实拍来源：目标进程 {proc}）"
                    return self._executor.capture_approval_shot(
                        tuple(cands[0]["rect"]))
            # 反查不到:退化全屏上下文
            from .monitors import enum_monitors
            l, t, r, b = enum_monitors()[0]["rect"]
            self._capture_note = "（实拍来源：全屏上下文，无目标窗口）"
            return self._executor.capture_approval_shot((l, t, r, b))
        except Exception as e:
            try:
                self._audit.record_event("审批取图失败", str(e))
            except Exception:
                pass
            return None

    def _describe(self, request: OperationRequest,
                  binding: BindingRecord | None) -> str:
        """两段式描述:人话标题行 + 「---」分隔 + 技术底注(进程/句柄保留)。

        ISS-0020 A：内容型操作主标题直接带内容(截断展示,不改操作语义);
        B：底注参数上限 500 字并标注总长;C：附实拍来源说明。
        """
        tech_target = ""
        if binding is not None:
            title = self._live_title(binding)
            plain_target = (f"「{title}」" if title
                            else f"进程 {binding.process_name} 的窗口")
            tech_target = (f"进程 {binding.process_name} 的窗口"
                           f"（句柄 {binding.hwnd}）")
        else:
            # ISS-0012 F：launch 无绑定窗口，plain_target 用显示名（裸进程名不可读）
            from .appnames import app_display_name
            app_raw = str(request.params.get("app", ""))
            proc = app_raw.strip().lower().rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            plain_target = app_display_name(proc)
            tech_target = f"应用 {app_raw}"

        if request.tool == "key":
            key = normalize_key(str(request.params.get("key", "")))
            action = self._KEY_ACTIONS.get(key, f"按下 {key}")
            headline = f"{action}{plain_target}" if binding else f"{action}"
            tech = f"按键 {key} 作用于{tech_target}"
        elif request.tool == "attach":
            # ISS-0020 补:attach 主标题带目标窗口(不再"执行 attach"空泛)
            from .appnames import app_display_name
            att_title = str(request.params.get("title", "") or "")
            att_proc = str(request.params.get("process", "") or "")
            att_target = (f"「{att_title}」" if att_title
                          else app_display_name(att_proc) if att_proc
                          else f"句柄 {request.params.get('hwnd')}")
            headline = f"绑定窗口 {att_target}"
            tech = (f"attach（参数 {_truncate_show(self._digest(request), 500)}）"
                    f"作用于{tech_target or '目标窗口'}")
        elif request.tool == "launch_app":
            headline = f"启动应用 {plain_target}"
            tech = f"launch_app 作用于{tech_target}"
        elif request.tool in ("type_text", "type_element", "set_clipboard"):
            # ISS-0020 A：内容进主标题（≤60 字截断+总长标注）
            action = self._TOOL_ACTIONS.get(request.tool,
                                            f"执行 {request.tool}")
            text = str(request.params.get("text", ""))
            headline = f"{action}「{_truncate_show(text, 60)}」{plain_target}"
            tech = f"{request.tool}（参数 {_truncate_show(self._digest(request), 500)}）作用于{tech_target}"
        elif request.tool == "click":
            x, y = request.params.get("x"), request.params.get("y")
            headline = f"鼠标点击 ({x}, {y}){plain_target}"
            tech = f"click（参数 {_truncate_show(self._digest(request), 500)}）作用于{tech_target}"
        elif request.tool == "drag":
            s, e = request.params.get("start"), request.params.get("end")
            headline = f"鼠标拖拽 ({s[0]}, {s[1]})→({e[0]}, {e[1]}){plain_target}"
            tech = f"drag（参数 {_truncate_show(self._digest(request), 500)}）作用于{tech_target}"
        else:
            action = self._TOOL_ACTIONS.get(request.tool, f"执行 {request.tool}")
            headline = f"{action}{plain_target}"
            tech = f"{request.tool}（参数 {_truncate_show(self._digest(request), 500)}）作用于{tech_target}"
        note = getattr(self, "_capture_note", "")
        return f"{headline}\n---\n{tech}{note}"

    def _describe_enroll(self, request: OperationRequest,
                         binding: BindingRecord | None, proc: str) -> str:
        """入白审批描述（ISS-0012 A+F）：主标题显示名，底注进程名+三态含义。

        F 补丁：显示名三级解析——attach 用窗口实况标题、launch 读版本信息
        FileDescription、全失败回退进程名（"我都不知道这是个啥软件"教训）。
        """
        from .appnames import app_display_name
        title = self._live_title(binding) if binding is not None else ""
        display = app_display_name(proc, title)
        if title:
            src = "窗口标题"
        elif display != proc:
            src = "版本信息"
        else:
            src = "进程名"
        headline = f"AI 请求操作新应用「{display}」"
        tech = (f"进程 {proc}（显示名来源：{src}）当前未经本地授权"
                f"（请求动作 {request.tool}）。"
                f"本次会话允许 = 重启前有效（会话级，不落盘）；"
                f"永久加入 = 写入白名单长期有效，可随时在白名单管理中移出")
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
