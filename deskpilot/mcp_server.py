"""MCP 协议层程序（详细设计 §4）。

只做协议翻译与参数规整：零业务逻辑、零安全判断、零直通后门（INV-8）。
本文件包含 22 个工具的参数模式声明与 validate_call 规整入口；
stdio 服务循环留待后续迭代。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Mapping

from .enforcement import _truncate_show     # ISS-0027：参数回显截断复用
from .errors import InvalidParamsError  # noqa: F401  （供调用方捕获）
from .httpd import client_timeout           # ISS-0033 A2：客户端超时由策略推导
from .models import Policy

# 参数类型标签：str / int / num / coord / rect / text / any
# text 受 policy.limits.input_max_chars 长度约束；coord/rect 为坐标结构。


async def call_with_progress(work: Awaitable, report: Callable[[], None],
                             interval_s: float,
                             clock: Callable[[], float] = time.monotonic) -> Any:
    """ISS-0009 §6：周期触发进度回调直到 work 完成；返回 work 结果。

    work 为协程/Future；每 interval_s 未完成即调用 report() 一次；
    work 抛异常原样透出且进度停止。用于 stdio 服务在长调用（L3 同步审批等）
    期间向客户端发 MCP progress notifications。
    """
    task = asyncio.ensure_future(work)
    try:
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(task), interval_s)
            except asyncio.TimeoutError:
                if task.done():
                    return task.result()
                report()
    finally:
        if not task.done():
            task.cancel()
TOOL_SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    # ---- L0 感知类（详细设计 §12.4）----
    "screenshot": {
        "description": "拍 Windows 真实桌面/应用窗口的图像,返回可供多模态模型直接查看的图像内容;浏览器页面请用浏览器工具(它的网页视口截图不是桌面)。scope:fullscreen=整个虚拟桌面(多屏含负坐标)、window=绑定窗口、region=rect 矩形。另返回图像路径+宽高+coord_space+monitors 屏列表。",
        "required": {"scope": ("enum", ["fullscreen", "region", "window"])},
        "optional": {"rect": ("rect",), "window": ("any",)},
        "conditional": {"region": ["rect"], "window": ["window"]},
    },
    "ocr": {
        "description": "识别 Windows 桌面/窗口图像中的文字(OCR):要精确文字清单或文字定位时用我;布局理解请直接查看 screenshot 返回的图像(多模态可见)。浏览器网页文字请用浏览器工具读 DOM。source=图像路径或 screen,返回 [{text, position}],可直接配 attach 使用。",
        "required": {"source": ("any",)}, "optional": {}},
    "find_window": {
        "description": "查找 Windows 桌面上的应用窗口(按标题/进程名),返回 hwnd/标题/进程/矩形;网页定位请用浏览器工具。操作任何应用前先调用它定位,再 attach 绑定、get_ui_tree 看内容。不要为此写临时脚本(uiautomation/mss)——窗口枚举已封装。",
        "required": {},
        "optional": {"title": ("str",), "process": ("str",)},
        "at_least_one": ["title", "process"],
    },
    "get_ui_tree": {
        "description": "读取绑定的 Windows 窗口的界面元素树(UIA):每个可交互控件的名称/类型/矩形;网页元素请用浏览器工具。attach 绑定之后用它「看懂」窗口里有哪些按钮、输入框、列表。返回 elements+coord_space。",
        "required": {"window": ("any",)}, "optional": {}},
    "get_clickable_map": {
        "description": "给绑定的 Windows 窗口做 SoM 标注截图:把可点击元素编号画在图上。需要「指第 N 号元素」点击时用,编号传入 click_element 的 som_id 即可点中。",
        "required": {"window": ("any",)}, "optional": {}},
    "template_match": {
        "description": "在 Windows 屏幕或窗口里按模板小图找位置(图像匹配);UIA 读不出的自绘界面(游戏/老软件/画布)时用。template=模板图路径,scope=搜索范围,返回命中坐标。",
        "required": {"template": ("str",), "scope": ("rect",)},
        "optional": {"threshold": ("num",)},
    },
    "get_cursor": {
        "description": "返回 Windows 桌面鼠标当前坐标(虚拟桌面坐标系,可含负值)。无参数,返回 {x, y}。",
        "required": {}, "optional": {}},
    "get_clipboard": {
        "description": "读取 Windows 桌面当前剪贴板文本。无参数,返回 {text}。"
        "写入剪贴板用 set_clipboard(需 attach 绑定)。",
        "required": {}, "optional": {}},
    # ---- L1 控制类（详细设计 §13.4）----
    "wait_for_window": {
        "description": "等待某个 Windows 窗口出现或消失;launch_app 启动应用后等它就位再用。target=标题/进程,timeout 秒,返回命中信息。",
        "required": {"target": ("str",)},
        "optional": {"timeout": ("num",)},
    },
    "wait_for_element": {
        "description": "等待绑定的 Windows 窗口内某个元素出现(轮询)。attach 绑定后,界面加载慢时先等它再 click_element。token+name/automation_id+timeout。",
        "required": {"token": ("str",)},
        "optional": {"name": ("str",), "automation_id": ("str",), "timeout": ("num",)},
        "at_least_one": ["name", "automation_id"],
    },
    "move": {
        "description": "移动 Windows 桌面鼠标到指定坐标(不点击,虚拟桌面坐标系)。x,y 整数。",
        "required": {"x": ("int",), "y": ("int",)}, "optional": {}},
    "scroll": {
        "description": "在绑定的 Windows 窗口滚动鼠标滚轮。attach 绑定后使用。direction(up/down)+amount(格数)。",
        "required": {"token": ("str",), "direction": ("enum", ["up", "down"]),
                     "amount": ("int",)},
        "optional": {},
    },
    "attach": {
        "description": "绑定一个 Windows 原生应用窗口——一切写操作(点击/输入/按键)的前提,返回操作令牌 token;浏览器页面交互请用浏览器工具。按 title/hwnd/process 定位(先 find_window 找到 hwnd 最稳)。绑定后链路:get_ui_tree 看内容→click_element/type_element 操作→detach 解绑。",
        "required": {},
        "optional": {"title": ("str",), "hwnd": ("int",), "process": ("str",)},
        "at_least_one": ["title", "hwnd", "process"],
    },
    "detach": {
        "description": "解绑 Windows 窗口,操作令牌 token 立即失效。操作完一个应用后调用。token=attach 返回值。",
        "required": {"token": ("str",)}, "optional": {}},
    # ISS-0012 §6 E3：AI 请求撤回白名单（人类弹窗裁决后才执行）
    "request_remove_from_whitelist": {
        "description": "申请把某进程移出桌面应用白名单:弹本地确认窗,"
        "人类点[移出]才执行(特权收缩,安全向)。用户说「以后别操作 XX 了」"
        "时调用。process=进程名,返回 {removed}。",
        "required": {"process": ("str",)}, "optional": {},
    },
    # ---- L2 写入类（详细设计 §14.4）----
    "launch_app": {
        "description": "启动一个 Windows 桌面应用(白名单内直接启动;非白名单"
        "弹本地入白审批,人类三选)。app=进程名或完整路径。"
        "启动后用 wait_for_window 等位再 attach。",
        "required": {"app": ("str",)}, "optional": {}},
    "activate_window": {
        "description": "把绑定的 Windows 窗口置前台(多数写操作要求窗口在前台)。token=attach 返回令牌。",
        "required": {"token": ("str",)}, "optional": {}},
    "click_element": {
        "description": "按名称/AutomationId/SoM 编号点击绑定的 Windows 窗口内控件(UIA 优先,比像素坐标稳);网页元素点击请用浏览器工具。attach 绑定后,先 get_ui_tree 找控件名,再点它。token+name/automation_id/som_id。",
        "required": {"token": ("str",)},
        "optional": {"name": ("str",), "automation_id": ("str",), "som_id": ("int",)},
        "at_least_one": ["name", "automation_id", "som_id"],
    },
    "type_element": {
        "description": "向绑定的 Windows 窗口内控件(输入框等)输入文本;网页表单请用浏览器工具。attach 绑定后使用。token+name/automation_id+text。",
        "required": {"token": ("str",), "text": ("text",)},
        "optional": {"name": ("str",), "automation_id": ("str",)},
        "at_least_one": ["name", "automation_id"],
    },
    "click": {
        "description": "按 Windows 虚拟桌面坐标像素点击(元素不可用时的兜底;能用 click_element 就别用它)。token+x+y。",
        "required": {"token": ("str",), "x": ("int",), "y": ("int",)},
              "optional": {}},
    "click_text": {
        "description": "在绑定的 Windows 窗口内按文字点击(OCR 定位;能用文字定位就不要手算坐标,优先于裸坐标 click)。token+text;match=contains/exact;多命中默认不放行,用 index 指定第几个(从 0);button=left/right。",
        "required": {"token": ("str",), "text": ("str",)},
        "optional": {"match": ("str",), "index": ("int",),
                     "button": ("str",)}},
    "type_text": {
        "description": "经剪贴板向 Windows 窗口当前焦点输入文本(支持中文,带读回校验;不会预清空目标区域)。token+text。",
        "required": {"token": ("str",), "text": ("text",)}, "optional": {}},
    "key": {
        "description": "向绑定的 Windows 窗口发送按键/组合键(受按键许可表管控;delete/alt+f4 等危险键弹本地审批)。token+key,如 enter、ctrl+s、alt+f4。未收录键返回 KEY_UNKNOWN 并列出现行可用键;拒绝时不发送任何按键。",
        "required": {"token": ("str",), "key": ("str",)}, "optional": {}},
    "set_clipboard": {
        "description": "改写 Windows 桌面剪贴板内容。attach 绑定后使用。"
        "token+text。读取用 get_clipboard(无需绑定)。",
        "required": {"token": ("str",), "text": ("text",)}, "optional": {}},
    "drag": {
        "description": "在 Windows 桌面拖拽鼠标(起点→终点,虚拟桌面坐标系)。token+start/end(各 [x,y])。",
        "required": {"token": ("str",), "start": ("coord",), "end": ("coord",)},
             "optional": {}},
}


def _check_type(name: str, value: Any, spec: tuple, policy: Policy) -> None:
    typ = spec[0]
    if typ == "any":
        return
    if typ == "str" or typ == "text":
        if not isinstance(value, str):
            raise InvalidParamsError(f"参数 {name} 必须为字符串")
        if typ == "text" and len(value) > policy.input_max_chars:
            # ISS-0027 A：回显服务端实际收到的值(AI 对比发送/接收诊断传输故障)
            raise InvalidParamsError(
                f"参数 {name} 超长（{len(value)} > {policy.input_max_chars}）"
                f"。收到: {_truncate_show(value, 60)}")
        return
    if typ == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidParamsError(f"参数 {name} 必须为整数")
        return
    if typ == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidParamsError(f"参数 {name} 必须为数值")
        return
    if typ == "enum":
        if value not in spec[1]:
            raise InvalidParamsError(f"参数 {name} 取值越界: {value!r}")
        return
    if typ in ("coord", "rect"):
        want = 2 if typ == "coord" else 4
        if (not isinstance(value, (list, tuple)) or len(value) != want
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       for v in value)):
            raise InvalidParamsError(f"参数 {name} 必须为 {want} 元数值坐标")
        return
    raise InvalidParamsError(f"参数 {name} 模式声明非法: {typ}")


def validate_call(tool: str, raw_params: Mapping[str, Any], policy: Policy) -> dict:
    """参数规整（详细设计 §4.6）：必填 / 类型 / 枚举 / 条件必填 / 至少其一 / 文本长度。

    通过返回规整后的参数副本；失败抛 InvalidParamsError（INVALID_PARAMS）。
    未在模式中声明的额外参数原样透传——它们参与操作指纹但不进入任何判定
    （自报授权类参数无效，见测试设计 TC-S-TOK-06）。
    """
    schema = TOOL_SCHEMAS.get(tool)
    if schema is None:
        raise InvalidParamsError(f"未知工具: {tool}")
    if not isinstance(raw_params, Mapping):
        raise InvalidParamsError("参数必须为映射")

    params = dict(raw_params)

    for name in schema["required"]:
        if name not in params:
            raise InvalidParamsError(f"缺少必填参数: {name}")

    if "at_least_one" in schema:
        group = schema["at_least_one"]
        if not any(name in params for name in group):
            raise InvalidParamsError(f"参数 {'/'.join(group)} 至少提供一个")

    if "conditional" in schema:
        for name in schema["conditional"].get(params.get("scope"), []):
            if name not in params:
                raise InvalidParamsError(f"scope={params.get('scope')} 时缺少参数: {name}")

    declared = {**schema["required"], **schema["optional"]}
    for name, value in params.items():
        spec = declared.get(name)
        if spec is not None:
            _check_type(name, value, spec, policy)

    return params


def _input_schema(schema: Mapping[str, Any]) -> dict:
    """把内部参数模式转换为 MCP inputSchema。"""
    type_map = {"str": {"type": "string"}, "text": {"type": "string"},
                "int": {"type": "integer"}, "num": {"type": "number"},
                "any": {}, "enum": {"type": "string"},
                "coord": {"type": "array", "items": {"type": "number"}},
                "rect": {"type": "array", "items": {"type": "number"}}}
    props: dict[str, Any] = {}
    for group in ("required", "optional"):
        for name, spec in schema[group].items():
            props[name] = dict(type_map[spec[0]])
            if spec[0] == "enum":
                props[name]["enum"] = spec[1]
    return {"type": "object", "properties": props,
            "required": list(schema["required"].keys())}


def build_server(ctx, backend: str = "local", daemon_url: str = ""):
    """装配 MCP Server（list_tools / call_tool）。

    backend="http" 时为瘦代理：工具调用转发常驻服务
    （ISS-0001），本进程不再持有工具状态；本地直跑为兼容回退。
    """
    import base64
    import json
    from pathlib import Path

    import mcp.types as types
    from mcp.server import Server

    from . import tools as tools_layer
    from .httpd import remote_call
    from .models import TOOL_LEVELS

    server = Server("deskpilot", instructions=(
        "本服务操作 Windows 桌面与原生应用窗口(截图/元素树/键鼠);"
        "浏览器标签页、网页、DOM 元素的任务请使用浏览器专用工具,"
        "勿用本服务(本服务截不到网页,只能截真实桌面)。"))

    @server.list_tools()
    async def _list():
        return [
            types.Tool(
                name=name,
                # ISS-0015：意图化描述注册为一等字段（告别模板废话）
                description=schema["description"],
                inputSchema=_input_schema(schema),
            )
            for name, schema in TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict | None):
        raw = arguments or {}

        def _progress_reporter() -> None:
            """ISS-0009 §6 A：向客户端发 MCP 进度通知（须客户端携带
            progressToken 才有协议意义，否则安全空转）。"""
            try:
                rc = server.request_context
            except LookupError:
                return
            try:
                req = getattr(rc, "request", None)
                meta = getattr(getattr(req, "params", None), "meta", None)
                token = getattr(meta, "progressToken", None) if meta else None
                session = getattr(rc, "session", None)
                if session is not None and token is not None:
                    asyncio.ensure_future(
                        session.send_progress_notification(
                            token, 0.0, message="处理中（等待人类裁决）"))
            except Exception:
                pass

        if backend == "http":
            # ISS-0009 §6 A：长调用（L3 同步审批等）期间周期发进度通知，
            # 协议兼容客户端收到进度会重置执行超时
            # ISS-0033 A2：超时由策略推导(禁魔法 90)
            result_dict = await call_with_progress(
                asyncio.to_thread(remote_call, name, raw, daemon_url,
                                  client_timeout(ctx.policy)),
                _progress_reporter, interval_s=5.0)
            payload = json.dumps(result_dict, ensure_ascii=False, default=str)
            contents: list = [types.TextContent(type="text", text=payload)]
            data = result_dict.get("data") or {}
            if name == "screenshot" and result_dict.get("ok") and data.get("path"):
                try:
                    b64 = base64.b64encode(
                        Path(data["path"]).read_bytes()).decode()
                    contents.append(types.ImageContent(type="image", data=b64,
                                                       mimeType="image/png"))
                except OSError:
                    pass
            return contents
        if name == "attach":
            result = tools_layer.attach(ctx, title=raw.get("title"),
                                        hwnd=raw.get("hwnd"),
                                        process=raw.get("process"))
        elif name == "detach":
            result = tools_layer.detach(ctx, token=raw.get("token", ""))
        else:
            result = tools_layer.call_tool(ctx, name, raw)
        payload = json.dumps(
            {"ok": result.ok, "error_code": result.error_code,
             "message": result.message, "data": result.data},
            ensure_ascii=False, default=str)
        contents: list = [types.TextContent(type="text", text=payload)]
        if name == "screenshot" and result.ok and result.data and result.data.get("path"):
            try:
                b64 = base64.b64encode(
                    Path(result.data["path"]).read_bytes()).decode()
                contents.append(types.ImageContent(type="image", data=b64,
                                                   mimeType="image/png"))
            except OSError:
                pass
        return contents

    return server


def serve(ctx, backend: str = "auto", daemon_url: str = "") -> None:
    """MCP stdio 服务循环：阻塞至 stdio 关闭。

    backend="auto"（默认）启动时探测常驻服务：在线则本进程为瘦代理，
    不在线则本地直跑（兼容回退，ISS-0001）。"""
    import asyncio
    import os

    from mcp.server.stdio import stdio_server

    from .httpd import DEFAULT_HOST, DEFAULT_PORT, probe_daemon

    if backend == "auto":
        if not daemon_url:
            host = os.environ.get("DESKPILOT_DAEMON_HOST", DEFAULT_HOST)
            port = int(os.environ.get("DESKPILOT_DAEMON_PORT", DEFAULT_PORT))
            daemon_url = f"http://{host}:{port}"
        backend = "http" if probe_daemon(host, port) else "local"

    server = build_server(ctx, backend=backend, daemon_url=daemon_url)

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())
