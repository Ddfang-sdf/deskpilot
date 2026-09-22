"""MCP 协议层程序（详细设计 §4）。

只做协议翻译与参数规整：零业务逻辑、零安全判断、零直通后门（INV-8）。
本文件包含 22 个工具的参数模式声明与 validate_call 规整入口；
stdio 服务循环留待后续迭代。
"""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from .enforcement import _truncate_show     # ISS-0027：参数回显截断复用
from .errors import InvalidParamsError  # noqa: F401  （供调用方捕获）
from .httpd import client_timeout           # ISS-0033 A2：客户端超时由策略推导
from .models import Policy

# ISS-0089 方向A：客户端图像处理上限（Claude Code 发送前 resize,长边超
# 2000px 即整张拒收——Anthropic vision 文档:>20 图时上限 2000x2000;
# Claude Code #53170 未修复)。screenshot 内联图源头等比降采样阈值,
# 单源常量（是否 policy 可配留作后续,本单先常量避免扩面,单据 §5）。
INLINE_MAX_PX = 2000


def _downscale_inline(png_bytes: bytes,
                      max_px: int = INLINE_MAX_PX) -> tuple[bytes, float]:
    """screenshot 内联图源头等比降采样（ISS-0089 方向A）。

    契约（单据 §6.1）：入原 PNG 字节；长边 >max_px → 等比缩到长边 ≤max_px
    重编码 PNG，返回 (新字节, f=缩放比)；长边 ≤max_px → (原字节, 1.0)
    同一对象零重编码（零损失回归）。等比=整幅内容全保留,非裁剪;
    落盘原图不动（A2）。用项目既有依赖 PIL，不引新库（单据 §5）。
    """
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(png_bytes))
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= max_px:
        return png_bytes, 1.0
    f = max_px / long_edge
    new_size = (max(1, round(w * f)), max(1, round(h * f)))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    buf = BytesIO()
    resized.save(buf, format="PNG")
    return buf.getvalue(), f


def _screenshot_inline_b64(data: dict) -> str | None:
    """screenshot 内联装配（ISS-0089 A1/A3，http/local 两 backend 共用）：
    读 path 全分辨率字节 → _downscale_inline → base64；f<1 时同步
    data["scale_x"]=data["scale_y"]=f（坐标契约：虚拟坐标 = virtual_rect
    原点 + 内联像素 / scale）；path/virtual_rect 不动（A2 落盘保真）。

    注意：必须在 payload(json.dumps)之前调用,scale 改写才进文本载荷。
    读盘/解码失败返回 None（沿用原 OSError 容错语义：不内联不阻断）。
    """
    try:
        raw = Path(data["path"]).read_bytes()
        inline, f = _downscale_inline(raw)
        b64 = base64.b64encode(inline).decode()
    except OSError:
        return None
    if f < 1.0:
        data["scale_x"] = data["scale_y"] = f
    return b64

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
        # ISS-0089 A3 + ISS-0090 #5:降采样/scale/path 语义入描述
        # (受 ISS-0015 长度闸门 ≤200 + ISS-0037 sv06「图像不可见」子串约束)
        # ISS-0096:屏号语义入描述(0=主屏)——AI 不再靠猜
        # ISS-0102:path 落盘参数语义入描述(194/200;原文见单据 v0.4)
        "description": "拍 Windows 桌面/窗口图像,可查看;网页用浏览器工具。scope:fullscreen=虚拟桌面、screen=屏号(0=主屏)、window=绑定窗口、region=rect(精读/局部,含 coverage)。path=落盘路径(仅仓库/审计根)。长边>2000 等比缩:图坐标/scale 还原;返回 path 为原图。图像不可见改调 ocr;ocr:true 附文字清单。",
        "required": {"scope": ("enum", ["fullscreen", "screen", "region", "window"])},
        "optional": {"rect": ("rect",), "window": ("any",), "ocr": ("bool",),
                     "screen": ("int",),
                     # ISS-0102 §3.1(P1 空壳:纯声明;描述改写与透传属 P3)
                     "path": ("str",)},
        "conditional": {"region": ["rect"], "window": ["window"],
                        "screen": ["screen"]},
    },
    "ocr": {
        # ISS-0069 ②:描述收紧到真实形态(路径/[l,t,r,b] rect),剔除
        # 「屏幕区域」假形态;全屏/窗口图指向 screenshot(ocr:true)组合
        "description": "识别 Windows 桌面/窗口图像中的文字:要精确文字清单或定位时用我;布局理解看 screenshot 图像。source=图像路径或 [l,t,r,b] 区域 rect(全屏/窗口图请用 screenshot 的 ocr:true 同次附文字清单)。优先局部实拍或路径直读——全屏识别系统繁忙时可能超时,按指引 500ms 重试。",
        "required": {"source": ("any",)}, "optional": {}},
    "find_window": {
        # ISS-0065 ①:schema 补 hwnd(int) 与 probe 能力对齐(描述曾宣称
        # 可按 hwnd 查找却被 at_least_one 拦截——提示与声明面矛盾)
        "description": "查找 Windows 桌面上的应用窗口(按 title/process/hwnd 定位,至少给一项),返回 hwnd/标题/进程/矩形;网页定位请用浏览器工具。操作任何应用前先调用它定位,再 attach 绑定、get_ui_tree 看内容。不要写临时脚本(uiautomation/mss)——窗口枚举已封装。",
        "required": {},
        "optional": {"title": ("str",), "process": ("str",),
                     "hwnd": ("int",)},
        "at_least_one": ["title", "process", "hwnd"],
    },
    "get_ui_tree": {
        "description": "读取绑定的 Windows 窗口的界面元素树(UIA):每个可交互控件的名称/类型/矩形;网页元素请用浏览器工具。attach 绑定之后用它「看懂」窗口里有哪些按钮、输入框、列表。control_type=按控件类型过滤(如 CheckBox/Button/MenuItem,找无文字图形先用它)。返回 elements+coord_space。",
        "required": {"window": ("any",)}, "optional": {"control_type": ("str",)}},
    "get_clickable_map": {
        # ISS-0066 ②:UIA 条目 id 与 som_id 双写同值(输出/入参命名对齐),
        # id 标废弃日程;detect 编号仍不可寻址(只取 rect)
        "description": "给绑定的 Windows 窗口做 SoM 标注截图:可点击元素编号画在图上,UIA 条目同带 som_id 与 id(同值,id 已废弃)。detect=true 追加图形检测,覆盖 UIA 看不见的控件。source=uia 编号传 click_element 的 som_id 点中;source=detect 编号是图形区域,取其 rect 用 click 按坐标点。",
        "required": {"window": ("any",)},
        "optional": {"detect": ("bool",)}},
    "list_desktop_icons": {
        "description": "列出 Windows 桌面图标清单(无需绑定):display 显示名/source 路径(回收站等虚拟项为 null)/graphic_rect 图形矩形(拖拽抓点取中心)/cell_rect 单元矩形(槽位核验用),虚拟桌面坐标;栈叠图标各成一条。桌面定位/拖拽核验用;与 screenshot 的 ocr:true 分工:本工具给图标矩形,ocr 给文字。region=可选限定区域。",
        "required": {}, "optional": {"region": ("rect",)}},
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
        "description": "在绑定的 Windows 窗口滚动鼠标滚轮(垂直/水平)。attach 绑定后使用。direction(up/down/left/right)+amount(格数);left=负向,right=正向。",
        "required": {"token": ("str",), "direction": ("enum", ["up", "down", "left", "right"]),
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
        "description": "把绑定的 Windows 窗口置前台(多数写操作要求窗口在前台;最大化窗口保持最大化不被打回)。token=attach 返回令牌。窗口最大化/移动/缩放等几何变化后,既有截图与坐标即作废,请先重新感知再操作。",
        "required": {"token": ("str",)}, "optional": {}},
    "click_element": {
        # ISS-0091 整改④:拒绝语义入描述(退化矩形/遮挡);受 ISS-0015 描述
        # 长度闸门(≤200)约束,错误码全称由拒绝时的错误消息承载(附自愈指引)
        "description": "按名称/AutomationId/SoM 编号/控件类型点击绑定的 Windows 窗口内控件(UIA 优先);网页元素请用浏览器工具。先 get_ui_tree 找控件。无文字图形用 control_type+index;som_id 只点 UIA 编号,与 control_type 互斥;detect 编号取 rect 用 click。拒绝零鼠标动作:不可见/退化矩形/遮挡→错误码+自愈指引。",
        "required": {"token": ("str",)},
        "optional": {"name": ("str",), "automation_id": ("str",), "som_id": ("int",),
                     "control_type": ("str",), "index": ("int",)},
        "at_least_one": ["name", "automation_id", "som_id", "control_type"],
    },
    "type_element": {
        # ISS-0070:描述写明「name/automation_id 至少一项」(空手撞
        # INVALID_PARAMS 可自愈)
        "description": "向绑定的 Windows 窗口内控件(输入框等)输入文本;网页表单请用浏览器工具。attach 绑定后使用。token+text 必填,name/automation_id 至少一项作定位(空手调用将被 INVALID_PARAMS 拒绝)。",
        "required": {"token": ("str",), "text": ("text",)},
        "optional": {"name": ("str",), "automation_id": ("str",)},
        "at_least_one": ["name", "automation_id"],
    },
    "click": {
        "description": "按 Windows 虚拟桌面坐标像素点击(元素不可用时的兜底;能用 click_element 就别用它)。token+x+y;button=left/right/middle(默认 left),clicks=1/2/3(单/双/三连击,默认 1)。",
        "required": {"token": ("str",), "x": ("int",), "y": ("int",)},
              "optional": {"button": ("enum", ["left", "right", "middle"]),
                           "clicks": ("int",)}},
    "click_text": {
        "description": "在绑定的 Windows 窗口内按文字点击(OCR 定位,优先于裸坐标 click)。token+text;match=contains/exact;多命中须 index;button=left/right/middle;clicks=1/2/3;offset=left/right/above/below 点文字旁图形(如「记住我」旁的复选框),distance=偏移像素(默认 28)。",
        "required": {"token": ("str",), "text": ("str",)},
        "optional": {"match": ("str",), "index": ("int",),
                     "button": ("str",), "clicks": ("int",),
                     "offset": ("enum", ["left", "right", "above", "below"]),
                     "distance": ("int",)}},
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
        "description": "在 Windows 桌面拖拽鼠标(起点→终点,虚拟桌面坐标系)。token+start/end(各 [x,y]);button=left/right/middle(默认 left)。起点须在绑定窗内(防误射);终点可为虚拟桌面任意点(移动窗口/跨屏拖拽允许,越出所有屏拒)。",
        "required": {"token": ("str",), "start": ("coord",), "end": ("coord",)},
             "optional": {"button": ("enum", ["left", "right", "middle"])}},
    # ---- REQ-001 原语层(组合基座,详设 §5.1~5.3)----
    "mouse_down": {
        "description": "在 Windows 桌面按下鼠标指定键不松(原语层,组合基座:down+move+up=按住拖动,左右键可同按)。token+button(left/right/middle)。光标态操作,按前请先激活目标窗口或移动光标就位。安全网:30s 看门狗自动抬/急停强抬/启动清扫。",
        "required": {"token": ("str",),
                     "button": ("enum", ["left", "right", "middle"])},
        "optional": {}},
    "mouse_up": {
        "description": "抬起 Windows 桌面鼠标指定键,与 mouse_down 配对组合任意序列。token+button。幂等:无对应按下时 no-op 返回 released=false,防重试误抬。光标态操作,生效于当前光标所在处。",
        "required": {"token": ("str",),
                     "button": ("enum", ["left", "right", "middle"])},
        "optional": {}},
    "hold": {
        "description": "在 Windows 桌面按住鼠标指定键不放,到时自动抬起(异常也必抬)。token+duration_ms(1~30000 毫秒)+button(默认 left)。光标态操作,按前请确认光标就位。",
        "required": {"token": ("str",), "duration_ms": ("int",)},
        "optional": {"button": ("enum", ["left", "right", "middle"])}},
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
    if typ == "bool":
        # ISS-0037 B：严格 bool——1/"yes" 拒绝(bool 是 int 子类陷阱)
        if not isinstance(value, bool):
            raise InvalidParamsError(f"参数 {name} 必须为布尔值")
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
    """把内部参数模式转换为 MCP inputSchema。

    type_map 与 _check_type 分支一一对应:新增校验类型必须同步此表
    (ISS-0040【修改引入】:'bool' 漏映射致 list_tools 全量 KeyError)。
    """
    type_map = {"str": {"type": "string"}, "text": {"type": "string"},
                "int": {"type": "integer"}, "num": {"type": "number"},
                "bool": {"type": "boolean"},
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
            data = result_dict.get("data") or {}
            # ISS-0089 A1/A3:内联降采样+scale 同步须在 payload dump 之前
            b64 = None
            if (name == "screenshot" and result_dict.get("ok")
                    and data.get("path")):
                b64 = _screenshot_inline_b64(data)
            payload = json.dumps(result_dict, ensure_ascii=False, default=str)
            contents: list = [types.TextContent(type="text", text=payload)]
            if b64 is not None:
                contents.append(types.ImageContent(type="image", data=b64,
                                                   mimeType="image/png"))
            return contents
        if name == "attach":
            result = tools_layer.attach(ctx, title=raw.get("title"),
                                        hwnd=raw.get("hwnd"),
                                        process=raw.get("process"))
        elif name == "detach":
            result = tools_layer.detach(ctx, token=raw.get("token", ""))
        else:
            result = tools_layer.call_tool(ctx, name, raw)
        # ISS-0089 A1/A3:内联降采样+scale 同步须在 payload dump 之前
        b64 = None
        if (name == "screenshot" and result.ok and result.data
                and result.data.get("path")):
            b64 = _screenshot_inline_b64(result.data)
        payload = json.dumps(
            {"ok": result.ok, "error_code": result.error_code,
             "message": result.message, "data": result.data},
            ensure_ascii=False, default=str)
        contents: list = [types.TextContent(type="text", text=payload)]
        if b64 is not None:
            contents.append(types.ImageContent(type="image", data=b64,
                                               mimeType="image/png"))
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
