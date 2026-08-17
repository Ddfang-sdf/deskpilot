"""MCP 协议层程序（详细设计 §4）。

只做协议翻译与参数规整：零业务逻辑、零安全判断、零直通后门（INV-8）。
本文件包含 22 个工具的参数模式声明与 validate_call 规整入口；
stdio 服务循环留待后续迭代。
"""

from __future__ import annotations

from typing import Any, Mapping

from .errors import InvalidParamsError  # noqa: F401  （供调用方捕获）
from .models import Policy

# 参数类型标签：str / int / num / coord / rect / text / any
# text 受 policy.limits.input_max_chars 长度约束；coord/rect 为坐标结构。
TOOL_SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    # ---- L0 感知类（详细设计 §12.4）----
    "screenshot": {
        "required": {"scope": ("enum", ["fullscreen", "region", "window"])},
        "optional": {"rect": ("rect",), "window": ("any",)},
        "conditional": {"region": ["rect"], "window": ["window"]},
    },
    "ocr": {"required": {"source": ("any",)}, "optional": {}},
    "find_window": {
        "required": {},
        "optional": {"title": ("str",), "process": ("str",)},
        "at_least_one": ["title", "process"],
    },
    "get_ui_tree": {"required": {"window": ("any",)}, "optional": {}},
    "get_clickable_map": {"required": {"window": ("any",)}, "optional": {}},
    "template_match": {
        "required": {"template": ("str",), "scope": ("rect",)},
        "optional": {"threshold": ("num",)},
    },
    "get_cursor": {"required": {}, "optional": {}},
    "get_clipboard": {"required": {}, "optional": {}},
    # ---- L1 控制类（详细设计 §13.4）----
    "wait_for_window": {
        "required": {"target": ("str",)},
        "optional": {"timeout": ("num",)},
    },
    "wait_for_element": {
        "required": {"token": ("str",)},
        "optional": {"name": ("str",), "automation_id": ("str",), "timeout": ("num",)},
        "at_least_one": ["name", "automation_id"],
    },
    "move": {"required": {"x": ("int",), "y": ("int",)}, "optional": {}},
    "scroll": {
        "required": {"token": ("str",), "direction": ("enum", ["up", "down"]),
                     "amount": ("int",)},
        "optional": {},
    },
    "attach": {
        "required": {},
        "optional": {"title": ("str",), "hwnd": ("int",), "process": ("str",)},
        "at_least_one": ["title", "hwnd", "process"],
    },
    "detach": {"required": {"token": ("str",)}, "optional": {}},
    # ---- L2 写入类（详细设计 §14.4）----
    "launch_app": {"required": {"app": ("str",)}, "optional": {}},
    "activate_window": {"required": {"token": ("str",)}, "optional": {}},
    "click_element": {
        "required": {"token": ("str",)},
        "optional": {"name": ("str",), "automation_id": ("str",), "som_id": ("int",)},
        "at_least_one": ["name", "automation_id", "som_id"],
    },
    "type_element": {
        "required": {"token": ("str",), "text": ("text",)},
        "optional": {"name": ("str",), "automation_id": ("str",)},
        "at_least_one": ["name", "automation_id"],
    },
    "click": {"required": {"token": ("str",), "x": ("int",), "y": ("int",)},
              "optional": {}},
    "type_text": {"required": {"token": ("str",), "text": ("text",)}, "optional": {}},
    "key": {"required": {"token": ("str",), "key": ("str",)}, "optional": {}},
    "set_clipboard": {"required": {"token": ("str",), "text": ("text",)}, "optional": {}},
    "drag": {"required": {"token": ("str",), "start": ("coord",), "end": ("coord",)},
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
            raise InvalidParamsError(
                f"参数 {name} 超长（{len(value)} > {policy.input_max_chars}）")
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

    server = Server("deskpilot")

    @server.list_tools()
    async def _list():
        return [
            types.Tool(
                name=name,
                description=f"DeskPilot 桌面操作工具 {name}（级别 {TOOL_LEVELS[name]}）",
                inputSchema=_input_schema(schema),
            )
            for name, schema in TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict | None):
        raw = arguments or {}
        if backend == "http":
            result_dict = remote_call(name, raw, daemon_url)
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
