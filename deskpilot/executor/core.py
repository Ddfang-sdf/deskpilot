"""执行层核心（详细设计 §9）：真实桌面驱动。

只执行、不判断（安全判定全在强制层）。写路径动手前复查冻结标志（双检查）。
驱动：截图 mss；键鼠 pyautogui；UIA uiautomation；剪贴板 pyperclip；窗口探测 ctypes。
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import mss
import mss.tools
import pyautogui
import pyperclip
import uiautomation

# ISS-0016 A：线程级 COM 惰性初始化（daemon 线程池上 UIA 可用的前提）。
# 真实初始化函数；测试中可替身计数（幂等性断言点）。
_com_initialize = None
if _com_initialize is None:
    import comtypes
    _com_initialize = comtypes.CoInitialize

# ISS-0017 C：遮挡判定的 user32 接缝（默认真实 user32；测试可替身）
_occlusion_user32 = None

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ..errors import (DETECTOR_UNAVAILABLE, ELEMENT_AMBIGUOUS, ELEMENT_DISABLED,
                      ELEMENT_NOT_FOUND, ELEMENT_RECT_DEGENERATE,
                      ELEMENT_UNSUPPORTED, EMERGENCY_STOP,
                      INTERNAL_ERROR, INVALID_PARAMS, OCR_AMBIGUOUS,
                      OCR_TEXT_NOT_FOUND, OUT_OF_BOUNDS, READBACK_UNAVAILABLE,
                      TIMEOUT, TYPE_MISMATCH, WINDOW_GONE,
                      WINDOW_OCCLUDED, ExecutorError, InvalidParamsError)
from ..audit_events import (
    EV_SCREENSHOT_OVERWRITE, EV_STARTUP_KEY_SWEEP,
    EV_STARTUP_KEY_SWEEP_FAILSAFE)
from .detector import resolve, screened, to_virtual, verify
from . import elements, guards, input as input_, screens, vision
from .mousehold import MOUSE_BUTTONS, PressedTracker, WatchdogThread
from .probe import DesktopProbe, set_window_rect as _os_set_window_rect

_NOT_WIRED = {
    "get_clickable_map", "ocr", "template_match",
}  # 驱动未包含在 M1 构建（OCR/模板匹配/SoM 见里程碑 M3）


# ISS-0088 方向①:UIA 树遍历深度上限**单源**——_walk(get_ui_tree)与
# _iter_summaries(定位链/SoM 编号)/_iter_controls(读回校验)共用同一常量,
# 消除「树上看得见、定位链点不到」的双口径(8 vs 10 曾致画图形状钮
# depth9 可见不可点)。取较深者 10;800 条防爆炸上限(_walk)不动。
_UI_TREE_MAX_DEPTH = 10

# ISS-0105(裁定 A):选读哨兵——选读通道③写剪贴板前的占位定值。
# 焦点落空时 ctrl+c 是空操作,剪贴板残留桥写入的请求文本会把读回
# 比对退化成自证(假命中实证,见单据 §1);ctrl+c 后内容仍是哨兵
# =选读失败(None),被改写才进入比对。含不可打印字符 \x00 防撞串;
# 单点定义(TC-105-03 形态钉)。
_SELECTION_SENTINEL = "\x00DP-SENTINEL\x00"


def _failsafe_guard(fn, *args, **kwargs):
    """ISS-0056：pyautogui FAILSAFE → EMERGENCY_STOP 收敛单点
    （ISS-0009 §6 C 三方异常收敛；原 7 处复制模板——复制一次多一处
    漏接面，ISS-0052 move 裸逃成 500 即实证）。
    错误消息语义不变（含 pyautogui 原文）；仅 FailSafeException 转换,
    其余异常原样上抛。"""
    try:
        return fn(*args, **kwargs)
    except pyautogui.FailSafeException as e:
        raise ExecutorError(EMERGENCY_STOP,
                            f"pyautogui FAILSAFE 触发: {e}") from e


def _strictly_inside(inner, outer) -> bool:
    """ISS-0088 几何判据(委托 elements)。"""
    return elements._strictly_inside(inner, outer)


def _tool_set_clipboard(ex, params, hwnd) -> dict:
    pyperclip.copy(params["text"])
    return {"status": "ok"}


def _tool_activate_window(ex, params, hwnd) -> dict:
    ok = ex._activate_if_needed(hwnd)
    if not ok:
        raise ExecutorError(WINDOW_GONE, "窗口无法前置（可能已消失）")
    return {"status": "ok"}


def _tool_move(ex, params, hwnd) -> dict:
    pyautogui.moveTo(params["x"], params["y"])
    return {"status": "ok"}


def _tool_launch_app(ex, params, hwnd) -> dict:
    try:
        proc = subprocess.Popen([params["app"]])
    except OSError as e:
        raise ExecutorError(INTERNAL_ERROR, f"启动失败: {e}") from e
    return {"status": "ok", "pid": proc.pid}


# ISS-0055 S6:分发表注册制(裁决 v0.2②)——tool→执行驱动的单点登记表,
# 同语义替换原 15 连 if;新增工具=登记一行,未知工具错误消息逐字不变。
_DISPATCH_TABLE = {
    "click": lambda ex, p, h: ex._click(p["x"], p["y"], h,
                                        button=p.get("button", "left"),
                                        clicks=p.get("clicks", 1)),
    "mouse_down": lambda ex, p, h: ex._mouse_down(p["button"], h),
    "mouse_up": lambda ex, p, h: ex._mouse_up(p["button"], h),
    "hold": lambda ex, p, h: ex._hold(p["duration_ms"],
                                      p.get("button", "left"), h),
    "click_text": lambda ex, p, h: ex._click_text(p, h),
    "type_text": lambda ex, p, h: ex._type_text(p["text"], h),
    "key": lambda ex, p, h: ex._key(p["key"], h),
    "set_clipboard": _tool_set_clipboard,
    "scroll": lambda ex, p, h: ex._scroll(p["direction"], p["amount"], h),
    "drag": lambda ex, p, h: ex._drag(p["start"], p["end"], h,
                                      button=p.get("button", "left"),
                                      # REQ-004:via/duration_ms 透传
                                      via=p.get("via"),
                                      duration_ms=p.get("duration_ms")),
    "activate_window": _tool_activate_window,
    "set_window_rect": lambda ex, p, h: ex._set_window_rect(p, h),
    "move": _tool_move,
    "launch_app": _tool_launch_app,
    "click_element": lambda ex, p, h: ex._click_element(p, h),
    "type_element": lambda ex, p, h: ex._type_element(p, h),
    "wait_for_element": lambda ex, p, h: ex._wait_for_element(p, h),
}


class Executor:
    """执行层公开入口。"""

    def __init__(self, estop, audit_dir: str, poll_interval: float = 0.5,
                 wait_timeout_max: float = 300.0, clock: Callable[[], float] = time.monotonic,
                 probe=None, element_source=None, shot_fn=None, ocr_engine=None,
                 audit=None, detector_weights_dir: str | None = None,
                 allowed_roots=None):
        self._probe = probe if probe is not None else DesktopProbe()
        self._estop = estop
        self._shots_dir = Path(audit_dir) / "shots"
        self._poll = poll_interval
        self._wait_max = wait_timeout_max
        self._clock = clock
        self._element_source = element_source   # UIA 根控件工厂（可注入，测试接缝）
        self._shot_fn = shot_fn                 # 区域截图工厂（可注入，测试接缝）
        self._ocr_engine = ocr_engine           # OCR 引擎（可注入，测试接缝）
        self._audit = audit                     # 审计通道（可注入;无则安全网事件不落盘）
        self.ocr_factory = None                 # ISS-0008 §6：OCR 懒加载工厂（公开属性）
        # REQ-003 §3.3：权重目录取值（policy.yml 顶层 detector_weights_dir 的值，
        # 由 main 装配期传入）；相对路径的锚定交给 resolve()，此处不自行解析。
        # 缺省 None = 生产未接线（P3 起由 main 传入 policy 取值）
        self._weights_dir_configured = detector_weights_dir
        # ISS-0102 §3.2(P1 空壳:仅签名+默认值,护栏逻辑 P3 落):screenshot
        # path 落盘允许根集合=仓库根(policy.yml 所在目录)∪审计根
        # (resolve_audit_dir 绝对值),装配期 main.py 计算传入;缺省 None
        self._allowed_roots = allowed_roots
        # REQ-003 §3.7 / D-18：检测器工厂（公开装配位，与 ocr_factory 同处装配）；
        # 缺省 None = 未装配 → detect=true 落 DETECTOR_UNAVAILABLE（§9.1）
        self.detector_factory = None
        # REQ-003 §3.2 / D-18：权重清单（公开装配位，与 detector_factory 平行）。
        # 形态 = 扁平 {相对路径: sha256}(与 verify() 入参同形);缺省 = 出厂
        # 空清单(D-12 未裁——空清单下 verify() 给 ok 是真实语义,但空清单 ≠
        # 可用出厂形态,D-12 后必须回填);生产装配不赋值(§6 main 装配期)
        self.weight_manifest: dict = {}
        # FD-06:置信度门槛是**检测器装配参数**,不进 policy.yml;随装配固定
        self.detector_threshold = 0.5
        # REQ-003 §3.7:检测器懒装填状态(承 _ensure_ocr_engine 形态)
        self._detector = None
        self._detector_failed: str | None = None   # 失败记忆串(§8.1 口径)
        self._detector_lock = threading.Lock()
        self._detect_cache: dict[int, dict] = {}   # detect 编号表(§3.7,只诊断)
        self._ocr_lock = threading.Lock()       # ISS-0008 P2：懒初始化一次性锁
        self._ocr_failed: str | None = None     # ISS-0008 P2：初始化失败记忆化
        self._som_cache: dict[int, dict] = {}   # SoM 编号缓存（§9.9）
        # REQ-001：按下状态跟踪器+看门狗(安全网基座;线程由装配方显式启动,
        # 测试经 _mouse_watchdog_tick 手动驱动,防背景线程抢跑断言)
        self._mouse = PressedTracker(clock=self._clock)
        self._mouse_watchdog = WatchdogThread(
            self._mouse, self._force_release_button, self._audit)
        # REQ-001 D-02：启动抬键清扫——旧进程死亡期悬空按键的系统级自愈
        # ISS-0048(修改引入回归):光标压角时 pyautogui FAILSAFE 会拦截
        # mouseUp——逐键容错,记审计「启动抬键清扫-FAILSAFE拦截」并继续,
        # 启动不得崩;启动期 FAILSAFE 不映射冻结(光标压角≠用户急停意图)。
        _sweep_blocked = 0
        for _b in MOUSE_BUTTONS:
            try:
                pyautogui.mouseUp(button=_b)    # 幂等:无按下=系统级 no-op
            except pyautogui.FailSafeException:
                _sweep_blocked += 1
        if self._audit is not None:
            self._audit.record_event(EV_STARTUP_KEY_SWEEP, "三键幂等抬起")
            if _sweep_blocked:
                self._audit.record_event(EV_STARTUP_KEY_SWEEP_FAILSAFE,
                                         f"光标压角拦截 {_sweep_blocked} 键")
        # REQ-001 安全网①：急停冻结→强制抬起全部按下键
        add_listener = getattr(self._estop, "add_freeze_listener", None)
        if callable(add_listener):
            add_listener(self._force_release_all)
        pyautogui.PAUSE = 0.02

    # ---------- 公开入口 ----------

    def execute(self, instruction: dict[str, Any]) -> dict[str, Any]:
        """执行已放行指令（写路径动手前复查冻结标志，§9.7 双检查）。"""
        tool = instruction["tool"]
        params = instruction["params"]
        hwnd = instruction.get("binding_hwnd")
        if self._estop.is_frozen():
            raise ExecutorError(EMERGENCY_STOP, "急停冻结中，动作中止")
        if tool in _NOT_WIRED:
            raise ExecutorError(INTERNAL_ERROR,
                                f"工具 {tool} 的驱动未包含在 M1 构建（见里程碑规划）")
        rect = self._binding_rect(hwnd)
        # REQ-001 MOUSE-14:原语层 down/up 只记审计不拍图(高频组合证据成本控制)
        no_shot = tool in ("mouse_down", "mouse_up")
        before = "" if no_shot else self._evidence_shot(tool, "before", rect)
        try:
            # ISS-0056:FAILSAFE 收敛单点化(原模板副本删除)
            result = _failsafe_guard(lambda: self._dispatch(tool, params,
                                                            hwnd))
        except ExecutorError:
            raise
        except Exception as e:
            # ISS-0009 §6 C：未知异常不再裸抛（防 handler/进程断连）
            raise ExecutorError(INTERNAL_ERROR,
                                f"执行层未处理异常: {e}") from e
        after = "" if no_shot else self._evidence_shot(tool, "after", rect)
        result = dict(result or {})
        result["before_shot"] = before
        result["after_shot"] = after
        return result

    def _binding_rect(self, hwnd) -> tuple | None:
        """绑定窗口矩形（无绑定或探测失败回退 None → 证据图转全桌面）。"""
        return guards._binding_rect(self, hwnd)

    def focused_control_type(self) -> str | None:
        """查询当前焦点元素的 UIA 控件类型；查询失败返回 None（fail-closed 由调用方处理）。"""
        try:
            control = uiautomation.GetFocusedControl()
            return control.ControlTypeName if control else None
        except Exception:
            return None

    # ---------- 感知（L0，tools 层直调） ----------

    def screenshot(self, scope: str, rect=None, window=None,
                   ocr: bool = False, screen=None, path=None) -> dict:
        """ISS-0102 §3.3(委托 screens)：path 指定路径落盘护栏。"""
        return screens.screenshot(self, scope, rect, window, ocr, screen, path)

    def find_windows(self, title=None, process=None, hwnd=None,
                     include_hidden: bool = False) -> list[dict]:
        return self._probe.find_windows(title=title, process=process,
                                        hwnd=hwnd,
                                        include_hidden=include_hidden)

    def get_ui_tree(self, window, control_type: str | None = None) -> dict:
        return elements.get_ui_tree(self, window, control_type)

    def get_cursor(self) -> dict:
        return screens.get_cursor(self)

    def get_clipboard(self) -> dict:
        return screens.get_clipboard(self)

    def list_desktop_icons(self, region=None) -> dict:
        """桌面图标清单(REQ-002,委托 elements)。"""
        return elements.list_desktop_icons(self, region)

    def move(self, x: int, y: int) -> dict:
        """移动鼠标（L1，无写入;委托 input_）。"""
        return input_.move(self, x, y)

    def ocr(self, source) -> dict:
        """文字识别（委托 vision;懒初始化/失败记忆化口径不变）。"""
        return vision.ocr(self, source)

    def _ensure_ocr_engine(self) -> None:
        """懒初始化 OCR 引擎（ISS-0008 §6,委托 vision）。"""
        vision._ensure_ocr_engine(self)

    def _ensure_detector(self):
        """懒装填检测器（REQ-003 §9.1,委托 vision;记忆化口径不变）。"""
        return vision._ensure_detector(self)

    def template_match(self, template: str, scope, threshold: float = 0.8) -> dict:
        """模板匹配（§12.6,委托 vision）。"""
        return vision.template_match(self, template, scope, threshold)

    def get_clickable_map(self, window, detect: bool = False) -> dict:
        """SoM 标注（§12.6 + REQ-003,委托 vision）。"""
        return vision.get_clickable_map(self, window, detect)

    def capture_approval_shot(self, rect) -> str:
        """审批用目标窗口实拍（委托 screens）。"""
        return screens.capture_approval_shot(self, rect)

    def wait_for_window(self, target: str, timeout: float | None = None) -> dict:
        limit = min(timeout or 10.0, self._wait_max)
        deadline = self._clock() + limit
        last = ""
        while True:
            found = self._probe.find_windows(title=target) or \
                self._probe.find_windows(process=target)
            if found:
                return {"window": found[0], "elapsed": limit - (deadline - self._clock())}
            last = f"未发现标题或进程含 {target!r} 的窗口"
            if self._clock() >= deadline:
                raise ExecutorError(TIMEOUT, f"等待超时：{last}")
            time.sleep(self._poll)

    # ---------- 写动作 ----------

    def _dispatch(self, tool: str, params: dict, hwnd: int | None) -> dict:
        if hwnd is not None and not self._probe.hwnd_alive(hwnd):
            raise ExecutorError(WINDOW_GONE, "目标窗口已消失")
        handler = _DISPATCH_TABLE.get(tool)
        if handler is None:
            raise ExecutorError(INTERNAL_ERROR, f"工具 {tool} 的执行驱动未接线")
        return handler(self, params, hwnd)

    # ---------- M2 元素级驱动（详细设计 §9.2 uia 子模块 / §14.7） ----------

    def _element_root(self, hwnd: int):
        """绑定窗口的 UIA 根控件（委托 elements;元素源接缝不动）。"""
        return elements._element_root(self, hwnd)

    def _ensure_com(self) -> None:
        """ISS-0016 A（委托 elements;_com_initialize 留 core 延迟读）。"""
        elements._ensure_com(self)

    def _find_elements(self, root, *, name=None, automation_id=None,
                       control_type=None, visible_only=False) -> list:
        """按定位条件查找（委托 elements）。"""
        return elements._find_elements(
            self, root, name=name, automation_id=automation_id,
            control_type=control_type, visible_only=visible_only)

    def _resolve_unique_element(self, root, *, name=None, automation_id=None,
                                visible_only=False):
        """唯一性解析（委托 elements）。"""
        return elements._resolve_unique_element(
            self, root, name=name, automation_id=automation_id,
            visible_only=visible_only)

    def _hidden_hint(self, root, *, name=None, automation_id=None,
                     control_type=None) -> str:
        """ISS-0091 整改③（委托 elements）。"""
        return elements._hidden_hint(
            self, root, name=name, automation_id=automation_id,
            control_type=control_type)

    def _candidate_names(self, root) -> str:
        return elements._candidate_names(self, root)

    def _element_summary(self, element) -> dict:
        return elements._element_summary(self, element)

    def _capture(self, region: dict) -> Image.Image:
        """区域截图（shot_fn 为测试接缝；默认 mss 实拍;委托 screens）。"""
        return screens._capture(self, region)

    @staticmethod
    def _region_dict(rect) -> dict:
        return screens._region_dict(rect)

    @staticmethod
    def _node_rect(node):
        """元素矩形（委托 elements,staticmethod 形态保留）。"""
        return elements._node_rect(node)

    def _click_element(self, params: dict, hwnd: int) -> dict:
        return elements._click_element(self, params, hwnd)

    def _resolve_typed_element(self, root, *, control_type, name=None,
                               index=None, visible_only=False):
        """ISS-0044 G-01（委托 elements）。"""
        return elements._resolve_typed_element(
            self, root, control_type=control_type, name=name,
            index=index, visible_only=visible_only)

    def _invoke_element(self, element, hwnd: int | None = None) -> None:
        """元素激活（委托 elements;ISS-0091 退化守卫逐字不变）。"""
        elements._invoke_element(self, element, hwnd)

    def _pixel_click(self, x: int, y: int) -> None:
        return input_._pixel_click(self, x, y)

    def _type_element(self, params: dict, hwnd: int) -> dict:
        return elements._type_element(self, params, hwnd)

    def _wait_for_element(self, params: dict, hwnd: int) -> dict:
        return elements._wait_for_element(self, params, hwnd)

    def _click(self, x: int, y: int, hwnd: int,
               button: str = "left", clicks: int = 1) -> dict:
        return input_._click(self, x, y, hwnd, button, clicks)

    # ---------- REQ-001 原语层:mouse_down/mouse_up/hold ----------

    def _mouse_down(self, button: str, hwnd: int) -> dict:
        """按下指定键并登记(位置无关,不激活不拍图 MOUSE-14;委托 input_)。"""
        return input_._mouse_down(self, button, hwnd)

    def _mouse_up(self, button: str, hwnd: int) -> dict:
        """抬起指定键并核销(无按下时 no-op;委托 input_)。"""
        return input_._mouse_up(self, button, hwnd)

    def _hold(self, duration_ms: int, button: str, hwnd: int) -> dict:
        """按住不放(按下→等待→抬起,finally 必抬;委托 input_)。"""
        return input_._hold(self, duration_ms, button, hwnd)

    def _mouse_watchdog_tick(self) -> None:
        """看门狗单轮检测(公开接缝:测试手动驱动;委托 input_)。"""
        input_._mouse_watchdog_tick(self)

    def _force_release_button(self, button: str) -> None:
        input_._force_release_button(self, button)

    def _force_release_all(self) -> None:
        """安全网①:estop 冻结监听器——强制抬起全部按下键(委托 input_)。"""
        input_._force_release_all(self)

    def _click_text(self, params: dict, hwnd: int) -> dict:
        """ISS-0021 A：按文字点击(委托 input_;失败分类 fail-closed 与
        安全链逐字不变)。"""
        return input_._click_text(self, params, hwnd)

    def _drag(self, start, end, hwnd: int, button: str = "left",
              via=None, duration_ms=None) -> dict:
        """REQ-004(委托 input_):via/duration_ms 透传,轨迹引擎在 input_。"""
        return input_._drag(self, start, end, hwnd, button, via, duration_ms)

    def _scroll(self, direction: str, amount: int, hwnd: int) -> dict:
        return input_._scroll(self, direction, amount, hwnd)

    def _key(self, raw_key: str, hwnd: int) -> dict:
        return input_._key(self, raw_key, hwnd)

    def _type_text(self, text: str, hwnd: int) -> dict:
        """全量走剪贴板桥（INV-5;委托 input_——读回校验修真语义不变）。"""
        return input_._type_text(self, text, hwnd)

    # ---------- 内部 ----------

    def _activate_if_needed(self, hwnd: int) -> bool:
        """仅当目标窗口不在前台时才前置——避免重激活导致弹出的菜单/画廊被销毁。
        返回是否已处前台（fail-closed：写路径调用方必须检查）。"""
        return guards._activate_if_needed(self, hwnd)

    def _set_window_rect(self, params: dict, hwnd: int) -> dict:
        """窗口几何摆放（ISS-0101 §4.2，物理层原语;委托 guards）。"""
        return guards._set_window_rect(self, params, hwnd)

    def _check_point(self, hwnd: int, x: int, y: int) -> None:
        guards._check_point(self, hwnd, x, y)

    def _enum_monitors(self) -> list[dict]:
        """ISS-0047:显示器枚举接缝(测试替身入口;生产=monitors.enum_monitors)。"""
        return guards._enum_monitors(self)

    def _check_drag_end(self, x: int, y: int) -> None:
        """ISS-0047:drag 终点校验=虚拟桌面全域(委托 guards)。"""
        guards._check_drag_end(self, x, y)

    def _check_occlusion(self, hwnd: int, x: int, y: int) -> None:
        """ISS-0017 C：遮挡判定（委托 guards;接缝 _occlusion_user32 留
        core 延迟读——ISS-0055 §6 风险 1 处置）。"""
        guards._check_occlusion(self, hwnd, x, y)

    def _resolve_window(self, window) -> int:
        return guards._resolve_window(self, window)

    def _resolve_region(self, scope: str, rect, window, screen=None) -> dict:
        return screens._resolve_region(self, scope, rect, window, screen)

    def _save_shot(self, region: dict, tag: str, fmt: str = "PNG") -> Path:
        return screens._save_shot(self, region, tag, fmt)

    def _save_shot_to(self, region: dict, target: str) -> Path:
        """ISS-0102 §3.2（委托 screens）：指定路径落盘护栏闸序逐字不变。"""
        return screens._save_shot_to(self, region, target)

    def _evidence_shot(self, tool: str, tag: str, rect: tuple | None = None) -> str:
        """写操作证据图（ISS-0008 P3,委托 screens）。"""
        return screens._evidence_shot(self, tool, tag, rect)

    def _walk(self, control, nodes: list, depth: int) -> None:
        elements._walk(self, control, nodes, depth)

    def _read_edit_value(self, hwnd: int) -> str | None:
        """读回三级通道序（ISS-0100 C,委托 input_;fail-closed 口径不变）。"""
        return input_._read_edit_value(self, hwnd)

    def _focus_first_edit(self, hwnd: int) -> None:
        """粘贴前聚焦首个 Edit/Document 控件（ISS-0104 §5,委托 input_）。"""
        input_._focus_first_edit(self, hwnd)

    @staticmethod
    def _node_text(node) -> str | None:
        """单节点读值（① ValuePattern→② TextPattern;委托 input_,
        staticmethod 形态保留）。"""
        return input_._node_text(node)

    @staticmethod
    def _read_via_selection() -> str | None:
        """选读通道③（委托 input_,staticmethod 形态保留;
        哨兵 _SELECTION_SENTINEL 单点定义留本模块,TC-105-03 钉）。"""
        return input_._read_via_selection()

    def _iter_controls(self, control, depth: int = 0):
        yield from elements._iter_controls(self, control, depth)

    def _iter_summaries(self, control, depth: int = 0):
        """遍历控件树并产出摘要（ISS-0008 P4,委托 elements）。"""
        yield from elements._iter_summaries(self, control, depth)

