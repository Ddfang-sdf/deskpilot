"""元素族(ISS-0055 S4):UIA 元素树根/COM 惰性初始化/查找与唯一定位/
类型+序号寻址/元素激活/类型设值/等元素/UIA 树遍历与摘要/桌面图标
装配桥——自 Executor 外迁。

搬函数留委托(self→ex 首参;跨族调用经 ex 委托门面回 core,本模块
不 import 任何兄弟族模块)。`_com_initialize` 接缝留 core,
_ensure_com 函数体内延迟 `from . import core` 调用——test_uia_com_iss16
对 core 的赋值在调用前发生,语义等价(ISS-0055 §6 风险 1 处置)。
`_node_rect` 保持 staticmethod 形态。
"""

from __future__ import annotations

import time

import uiautomation

from ..errors import (ELEMENT_AMBIGUOUS, ELEMENT_DISABLED, ELEMENT_NOT_FOUND,
                      ELEMENT_RECT_DEGENERATE, ELEMENT_UNSUPPORTED,
                      INTERNAL_ERROR, INVALID_PARAMS, TIMEOUT, WINDOW_GONE,
                      ExecutorError)

# ISS-0088:深度上限单源(与 _walk/_iter_controls/_iter_summaries 同口径)
_UI_TREE_MAX_DEPTH = 10


def _strictly_inside(inner, outer) -> bool:
    """ISS-0088 嵌套同名歧义化解的几何判据:矩形缺失/相等(幽灵去重已滤)
    保守返回 False(让位不发生,歧义保持)。"""
    if not inner or not outer:
        return False
    l1, t1, r1, b1 = inner
    l2, t2, r2, b2 = outer
    if (l1, t1, r1, b1) == (l2, t2, r2, b2):
        return False
    return l2 <= l1 and t2 <= t1 and r1 <= r2 and b1 <= b2


def get_ui_tree(ex, window, control_type: str | None = None) -> dict:
    hwnd = ex._resolve_window(window)
    root = ex._element_root(hwnd)      # 走元素源接缝（测试可注入）
    nodes: list[dict] = []
    ex._walk(root, nodes, depth=0)
    truncated = len(nodes) >= 800
    if control_type:
        # ISS-0044 G-01:类型过滤(walk 后子串+大小写不敏感);
        # 截断继承诚实:truncated 标志原样保留,AI 得知结果不完整
        needle = control_type.strip().casefold()
        nodes = [n for n in nodes
                 if needle in n["control_type"].casefold()]
    # ISS-0007 C：坐标系声明（rect 为虚拟桌面坐标，可含负值）
    return {"hwnd": hwnd, "elements": nodes,
            "truncated": truncated,
            "coord_space": "virtual_desktop"}


def list_desktop_icons(ex, region=None) -> dict:
    """桌面图标清单(REQ-002):三路装配;fail-closed;每次调用动态定位。"""
    from .desktop_icons import (ContainerLocator, DesktopIconAssembler,
                                ListViewIconProvider,
                                ShellViewIconProvider, UiaIconProvider)

    def walker(hwnd):
        root = ex._element_root(hwnd)
        nodes: list[dict] = []
        ex._walk(root, nodes, depth=0)
        return nodes

    assembler = DesktopIconAssembler(
        ContainerLocator(), UiaIconProvider(walker),
        ListViewIconProvider(), ShellViewIconProvider())
    items = assembler.assemble(region=region)
    return {"items": items, "count": len(items)}


def _element_root(ex, hwnd: int):
    """绑定窗口的 UIA 根控件；窗口消失 → WINDOW_GONE。

    ISS-0016 A：先线程级 COM 惰性初始化（幂等）；
    ISS-0016 B：COM 通道异常（未初始化/RPC 失败）→ INTERNAL_ERROR
    "UIA 通道异常"（真因不被 WINDOW_GONE 吞掉）。
    """
    ex._ensure_com()
    try:
        if ex._element_source is not None:
            root = ex._element_source(hwnd)
        else:
            root = uiautomation.ControlFromHandle(hwnd)
    except Exception as e:
        raise ExecutorError(INTERNAL_ERROR,
                            f"UIA 通道异常: {e}") from e
    if root is None:
        raise ExecutorError(WINDOW_GONE, "目标窗口已消失")
    return root


def _ensure_com(ex) -> None:
    """ISS-0016 A：当前线程的 COM 惰性初始化（threading.local 幂等）。"""
    local = getattr(ex, "_com_local", None)
    if local is None:
        import threading
        local = ex._com_local = threading.local()
    if getattr(local, "inited", False):
        return
    from . import core
    core._com_initialize()
    local.inited = True


def _find_elements(ex, root, *, name=None, automation_id=None,
                   control_type=None, visible_only=False) -> list:
    """按名称/自动化标识/控件类型在绑定窗口树内查找（§14.7 定位条件）。

    ISS-0044 G-01:control_type 子串+大小写不敏感过滤;与 name 同传时
    取交集(名称子串∧类型子串)。
    WinUI 树存在幽灵重复（同名同型同矩形可见/离屏两份）——按
    名称+自动化标识+矩形三元组去重，视为同一元素。
    ISS-0091 整改③:visible_only=True 仅点击路径传入，过滤
    IsOffscreen=True 候选（不可见元素点击=盲射，常见于折叠菜单/
    隐藏标签页）。注意**不过滤退化矩形元素**——Invoke-first 对折叠
    控件仍有效，过滤=过修回归（单据 v0.2 裁定 Option A）；退化防护
    由 _invoke_element 守卫在像素兜底时刻（唯一动鼠标处）fail-closed。
    """
    matches = []
    seen: set[tuple] = set()
    needle_type = control_type.strip().casefold() if control_type else None
    for s in ex._iter_summaries(root):           # ISS-0008 P4：摘要复用
        if visible_only and s.get("offscreen"):
            continue
        if control_type is not None and name is not None:
            hit = (needle_type in s["control_type"].casefold()
                   and name in s["name"])
        elif control_type is not None:
            hit = needle_type in s["control_type"].casefold()
        elif name is not None and automation_id is not None:
            hit = s["name"] == name and s["automation_id"] == automation_id
        elif name is not None:
            hit = s["name"] == name
        elif automation_id is not None:
            hit = s["automation_id"] == automation_id
        else:
            hit = False
        if not hit:
            continue
        key = (s["name"], s["automation_id"],
               s["rect"] if s["rect"] is not None else ())
        if key in seen:
            continue
        seen.add(key)
        matches.append(s)
    # ISS-0088(嵌套同名歧义化解,验收「同目标同结果」机制):深度加深后
    # 嵌套同名链(如画图 ribbon ListItem⊃Button 同叫「矩形」)会多匹配——
    # 若某匹配存在「矩形严格内含且深度更深」的子孙匹配,祖先让位
    # (最内层=最精确目标,Invoke-first+像素兜底保证点击几何等价);
    # 无内含关系的同名兄弟保持歧义报错不变(不过修)。
    if len(matches) > 1:
        matches = [s for s in matches if not any(
            m is not s and m["depth"] > s["depth"]
            and _strictly_inside(m["rect"], s["rect"])
            for m in matches)]
    return [s["control"] for s in matches]


def _resolve_unique_element(ex, root, *, name=None, automation_id=None,
                            visible_only=False):
    """唯一性解析：不存在 / 多匹配 / 禁用逐级显式报错（§14.7 流程）。

    ISS-0091 整改③:visible_only 仅点击路径传 True；无匹配时经
    _hidden_hint 区分「元素消失」vs「元素不可见」，AI 可据码自愈。
    """
    matches = ex._find_elements(root, name=name,
                                automation_id=automation_id,
                                visible_only=visible_only)
    if not matches:
        hint = (ex._hidden_hint(root, name=name,
                                automation_id=automation_id)
                if visible_only else "")
        raise ExecutorError(
            ELEMENT_NOT_FOUND,
            f"元素不存在（条件 name={name!r}, automation_id={automation_id!r}）。"
            f"{hint}"
            f"候选元素: {ex._candidate_names(root)}")
    if len(matches) > 1:
        raise ExecutorError(
            ELEMENT_AMBIGUOUS,
            f"元素不唯一（{len(matches)} 个匹配）: "
            f"{', '.join(m.Name for m in matches)}。请缩小定位条件")
    element = matches[0]
    if not bool(getattr(element, "IsEnabled", True)):
        raise ExecutorError(ELEMENT_DISABLED,
                            f"元素 {element.Name or automation_id} 处于禁用态")
    return element


def _hidden_hint(ex, root, *, name=None, automation_id=None,
                 control_type=None) -> str:
    """ISS-0091 整改③（AI 友好）:visible_only 无匹配时重跑不过滤查询。

    命中=元素存在但 IsOffscreen=True——为 NOT_FOUND 消息追加自愈指引，
    免得 AI 在「元素消失」vs「元素不可见」之间瞎猜（两者处置不同）。
    """
    if not ex._find_elements(root, name=name, automation_id=automation_id,
                             control_type=control_type):
        return ""
    return ("提示: 该元素存在但当前不可见（IsOffscreen=True，常见于折叠"
            "菜单/未展开面板/隐藏标签页），点击路径已拒绝以防误点。"
            "下一步: 先展开其所属容器后重新取树，或改用键盘路径"
            "（key/type_text），或 get_ui_tree 确认可见性。")


def _candidate_names(ex, root) -> str:
    names: list[str] = []
    for s in ex._iter_summaries(root):             # ISS-0008 P4：摘要复用
        if s["name"] and s["name"] not in names:
            names.append(s["name"])
        if len(names) >= 10:
            break
    return ", ".join(names) or "(无可交互元素)"


def _element_summary(ex, element) -> dict:
    return {"name": element.Name, "control_type": element.ControlTypeName,
            "automation_id": element.AutomationId}


def _node_rect(node):
    """元素矩形：兼容属性形态与下标形态（uiautomation 与替身）。"""
    try:
        rect = node.BoundingRectangle
    except Exception:
        return None
    if rect is None:
        return None
    try:
        l, t, r, b = rect.left, rect.top, rect.right, rect.bottom
    except AttributeError:
        try:
            l, t, r, b = rect[0], rect[1], rect[2], rect[3]
        except Exception:
            return None
    return int(l), int(t), int(r), int(b)


def _resolve_typed_element(ex, root, *, control_type, name=None,
                           index=None, visible_only=False):
    """ISS-0044 G-01:类型+序号寻址——类型过滤(可与 name 交集)后按序取。"""
    matches = ex._find_elements(root, name=name,
                                control_type=control_type,
                                visible_only=visible_only)
    if not matches:
        hint = (ex._hidden_hint(root, name=name,
                                control_type=control_type)
                if visible_only else "")
        raise ExecutorError(
            ELEMENT_NOT_FOUND,
            f"元素不存在（类型 {control_type!r}"
            f"{f', 名称 {name!r}' if name else ''}）。"
            f"{hint}"
            f"候选元素: {ex._candidate_names(root)}")
    i = index if index is not None else 0
    if isinstance(i, bool) or not isinstance(i, int) or i < 0:
        raise ExecutorError(INVALID_PARAMS, f"index 非法: {i!r}")
    if i >= len(matches):
        raise ExecutorError(
            ELEMENT_NOT_FOUND,
            f"类型 {control_type!r} 命中 {len(matches)} 个,"
            f"index={i} 越界(0~{len(matches) - 1})")
    return matches[i]


def _invoke_element(ex, element, hwnd: int | None = None) -> None:
    """元素激活：Invoke 优先，SelectionItem 选择模式次之，像素点击兜底。

    ISS-0091 整改①②:兜底路径 fail-closed 强化——
    ①退化矩形守卫:宽/高≤0 时中心计算退化为屏幕原点 (0,0)，恰为甩角
      判定点（estop.py corner_hold），真实点击可诱发误冻结；守卫必须
      在 _check_point **之前**——否则 (0,0) 先吃 OUT_OF_BOUNDS，错误码
      失真（AI 无法据码自愈）；
    ②校验链接入:镜像 _click 的 ISS-0017 C 次序——check_point →
      激活 → check_occlusion；旧实现兜底零校验，窗口移位/被遮挡时
      照样误点。像素兜底前必须成功前置绑定窗口（防误射）。
    """
    try:
        element.Invoke()
        return
    except Exception:
        pass
    try:
        element.GetSelectionItemPattern().Select()
        return
    except Exception:
        pass
    rect = ex._node_rect(element)
    if rect is None:
        raise ExecutorError(INTERNAL_ERROR,
                            "元素无 Invoke 与选择模式，且无矩形可定位，无法点击")
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    if w <= 0 or h <= 0:
        raise ExecutorError(
            ELEMENT_RECT_DEGENERATE,
            f"元素无 Invoke 与选择模式，且矩形退化（rect={tuple(rect)}，"
            f"宽 {w}px × 高 {h}px ≤0），像素兜底无法计算可靠落点，"
            f"已拒绝点击（防误点屏幕原点诱发冻结）。该元素可能是折叠/"
            f"隐藏容器的占位符。下一步: 先展开其所属容器后重新取树，"
            f"或改用键盘路径（key/type_text）")
    x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    if hwnd is not None:
        ex._check_point(hwnd, x, y)
        if not ex._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，元素点击中止（防误射）")
        ex._check_occlusion(hwnd, x, y)
    ex._pixel_click(x, y)


def _click_element(ex, params: dict, hwnd: int) -> dict:
    som_id = params.get("som_id")
    control_type = params.get("control_type")
    # ISS-0044 G-01:som_id 与 control_type 为两条寻址路径,互斥
    if som_id is not None and control_type:
        raise ExecutorError(
            INVALID_PARAMS,
            "som_id 与 control_type 为两条寻址路径,不可同传")
    if som_id is not None:
        entry = ex._som_cache.get(int(som_id))
        if (entry is not None and entry["hwnd"] == hwnd
                and ex._clock() <= entry["expires"]):
            root = ex._element_root(hwnd)
            element = ex._resolve_unique_element(
                root, name=entry["name"] or None,
                automation_id=entry["automation_id"] or None,
                visible_only=True)       # ISS-0091 整改③:点击路径
        else:
            # REQ-003 §5.3:som 表未命中 → 查 detect 编号表(诊断分支)。
            # **零点击保证**:本分支在 _element_root/_resolve_unique_element
            # /_invoke_element 之前返回,物理上无点击可能
            dentry = ex._detect_cache.get(int(som_id))
            if (dentry is not None and dentry["hwnd"] == hwnd
                    and ex._clock() <= dentry["expires"]):
                raise ExecutorError(
                    ELEMENT_UNSUPPORTED,
                    f"SoM 编号 {som_id} 是 source=\"detect\" 的检测图形"
                    f"区域,不是 UIA 控件,无法经 click_element 寻址。"
                    f"下一步: 取该条目的 rect,用 click 工具按其中心坐标"
                    f"点击")
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                "SoM 编号已失效或不属于当前绑定窗口，"
                "请重新调用 get_clickable_map 取图")
    elif control_type:
        root = ex._element_root(hwnd)
        element = ex._resolve_typed_element(
            root, control_type=control_type, name=params.get("name"),
            index=params.get("index"),
            visible_only=True)           # ISS-0091 整改③:点击路径
    else:
        root = ex._element_root(hwnd)
        element = ex._resolve_unique_element(
            root, name=params.get("name"),
            automation_id=params.get("automation_id"),
            visible_only=True)           # ISS-0091 整改③:点击路径
    ex._invoke_element(element, hwnd)
    return {"status": "ok", "element": ex._element_summary(element)}


def _type_element(ex, params: dict, hwnd: int) -> dict:
    root = ex._element_root(hwnd)
    element = ex._resolve_unique_element(
        root, name=params.get("name"), automation_id=params.get("automation_id"))
    try:
        pattern = element.GetValuePattern()
    except Exception:
        pattern = None
    if pattern is None:
        # uiautomation 对不支持 ValuePattern 的控件返回 None（不抛异常）
        raise ExecutorError(
            ELEMENT_UNSUPPORTED,
            f"元素 {element.Name} 不支持设值（无 ValuePattern），"
            f"请改用 type_text 走剪贴板路径输入")
    try:
        pattern.SetValue(params["text"])
    except Exception as e:
        raise ExecutorError(INTERNAL_ERROR, f"SetValue 失败: {e}") from e
    return {"status": "ok", "element": ex._element_summary(element)}


def _wait_for_element(ex, params: dict, hwnd: int) -> dict:
    limit = min(params.get("timeout") or 10.0, ex._wait_max)
    deadline = ex._clock() + limit
    cond = params.get("name"), params.get("automation_id")
    while True:
        root = ex._element_root(hwnd)
        matches = ex._find_elements(root, name=cond[0], automation_id=cond[1])
        if matches:
            element = matches[0]
            return {"status": "ok", "elapsed": round(limit - (deadline - ex._clock()), 3),
                    "element": ex._element_summary(element)}
        if ex._clock() >= deadline:
            raise ExecutorError(
                TIMEOUT,
                f"等待超时：未发现元素（name={cond[0]!r}, "
                f"automation_id={cond[1]!r}）")
        time.sleep(ex._poll)


def _walk(ex, control, nodes: list, depth: int) -> None:
    if depth > _UI_TREE_MAX_DEPTH or len(nodes) >= 800:
        return
    try:
        rect = control.BoundingRectangle
        try:
            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        except AttributeError:
            try:
                left, top, right, bottom = rect[0], rect[1], rect[2], rect[3]
            except (TypeError, IndexError):
                left = top = right = bottom = 0     # 无矩形节点：摘要置零仍续遍历
        nodes.append({
            "name": control.Name,
            "control_type": control.ControlTypeName,
            "automation_id": control.AutomationId,
            "rect": [left, top, right, bottom],
            "interactable": bool(control.IsEnabled),
            "depth": depth,
        })
    except Exception:
        pass                          # 本节点摘要失败仅跳过，不中止子树
    try:
        children = control.GetChildren()
    except Exception:
        return
    for child in children:
        ex._walk(child, nodes, depth + 1)


def _iter_controls(ex, control, depth: int = 0):
    if control is None or depth > _UI_TREE_MAX_DEPTH:
        return
    yield control
    try:
        children = control.GetChildren()
    except Exception:
        return
    for child in children:
        yield from ex._iter_controls(child, depth + 1)


def _iter_summaries(ex, control, depth: int = 0):
    """遍历控件树并产出每节点一次成型的摘要（ISS-0008 P4）。

    uiautomation 包无 CacheRequest 批量协议，本方法在单次遍历中把
    每个节点的 Name/ControlTypeName/AutomationId/BoundingRectangle/IsEnabled
    各只读取一次并成dict复用，消除消费方的重复 COM 往返。

    ISS-0088:深度上限单源化为 _UI_TREE_MAX_DEPTH(与 _walk 同口径)。
    """
    if control is None or depth > _UI_TREE_MAX_DEPTH:
        return
    try:
        summary = {
            "control": control,
            "name": getattr(control, "Name", "") or "",
            "control_type": getattr(control, "ControlTypeName", "") or "",
            "automation_id": getattr(control, "AutomationId", "") or "",
            "rect": ex._node_rect(control),
            "enabled": bool(getattr(control, "IsEnabled", True)),
            "depth": depth,
        }
    except Exception:
        return
    # ISS-0091 整改③:IsOffscreen 独立防御读取——该属性 COM 波动不
    # 拖垮整条摘要；替身/旧驱动缺该属性时默认 False，既有行为零变化。
    try:
        summary["offscreen"] = bool(getattr(control, "IsOffscreen", False))
    except Exception:
        summary["offscreen"] = False
    yield summary
    try:
        children = control.GetChildren()
    except Exception:
        return
    for child in children:
        yield from ex._iter_summaries(child, depth + 1)
