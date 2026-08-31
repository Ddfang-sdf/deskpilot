"""工具层（详细设计 §12–§14）。

每个工具为公开入口函数。路由：
- L0 只读工具 → 执行层只读面（不经强制层），写审计轻量记录；
- L1 无绑定工具（move / wait_for_window）→ 执行层直调；
- 需绑定工具与 L2 写工具 → 强制层四道闸；
- attach / detach → 解析目标 → 强制层过闸 → 绑定表动作（不落执行层）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ..enforcement import Enforcement
from ..errors import (AMBIGUOUS_TARGET, INTERNAL_ERROR, TARGET_NOT_FOUND,
                      ExecutorError, InvalidParamsError)
from ..mcp_server import validate_call
from ..models import (BINDING_REQUIRED_TOOLS, L2, TOOL_LEVELS, AuditEntry,
                      OperationRequest, Policy, ToolResult)

_L0_DIRECT = {"screenshot", "find_window", "get_ui_tree", "get_cursor",
              "get_clipboard", "ocr", "template_match", "get_clickable_map"}
_L1_DIRECT = {"move", "wait_for_window"}


@dataclass(frozen=True)
class ToolContext:
    """工具调用上下文（依赖装配）。L0/L1 与 attach 路径需要后三个依赖。"""

    policy: Policy
    enforcement: Enforcement
    bindings: Any = None
    executor: Any = None
    audit: Any = None
    whitelist_admin: Any = None     # ISS-0012 E2/E3：白名单运行期管理
    revoke_channel: Any = None      # ISS-0012 E3：AI 请求撤回的人类确认通道


def call_tool(ctx: ToolContext, tool: str, raw_params: Mapping[str, Any]) -> ToolResult:
    """工具统一调度：规整 → 按级别路由 → 包装结果。"""
    try:
        params = validate_call(tool, raw_params, ctx.policy)
    except InvalidParamsError as e:
        return ToolResult(ok=False, error_code=e.code, message=e.message)

    if tool == "attach":
        return attach(ctx, title=params.get("title"), hwnd=params.get("hwnd"),
                      process=params.get("process"))
    if tool == "detach":
        return detach(ctx, token=params.get("token", ""))
    if tool == "request_remove_from_whitelist":
        return request_remove_from_whitelist(ctx, process=params["process"])

    if tool in _L0_DIRECT or tool in _L1_DIRECT:
        return _run_sensing(ctx, tool, params)

    token = params.pop("token", None)
    decision = ctx.enforcement.submit(
        OperationRequest(tool=tool, params=params, binding_token=token))
    return ToolResult(ok=decision.allowed, error_code=decision.reason_code,
                      message=decision.message, data=decision.data)


def _run_sensing(ctx: ToolContext, tool: str, params: dict) -> ToolResult:
    """L0/L1 直调路径：执行层只读/低风险调用 + 审计轻量记录。"""
    t0 = time.monotonic()
    try:
        if tool == "screenshot":
            result = ctx.executor.screenshot(params["scope"], params.get("rect"),
                                             params.get("window"))
        elif tool == "find_window":
            result = {"windows": ctx.executor.find_windows(
                title=params.get("title"), process=params.get("process"))}
        elif tool == "get_ui_tree":
            result = ctx.executor.get_ui_tree(params["window"])
        elif tool == "get_cursor":
            result = ctx.executor.get_cursor()
        elif tool == "get_clipboard":
            result = ctx.executor.get_clipboard()
        elif tool == "move":
            result = ctx.executor.move(params["x"], params["y"])
        elif tool == "wait_for_window":
            result = ctx.executor.wait_for_window(params["target"],
                                                  params.get("timeout"))
        elif tool == "ocr":
            result = ctx.executor.ocr(params["source"])
        elif tool == "template_match":
            result = ctx.executor.template_match(params["template"],
                                                 params["scope"],
                                                 params.get("threshold", 0.8))
        elif tool == "get_clickable_map":
            result = ctx.executor.get_clickable_map(params["window"])
        else:
            raise ExecutorError(INTERNAL_ERROR, f"工具 {tool} 未接线")
        _light_audit(ctx, tool, params, "ok", t0)
        return ToolResult(ok=True, error_code="", message="ok", data=result)
    except ExecutorError as e:
        _light_audit(ctx, tool, params, e.message, t0, reason=e.code)
        return ToolResult(ok=False, error_code=e.code, message=e.message)


def _light_audit(ctx: ToolContext, tool: str, params: dict, result: str,
                 t0: float, reason: str = "") -> None:
    """L0/L1 轻量记录（无截图证据）。"""
    if ctx.audit is None:
        return
    level = TOOL_LEVELS.get(tool, "L0")
    entry = AuditEntry(
        seq=0, timestamp=datetime.now().astimezone().isoformat(), tool=tool,
        params_digest=", ".join(f"{k}={v}" for k, v in params.items()),
        params_full="", level=level, decision="放行", reason_code=reason,
        result=result, duration_ms=int((time.monotonic() - t0) * 1000),
        before_shot="", after_shot="", binding_token="")
    try:
        ctx.audit.record(entry)
    except Exception:
        pass  # 轻量记录失败不阻断只读操作（写操作的两阶段强审计在强制层）


# ---- attach / detach（过闸 + 绑定表动作） ----

def attach(ctx: ToolContext, *, title: str | None = None, hwnd: int | None = None,
           process: str | None = None) -> ToolResult:
    raw = {k: v for k, v in {"title": title, "hwnd": hwnd, "process": process}.items()
           if v is not None}
    try:
        params = validate_call("attach", raw, ctx.policy)
    except InvalidParamsError as e:
        return ToolResult(ok=False, error_code=e.code, message=e.message)

    cands = ctx.executor.find_windows(title=params.get("title"),
                                      process=params.get("process"),
                                      hwnd=params.get("hwnd"))
    if not cands:
        return ToolResult(ok=False, error_code=TARGET_NOT_FOUND,
                          message="未找到目标窗口，可用 find_window 确认目标是否存在")
    if len(cands) > 1:
        return ToolResult(ok=False, error_code=AMBIGUOUS_TARGET,
                          message="目标窗口不唯一，请改用句柄指定",
                          data={"candidates": cands})

    w = cands[0]
    decision = ctx.enforcement.submit(
        OperationRequest(tool="attach", params={"process": w["process"]},
                         binding_token=None))
    if not decision.allowed:
        return ToolResult(ok=False, error_code=decision.reason_code,
                          message=decision.message)
    rec = ctx.bindings.create(w["hwnd"], w["process"], tuple(w["rect"]),
                              window_title=w.get("title", ""))
    return ToolResult(ok=True, error_code="", message="attach 成功",
                      data={"token": rec.token, "hwnd": rec.hwnd,
                            "process": rec.process_name, "rect": list(rec.window_rect)})


def detach(ctx: ToolContext, *, token: str) -> ToolResult:
    try:
        params = validate_call("detach", {"token": token}, ctx.policy)
    except InvalidParamsError as e:
        return ToolResult(ok=False, error_code=e.code, message=e.message)
    decision = ctx.enforcement.submit(
        OperationRequest(tool="detach", params={}, binding_token=params["token"]))
    if not decision.allowed:
        return ToolResult(ok=False, error_code=decision.reason_code,
                          message=decision.message)
    ctx.bindings.detach(params["token"])
    return ToolResult(ok=True, error_code="", message="已解绑")


# ---- ISS-0012 §6 E3：AI 请求撤回白名单 ----

def request_remove_from_whitelist(ctx: ToolContext, *, process: str) -> ToolResult:
    """AI 请求把进程移出白名单：人类在本地确认窗点[移出]才执行（特权收缩）。

    保留/超时/通道未装配一律 removed=False（不产生任何策略变更）。
    """
    t0 = time.monotonic()
    proc = str(process).strip().lower()
    admin = ctx.whitelist_admin
    channel = ctx.revoke_channel
    removed = False
    if admin is not None and channel is not None and proc:
        decision = channel.request(proc)
        if decision == "remove":
            removed = admin.remove(proc) is not None
            if removed and ctx.audit is not None:
                try:
                    ctx.audit.record_event("白名单移除-经AI请求", proc)
                except Exception:
                    pass
    result = {"removed": removed}
    _light_audit(ctx, "request_remove_from_whitelist",
                 {"process": proc}, f"removed={removed}", t0)
    return ToolResult(ok=True, error_code="", message="ok", data=result)


# ---- L2 写入类公开入口（M1）----

def type_text(ctx: ToolContext, *, token: str, text: str) -> ToolResult:
    return call_tool(ctx, "type_text", {"token": token, "text": text})


def key(ctx: ToolContext, *, token: str, key: str) -> ToolResult:
    return call_tool(ctx, "key", {"token": token, "key": key})


def click(ctx: ToolContext, *, token: str, x: int, y: int) -> ToolResult:
    return call_tool(ctx, "click", {"token": token, "x": x, "y": y})


def set_clipboard(ctx: ToolContext, *, token: str, text: str) -> ToolResult:
    return call_tool(ctx, "set_clipboard", {"token": token, "text": text})


def launch_app(ctx: ToolContext, *, app: str) -> ToolResult:
    return call_tool(ctx, "launch_app", {"app": app})


def scroll(ctx: ToolContext, *, token: str, direction: str, amount: int) -> ToolResult:
    return call_tool(ctx, "scroll", {"token": token, "direction": direction,
                                     "amount": amount})


def activate_window(ctx: ToolContext, *, token: str) -> ToolResult:
    return call_tool(ctx, "activate_window", {"token": token})


def move(ctx: ToolContext, *, x: int, y: int) -> ToolResult:
    return call_tool(ctx, "move", {"x": x, "y": y})


def drag(ctx: ToolContext, *, token: str, start, end) -> ToolResult:
    return call_tool(ctx, "drag", {"token": token, "start": start, "end": end})
