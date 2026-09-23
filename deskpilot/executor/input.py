"""写入族(ISS-0055 S5):键鼠原语与动词/拖拽轨迹/文本输入与读回——
自 Executor 外迁。

搬函数留委托(self→ex 首参;跨族调用经 ex 委托门面回 core,本模块
不 import 任何兄弟族模块)。`_node_text`/`_read_via_selection` 保持
staticmethod 形态;`_normalize_newlines`/`_traj_points` 保持模块级
纯函数形态。
"""

from __future__ import annotations

import time

import pyautogui
import pyperclip
import uiautomation

from ..errors import (INTERNAL_ERROR, INVALID_PARAMS, OCR_AMBIGUOUS,
                      OCR_TEXT_NOT_FOUND, READBACK_UNAVAILABLE,
                      TYPE_MISMATCH, WINDOW_GONE, ExecutorError)
from ..policy import normalize_key
from .mousehold import MOUSE_BUTTONS
from .textclick import resolve_click, suggest_similar

_pyauto_key_alias = {"escape": "esc"}

# 读回校验目标控件类型(ISS-0100 C):uiautomation 2.x 的 ControlTypeName
# 带 Control 后缀(EditControl/DocumentControl,2.0.29 实测);裸名
# (Edit/Document)为设计与测试替身缝形态——两形并纳,缺一则真机
# 读回通道整体失明(ISS-0100 根因面之一,实证见单据 v0.6)。
_EDIT_TYPE_NAMES = frozenset(
    {"Edit", "Document", "EditControl", "DocumentControl"})
# 注:_SELECTION_SENTINEL 单点定义留 core(TC-105-03 形态钉),
# _read_via_selection 函数体内延迟读(免循环 import)。


def _normalize_newlines(s: str) -> str:
    """读回比对的换行归一（ISS-0100 实机取证）：TextPattern GetText 把
    CRLF 呈现为孤立 \\r（记事本 RichEditD2DPT 实测），原样子串包含会对
    多行文本误报不一致——双侧归一仅统一换行表示，乱改字符仍必被拦。"""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _traj_points(anchors: list, duration_ms=None) -> list:
    """REQ-004 轨迹引擎（纯函数）：起点→via 各点→终点分段线性插值。

    总步数 = min(48, max(2, round(总弧长/25)))（跨屏长距离封顶,
    短距不空转）;各段步数 = max(1, round(总步数×段长/总弧长)),
    段末点 = 该段锚点;每步时长:duration_ms 给定 = 总时长/总步数
    （匀速,各段按弧长比例自然分得时长）,缺省 = 0.02（现行为保持）。
    返回 [(x, y, duration)];贝塞尔/吸附/避障不做（裁定边界）。
    """
    import math
    segs = []
    total = 0.0
    for a, b in zip(anchors, anchors[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        segs.append((a, b, length))
        total += length
    total_steps = min(48, max(2, round(total / 25)))
    per = (duration_ms / 1000.0 / total_steps
           if duration_ms is not None else 0.02)
    out = []
    for a, b, length in segs:
        n = max(1, round(total_steps * length / total)) if total else 1
        for i in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * i / n,
                        a[1] + (b[1] - a[1]) * i / n, per))
    return out


def move(ex, x: int, y: int) -> dict:
    """移动鼠标（L1，无写入）。

    ISS-0052：FAILSAFE 收敛（经 ISS-0056 单点 _failsafe_guard）——
    光标压角时 moveTo 抛 FailSafeException;不收敛则沿 L1 直调链
    裸逃成 500（_run_sensing 只接 ExecutorError）。
    """
    from .core import _failsafe_guard
    _failsafe_guard(pyautogui.moveTo, x, y)
    return {"status": "ok"}


def _click(ex, x: int, y: int, hwnd: int,
           button: str = "left", clicks: int = 1) -> dict:
    from .core import _failsafe_guard
    if button not in MOUSE_BUTTONS:
        raise ExecutorError(INVALID_PARAMS, f"button 非法: {button}")
    if isinstance(clicks, bool) or not isinstance(clicks, int) \
            or clicks not in (1, 2, 3):
        raise ExecutorError(INVALID_PARAMS, f"clicks 非法(1/2/3): {clicks}")
    ex._check_point(hwnd, x, y)
    if not ex._activate_if_needed(hwnd):
        raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
    ex._check_occlusion(hwnd, x, y)     # ISS-0017 C：激活后再验遮挡
    _failsafe_guard(pyautogui.click, x, y, button=button, clicks=clicks)
    return {"status": "ok"}


def _pixel_click(ex, x: int, y: int) -> None:
    from .core import _failsafe_guard
    _failsafe_guard(pyautogui.click, x, y)


def _mouse_down(ex, button: str, hwnd: int) -> dict:
    """按下指定键并登记;位置无关(光标态操作),不激活不拍图(MOUSE-14)。"""
    ex._mouse.press(button)
    pyautogui.mouseDown(button=button)
    return {"status": "ok", "button": button,
            "pressed": ex._mouse.snapshot()}


def _mouse_up(ex, button: str, hwnd: int) -> dict:
    """抬起指定键并核销;无对应按下时 no-op(released=false,防重试误抬)。"""
    if ex._mouse.release(button):
        pyautogui.mouseUp(button=button)
        return {"status": "ok", "button": button, "released": True}
    return {"status": "ok", "button": button, "released": False}


def _hold(ex, duration_ms: int, button: str, hwnd: int) -> dict:
    """按住不放:按下→等待→抬起;任何异常路径键必抬(finally)。"""
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) \
            or not (1 <= duration_ms <= 30000):
        raise ExecutorError(
            INVALID_PARAMS,
            f"duration_ms 越界(1~30000): {duration_ms}")
    ex._mouse.press(button)
    pyautogui.mouseDown(button=button)
    try:
        time.sleep(duration_ms / 1000)
    finally:
        pyautogui.mouseUp(button=button)
        ex._mouse.release(button)
    return {"status": "ok", "button": button, "held_ms": duration_ms}


def _mouse_watchdog_tick(ex) -> None:
    """看门狗单轮检测(公开接缝:测试手动驱动;生产由装配方启动线程)。"""
    ex._mouse_watchdog.tick()


def _force_release_button(ex, button: str) -> None:
    pyautogui.mouseUp(button=button)


def _force_release_all(ex) -> None:
    """安全网①:estop 冻结监听器——强制抬起全部按下键。"""
    for b in ex._mouse.release_all():
        try:
            pyautogui.mouseUp(button=b)
        except Exception:                   # noqa: BLE001
            pass


def _drag(ex, start, end, hwnd: int, button: str = "left",
          via=None, duration_ms=None) -> dict:
    """REQ-004:via=途经点列表(≤32,超限 fail-closed;各途经点沿用
    终点同闸逐屏判定,越界拒绝零派发);duration_ms=总时长(按弧长
    比例分配各段,匀速);缺省=现行为直线两点 24 步×0.02 逐点不变。"""
    from .core import _failsafe_guard
    if button not in MOUSE_BUTTONS:
        raise ExecutorError(INVALID_PARAMS, f"button 非法: {button}")
    ex._check_point(hwnd, *start)   # 起点防误射不变(绑定窗内)
    use_traj = bool(via) or duration_ms is not None
    if use_traj:
        if via is not None and len(via) > 32:
            raise ExecutorError(
                INVALID_PARAMS,
                f"via 途经点超限（{len(via)} > 32，fail-closed）")
        anchors = [list(start)] + [list(p) for p in (via or [])] + [list(end)]
        for p in anchors[1:]:
            ex._check_drag_end(*p)  # 途经点与终点同闸(逐屏判定)
    else:
        ex._check_drag_end(*end)        # ISS-0047:终点=虚拟桌面逐屏判定
    if not ex._activate_if_needed(hwnd):
        raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
    ex._check_occlusion(hwnd, *start)   # ISS-0017 C：激活后再验遮挡
    # ISS-0056:段级收敛——按下/移动/抬起序列整体经单点 guard,
    # 内层 finally(抬键+核销)语义不变(FAILSAFE 触发也先抬键)
    def _do_drag():
        pyautogui.moveTo(*start)
        # REQ-001:按下表对称登记/核销(任意 button;安全网覆盖一切物理按下)
        ex._mouse.press(button)
        pyautogui.mouseDown(button=button)
        try:
            time.sleep(0.15)                      # 让目标应用识别按下
            if use_traj:
                # REQ-004:分段轨迹引擎(锚点=起点→via→终点)
                for x, y, dur in _traj_points(anchors, duration_ms):
                    pyautogui.moveTo(x, y, duration=dur)
            else:
                steps = 24                        # 分段慢移，保证轨迹被采到
                for i in range(1, steps + 1):
                    x = start[0] + (end[0] - start[0]) * i / steps
                    y = start[1] + (end[1] - start[1]) * i / steps
                    pyautogui.moveTo(x, y, duration=0.02)
            time.sleep(0.1)
        finally:
            pyautogui.mouseUp(button=button)
            ex._mouse.release(button)
    _failsafe_guard(_do_drag)
    return {"status": "ok"}


def _scroll(ex, direction: str, amount: int, hwnd: int) -> dict:
    rect = ex._probe.rect_of(hwnd)
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    if not ex._activate_if_needed(hwnd):
        raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
    if direction in ("left", "right"):
        # REQ-001 水平滚轮:left=负向,right=正向(与垂直对称)
        pyautogui.hscroll(-amount if direction == "left" else amount,
                          x=cx, y=cy)
    else:
        pyautogui.scroll(-amount if direction == "down" else amount,
                         x=cx, y=cy)
    return {"status": "ok"}


def _key(ex, raw_key: str, hwnd: int) -> dict:
    from .core import _failsafe_guard
    norm = normalize_key(raw_key)
    parts = [_pyauto_key_alias.get(p, p) for p in norm.split("+")]
    if not ex._activate_if_needed(hwnd):
        raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
    def _send():
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)
    _failsafe_guard(_send)                  # ISS-0056:收敛单点
    return {"status": "ok", "key": norm}


def _type_text(ex, text: str, hwnd: int) -> dict:
    """全量走剪贴板桥（INV-5：全程无预清空动作）。

    ISS-0100 A：逐键模拟路径废止——中文 IME 激活时按键流进组合器，
    落地内容由词库决定（demo 录制实证乱码）；任何文本一律走桥。
    ISS-0100 C：读回校验修真——比对失败重试耗尽报 TYPE_MISMATCH；
    读回三通道全灭 raise READBACK_UNAVAILABLE（fail-closed，
    不再 ok:true 放行）。
    """
    if not ex._activate_if_needed(hwnd):
        raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
    # ISS-0104(裁定 A):首次粘贴前聚焦首个 Edit/Document 控件——
    # 窗口前台 ≠ 键盘焦点在编辑区(Win11 记事本焦点可在标签条,
    # ctrl+v 对非编辑焦点是空操作,W6 实盘)。聚焦只做一次(重贴
    # 不重复聚焦,选择态副作用最小化);无编辑控件/聚焦失败不阻断,
    # fail-closed 由读回保证(§5)。
    ex._focus_first_edit(hwnd)

    old_clip = None
    try:
        old_clip = pyperclip.paste()
    except Exception:
        pass
    attempts = 0
    note = ""
    try:
        while True:
            pyperclip.copy(text)
            ex._activate_if_needed(hwnd)
            pyautogui.hotkey("ctrl", "v")
            # ISS-0035 C1:读回轮询确认——UIA 值刷新有滞后,单次立读
            # 会把"成功但滞后"误判为失败而重贴(文档重复实证)。轮询
            # 耗尽仍不含目标文本才判失败重贴;宁重复不丢字
            # 原则保留(轮询耗尽仍重贴至上限)。
            # ISS-0045 ①:轮询窗口按文本规模缩放——刷新耗时随文本量
            # 增长(65k 实证 3×300ms 远不够),每 8k 字符加一拍,
            # 3 拍起步、20 拍(6s)封顶。
            poll_budget = min(20, max(3, -(-len(text) // 8192)))
            want = _normalize_newlines(text)
            for _poll in range(poll_budget):
                time.sleep(0.3)
                current = ex._read_edit_value(hwnd)
                if current is None:
                    # ISS-0100 C③:读回三通道全灭(目标无 Edit/Document)
                    # → fail-closed,不再「note 不可用仍 ok:true」放行;
                    # 指引 AI 用 screenshot 自核(感知面自核,既有哲学)
                    raise ExecutorError(
                        READBACK_UNAVAILABLE,
                        "目标无可读回通道，落地内容未经校验"
                        "（fail-closed 不放行）；请用 screenshot "
                        "自核落地结果")
                if want in _normalize_newlines(current):
                    note = "读回校验一致"
                    break
            if note == "读回校验一致":
                break
            attempts += 1
            if attempts >= 2:
                raise ExecutorError(TYPE_MISMATCH,
                                    "粘贴读回校验不一致且重试耗尽")
    finally:
        if old_clip is not None:
            try:
                pyperclip.copy(old_clip)
            except Exception:
                pass
    return {"status": "ok", "mode": "clipboard", "note": note}


def _click_text(ex, params: dict, hwnd: int) -> dict:
    """ISS-0021 A：按文字点击——前置实拍→OCR→换算→与 click 同安全链。

    失败分类 fail-closed（未命中/多命中/越窗/参数非法）一律零点击；
    落点复用 _check_point/_check_occlusion 防误射管线。
    """
    from .core import _failsafe_guard
    button = params.get("button", "left")
    if button not in MOUSE_BUTTONS:
        raise ExecutorError(INVALID_PARAMS, f"button 非法: {button}")
    clicks = params.get("clicks", 1)
    if isinstance(clicks, bool) or not isinstance(clicks, int) \
            or clicks not in (1, 2, 3):
        raise ExecutorError(INVALID_PARAMS, f"clicks 非法(1/2/3): {clicks}")
    if not ex._activate_if_needed(hwnd):
        raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
    rect = ex._binding_rect(hwnd)
    if rect is None:
        raise ExecutorError(WINDOW_GONE, "绑定窗口矩形不可得（可能已消失）")
    region = ex._resolve_region("window", None, hwnd)
    ocr = ex.ocr(region)                      # 实拍+识别（懒加载）
    status, payload = resolve_click(
        ocr["items"], str(params.get("text", "")),
        params.get("match", "contains"), params.get("index"),
        region["width"], region["height"], rect)
    if status == "invalid":
        raise ExecutorError(INVALID_PARAMS, payload)
    if status == "not_found":
        # ISS-0027 B：附相似建议(仅文本,无载荷),AI 可一轮自愈
        near = suggest_similar(ocr["items"],
                               str(params.get("text", "")))
        hint = f"。相似文本: {' / '.join(near)}" if near else ""
        raise ExecutorError(
            OCR_TEXT_NOT_FOUND,
            f"未找到文字: {params.get('text')}。OCR 可见: {payload}"
            f"{hint}")
    if status == "ambiguous":
        raise ExecutorError(
            OCR_AMBIGUOUS,
            f"文字命中 {len(payload)} 处,请用 index 指定: {payload}")
    if status == "out_of_window":
        raise ExecutorError(INTERNAL_ERROR,
                            f"OCR 命中框越窗（数据异常）: {payload}")
    x, y = payload["point"]
    # ISS-0044 G-02:文字锚点偏移——命中框边缘±distance(几何契约见问题单 §2)
    offset = params.get("offset")
    if offset:
        distance = params.get("distance", 28)
        if isinstance(distance, bool) or not isinstance(distance, int) \
                or distance < 1:
            raise ExecutorError(
                INVALID_PARAMS, f"distance 非法(≥1): {distance}")
        bx1, by1, bx2, by2 = payload["box"]
        mx, my = (bx1 + bx2) // 2, (by1 + by2) // 2
        if offset == "left":
            x, y = bx1 - distance, my
        elif offset == "right":
            x, y = bx2 + distance, my
        elif offset == "above":
            x, y = mx, by1 - distance
        else:                               # below
            x, y = mx, by2 + distance
    ex._check_point(hwnd, x, y)
    ex._check_occlusion(hwnd, x, y)     # 与 click 同遮挡校验
    _failsafe_guard(pyautogui.click, x, y, button=button, clicks=clicks)
    return {"status": "ok", "target": [x, y],
            "matched": payload["matched"]}


def _read_edit_value(ex, hwnd: int) -> str | None:
    """收集窗口内全部 Edit/Document 控件的值（拼接），供读回校验。

    ISS-0100 C 三级通道序：① ValuePattern（Edit 类，现状）；
    ② TextPattern（Document 类,Win11 记事本富文本编辑器走此——
    DocumentRange().GetText(-1) 取全文）；③ 选读（前两路无值且
    存在 Edit/Document 控件时：ctrl+a + ctrl+c 读剪贴板——选读会
    覆盖剪贴板中的请求文本，还原由 _type_text 的 finally old_clip
    语义覆盖，语义不变）。三通道全灭（目标无 Edit/Document）
    返回 None（调用方 fail-closed）。

    ISS-0106:首行 _ensure_com()(ISS-0016 A 缝)——打包形态线程
    COM 未初始化时 UIA 调用必抛,被下方 except 吞成「无通道」假象。
    """
    ex._ensure_com()
    try:
        root = uiautomation.ControlFromHandle(hwnd)
        values: list[str] = []
        has_edit = False
        for node in ex._iter_controls(root, depth=0):
            if node.ControlTypeName in _EDIT_TYPE_NAMES:
                has_edit = True
                value = ex._node_text(node)
                if value:
                    values.append(value)
        if values:
            return "\n".join(values)
        if has_edit:
            return ex._read_via_selection()
        return None
    except Exception:
        return None


def _focus_first_edit(ex, hwnd: int) -> None:
    """粘贴前聚焦（ISS-0104 §5）：窗口内第一个 Edit/Document 控件
    调 UIA SetFocus（复用 _iter_controls+_EDIT_TYPE_NAMES 枚举,
    与读回通道同一控件面）。无命中节点/任何异常吞掉不阻断——
    聚焦是成功率优化,fail-closed 由读回校验保证;
    选择态副作用（如全选）属裁定接受的交互副作用（§5 登记）。

    ISS-0106:首行 _ensure_com()(同 _read_edit_value 的绕缝修复)。
    """
    ex._ensure_com()
    try:
        root = uiautomation.ControlFromHandle(hwnd)
        for node in ex._iter_controls(root, depth=0):
            if node.ControlTypeName in _EDIT_TYPE_NAMES:
                node.SetFocus()
                return
    except Exception:                           # noqa: BLE001
        pass


def _node_text(node) -> str | None:
    """单节点读值：① ValuePattern → ② TextPattern（取全文）。

    uiautomation 2.x 实测（2.0.29）：ValuePattern.Value 为属性
    （旧 .Current.Value 形态已不存在）；TextPattern.DocumentRange
    为属性（非方法）。两形并存兼容（测试替身缝=方法形态,
    tests/test_typeguard_iss100.py）。
    """
    try:
        vp = node.GetValuePattern()
        cur = getattr(vp, "Current", None)
        value = cur.Value if cur is not None else vp.Value
        if isinstance(value, str) and value:
            return value
    except Exception:
        pass
    try:
        rng = node.GetTextPattern().DocumentRange
        rng = rng() if callable(rng) else rng
        text = rng.GetText(-1)
        if isinstance(text, str) and text:
            return text
    except Exception:
        pass
    return None


def _read_via_selection() -> str | None:
    """选读通道（③）：哨兵清剪贴板 → ctrl+a 全选 + ctrl+c 读剪贴板。

    ISS-0105（裁定 A）：选读前 copy _SELECTION_SENTINEL——ctrl+c 后
    内容仍是哨兵=目标应用未改写（焦点落空空操作）=选读失败返回
    None（交上层 READBACK_UNAVAILABLE/重试,自证路径封死）;
    被改写才返回真实选区内容。哨兵一次性写由 _type_text 的
    finally old_clip 还原语义覆盖（与现选读通道同生命周期）。
    读前短等剪贴板写滞后（ctrl+c 到剪贴板可见非严格同步;
    外层读回轮询提供重读节奏,此处只消一次竞态）。
    """
    # 哨兵单点定义留 core(TC-105-03 形态钉),函数体内延迟读(免循环 import)
    from .core import _SELECTION_SENTINEL
    try:
        pyperclip.copy(_SELECTION_SENTINEL)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.2)
        value = pyperclip.paste()
        if not isinstance(value, str) or not value:
            return None
        if value == _SELECTION_SENTINEL:
            return None                 # 未被改写=选读失败(自证封死)
        return value
    except Exception:
        return None
