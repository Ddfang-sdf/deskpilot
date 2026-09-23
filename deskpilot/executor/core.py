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
from ..policy import normalize_key
from .detector import resolve, screened, to_virtual, verify
from . import guards, screens, vision
from .mousehold import MOUSE_BUTTONS, PressedTracker, WatchdogThread
from .probe import DesktopProbe, set_window_rect as _os_set_window_rect
from .textclick import resolve_click, suggest_similar

_NOT_WIRED = {
    "get_clickable_map", "ocr", "template_match",
}  # 驱动未包含在 M1 构建（OCR/模板匹配/SoM 见里程碑 M3）


_pyauto_key_alias = {"escape": "esc"}

# ISS-0088 方向①:UIA 树遍历深度上限**单源**——_walk(get_ui_tree)与
# _iter_summaries(定位链/SoM 编号)/_iter_controls(读回校验)共用同一常量,
# 消除「树上看得见、定位链点不到」的双口径(8 vs 10 曾致画图形状钮
# depth9 可见不可点)。取较深者 10;800 条防爆炸上限(_walk)不动。
_UI_TREE_MAX_DEPTH = 10
# 读回校验目标控件类型(ISS-0100 C):uiautomation 2.x 的 ControlTypeName
# 带 Control 后缀(EditControl/DocumentControl,2.0.29 实测);裸名
# (Edit/Document)为设计与测试替身缝形态——两形并纳,缺一则真机
# 读回通道整体失明(ISS-0100 根因面之一,实证见单据 v0.6)。
_EDIT_TYPE_NAMES = frozenset(
    {"Edit", "Document", "EditControl", "DocumentControl"})

# ISS-0105(裁定 A):选读哨兵——选读通道③写剪贴板前的占位定值。
# 焦点落空时 ctrl+c 是空操作,剪贴板残留桥写入的请求文本会把读回
# 比对退化成自证(假命中实证,见单据 §1);ctrl+c 后内容仍是哨兵
# =选读失败(None),被改写才进入比对。含不可打印字符 \x00 防撞串;
# 单点定义(TC-105-03 形态钉)。
_SELECTION_SENTINEL = "\x00DP-SENTINEL\x00"


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
    """矩形 inner 是否**严格**内含于 outer(四边内包且不全等)。

    ISS-0088 嵌套同名歧义化解的几何判据:矩形缺失/相等(幽灵去重已滤)
    保守返回 False(让位不发生,歧义保持)。
    """
    if not inner or not outer:
        return False
    l1, t1, r1, b1 = inner
    l2, t2, r2, b2 = outer
    if (l1, t1, r1, b1) == (l2, t2, r2, b2):
        return False
    return l2 <= l1 and t2 <= t1 and r1 <= r2 and b1 <= b2


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
        hwnd = self._resolve_window(window)
        root = self._element_root(hwnd)      # 走元素源接缝（测试可注入）
        nodes: list[dict] = []
        self._walk(root, nodes, depth=0)
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

    def get_cursor(self) -> dict:
        return screens.get_cursor(self)

    def get_clipboard(self) -> dict:
        return screens.get_clipboard(self)

    def list_desktop_icons(self, region=None) -> dict:
        """桌面图标清单(REQ-002):三路装配;fail-closed;每次调用动态定位。"""
        from .desktop_icons import (ContainerLocator, DesktopIconAssembler,
                                    ListViewIconProvider,
                                    ShellViewIconProvider, UiaIconProvider)

        def walker(hwnd):
            root = self._element_root(hwnd)
            nodes: list[dict] = []
            self._walk(root, nodes, depth=0)
            return nodes

        assembler = DesktopIconAssembler(
            ContainerLocator(), UiaIconProvider(walker),
            ListViewIconProvider(), ShellViewIconProvider())
        items = assembler.assemble(region=region)
        return {"items": items, "count": len(items)}

    def move(self, x: int, y: int) -> dict:
        """移动鼠标（L1，无写入）。

        ISS-0052：FAILSAFE 收敛（经 ISS-0056 单点 _failsafe_guard）——
        光标压角时 moveTo 抛 FailSafeException;不收敛则沿 L1 直调链
        裸逃成 500（_run_sensing 只接 ExecutorError）。
        """
        _failsafe_guard(pyautogui.moveTo, x, y)
        return {"status": "ok"}

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
        if tool == "click":
            return self._click(params["x"], params["y"], hwnd,
                               button=params.get("button", "left"),
                               clicks=params.get("clicks", 1))
        if tool == "mouse_down":
            return self._mouse_down(params["button"], hwnd)
        if tool == "mouse_up":
            return self._mouse_up(params["button"], hwnd)
        if tool == "hold":
            return self._hold(params["duration_ms"],
                              params.get("button", "left"), hwnd)
        if tool == "click_text":
            return self._click_text(params, hwnd)
        if tool == "type_text":
            return self._type_text(params["text"], hwnd)
        if tool == "key":
            return self._key(params["key"], hwnd)
        if tool == "set_clipboard":
            pyperclip.copy(params["text"])
            return {"status": "ok"}
        if tool == "scroll":
            return self._scroll(params["direction"], params["amount"], hwnd)
        if tool == "drag":
            return self._drag(params["start"], params["end"], hwnd,
                              button=params.get("button", "left"),
                              # REQ-004:via/duration_ms 透传
                              via=params.get("via"),
                              duration_ms=params.get("duration_ms"))
        if tool == "activate_window":
            ok = self._activate_if_needed(hwnd)
            if not ok:
                raise ExecutorError(WINDOW_GONE, "窗口无法前置（可能已消失）")
            return {"status": "ok"}
        if tool == "set_window_rect":
            return self._set_window_rect(params, hwnd)
        if tool == "move":
            pyautogui.moveTo(params["x"], params["y"])
            return {"status": "ok"}
        if tool == "launch_app":
            try:
                proc = subprocess.Popen([params["app"]])
            except OSError as e:
                raise ExecutorError(INTERNAL_ERROR, f"启动失败: {e}") from e
            return {"status": "ok", "pid": proc.pid}
        if tool == "click_element":
            return self._click_element(params, hwnd)
        if tool == "type_element":
            return self._type_element(params, hwnd)
        if tool == "wait_for_element":
            return self._wait_for_element(params, hwnd)
        raise ExecutorError(INTERNAL_ERROR, f"工具 {tool} 的执行驱动未接线")

    # ---------- M2 元素级驱动（详细设计 §9.2 uia 子模块 / §14.7） ----------

    def _element_root(self, hwnd: int):
        """绑定窗口的 UIA 根控件；窗口消失 → WINDOW_GONE。

        ISS-0016 A：先线程级 COM 惰性初始化（幂等）；
        ISS-0016 B：COM 通道异常（未初始化/RPC 失败）→ INTERNAL_ERROR
        "UIA 通道异常"（真因不被 WINDOW_GONE 吞掉）。
        """
        self._ensure_com()
        try:
            if self._element_source is not None:
                root = self._element_source(hwnd)
            else:
                root = uiautomation.ControlFromHandle(hwnd)
        except Exception as e:
            raise ExecutorError(INTERNAL_ERROR,
                                f"UIA 通道异常: {e}") from e
        if root is None:
            raise ExecutorError(WINDOW_GONE, "目标窗口已消失")
        return root

    def _ensure_com(self) -> None:
        """ISS-0016 A：当前线程的 COM 惰性初始化（threading.local 幂等）。"""
        local = getattr(self, "_com_local", None)
        if local is None:
            import threading
            local = self._com_local = threading.local()
        if getattr(local, "inited", False):
            return
        _com_initialize()
        local.inited = True

    def _find_elements(self, root, *, name=None, automation_id=None,
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
        for s in self._iter_summaries(root):           # ISS-0008 P4：摘要复用
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

    def _resolve_unique_element(self, root, *, name=None, automation_id=None,
                                visible_only=False):
        """唯一性解析：不存在 / 多匹配 / 禁用逐级显式报错（§14.7 流程）。

        ISS-0091 整改③:visible_only 仅点击路径传 True；无匹配时经
        _hidden_hint 区分「元素消失」vs「元素不可见」，AI 可据码自愈。
        """
        matches = self._find_elements(root, name=name,
                                      automation_id=automation_id,
                                      visible_only=visible_only)
        if not matches:
            hint = (self._hidden_hint(root, name=name,
                                      automation_id=automation_id)
                    if visible_only else "")
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                f"元素不存在（条件 name={name!r}, automation_id={automation_id!r}）。"
                f"{hint}"
                f"候选元素: {self._candidate_names(root)}")
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

    def _hidden_hint(self, root, *, name=None, automation_id=None,
                     control_type=None) -> str:
        """ISS-0091 整改③（AI 友好）:visible_only 无匹配时重跑不过滤查询。

        命中=元素存在但 IsOffscreen=True——为 NOT_FOUND 消息追加自愈指引，
        免得 AI 在「元素消失」vs「元素不可见」之间瞎猜（两者处置不同）。
        """
        if not self._find_elements(root, name=name, automation_id=automation_id,
                                   control_type=control_type):
            return ""
        return ("提示: 该元素存在但当前不可见（IsOffscreen=True，常见于折叠"
                "菜单/未展开面板/隐藏标签页），点击路径已拒绝以防误点。"
                "下一步: 先展开其所属容器后重新取树，或改用键盘路径"
                "（key/type_text），或 get_ui_tree 确认可见性。")

    def _candidate_names(self, root) -> str:
        names: list[str] = []
        for s in self._iter_summaries(root):             # ISS-0008 P4：摘要复用
            if s["name"] and s["name"] not in names:
                names.append(s["name"])
            if len(names) >= 10:
                break
        return ", ".join(names) or "(无可交互元素)"

    def _element_summary(self, element) -> dict:
        return {"name": element.Name, "control_type": element.ControlTypeName,
                "automation_id": element.AutomationId}

    def _capture(self, region: dict) -> Image.Image:
        """区域截图（shot_fn 为测试接缝；默认 mss 实拍;委托 screens）。"""
        return screens._capture(self, region)

    @staticmethod
    def _region_dict(rect) -> dict:
        return screens._region_dict(rect)

    @staticmethod
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

    def _click_element(self, params: dict, hwnd: int) -> dict:
        som_id = params.get("som_id")
        control_type = params.get("control_type")
        # ISS-0044 G-01:som_id 与 control_type 为两条寻址路径,互斥
        if som_id is not None and control_type:
            raise ExecutorError(
                INVALID_PARAMS,
                "som_id 与 control_type 为两条寻址路径,不可同传")
        if som_id is not None:
            entry = self._som_cache.get(int(som_id))
            if (entry is not None and entry["hwnd"] == hwnd
                    and self._clock() <= entry["expires"]):
                root = self._element_root(hwnd)
                element = self._resolve_unique_element(
                    root, name=entry["name"] or None,
                    automation_id=entry["automation_id"] or None,
                    visible_only=True)       # ISS-0091 整改③:点击路径
            else:
                # REQ-003 §5.3:som 表未命中 → 查 detect 编号表(诊断分支)。
                # **零点击保证**:本分支在 _element_root/_resolve_unique_element
                # /_invoke_element 之前返回,物理上无点击可能
                dentry = self._detect_cache.get(int(som_id))
                if (dentry is not None and dentry["hwnd"] == hwnd
                        and self._clock() <= dentry["expires"]):
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
            root = self._element_root(hwnd)
            element = self._resolve_typed_element(
                root, control_type=control_type, name=params.get("name"),
                index=params.get("index"),
                visible_only=True)           # ISS-0091 整改③:点击路径
        else:
            root = self._element_root(hwnd)
            element = self._resolve_unique_element(
                root, name=params.get("name"),
                automation_id=params.get("automation_id"),
                visible_only=True)           # ISS-0091 整改③:点击路径
        self._invoke_element(element, hwnd)
        return {"status": "ok", "element": self._element_summary(element)}

    def _resolve_typed_element(self, root, *, control_type, name=None,
                               index=None, visible_only=False):
        """ISS-0044 G-01:类型+序号寻址——类型过滤(可与 name 交集)后按序取。"""
        matches = self._find_elements(root, name=name,
                                      control_type=control_type,
                                      visible_only=visible_only)
        if not matches:
            hint = (self._hidden_hint(root, name=name,
                                      control_type=control_type)
                    if visible_only else "")
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                f"元素不存在（类型 {control_type!r}"
                f"{f', 名称 {name!r}' if name else ''}）。"
                f"{hint}"
                f"候选元素: {self._candidate_names(root)}")
        i = index if index is not None else 0
        if isinstance(i, bool) or not isinstance(i, int) or i < 0:
            raise ExecutorError(INVALID_PARAMS, f"index 非法: {i!r}")
        if i >= len(matches):
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                f"类型 {control_type!r} 命中 {len(matches)} 个,"
                f"index={i} 越界(0~{len(matches) - 1})")
        return matches[i]

    def _invoke_element(self, element, hwnd: int | None = None) -> None:
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
        rect = self._node_rect(element)
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
            self._check_point(hwnd, x, y)
            if not self._activate_if_needed(hwnd):
                raise ExecutorError(WINDOW_GONE, "窗口无法前置，元素点击中止（防误射）")
            self._check_occlusion(hwnd, x, y)
        self._pixel_click(x, y)

    def _pixel_click(self, x: int, y: int) -> None:
        _failsafe_guard(pyautogui.click, x, y)

    def _type_element(self, params: dict, hwnd: int) -> dict:
        root = self._element_root(hwnd)
        element = self._resolve_unique_element(
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
        return {"status": "ok", "element": self._element_summary(element)}

    def _wait_for_element(self, params: dict, hwnd: int) -> dict:
        limit = min(params.get("timeout") or 10.0, self._wait_max)
        deadline = self._clock() + limit
        cond = params.get("name"), params.get("automation_id")
        while True:
            root = self._element_root(hwnd)
            matches = self._find_elements(root, name=cond[0], automation_id=cond[1])
            if matches:
                element = matches[0]
                return {"status": "ok", "elapsed": round(limit - (deadline - self._clock()), 3),
                        "element": self._element_summary(element)}
            if self._clock() >= deadline:
                raise ExecutorError(
                    TIMEOUT,
                    f"等待超时：未发现元素（name={cond[0]!r}, "
                    f"automation_id={cond[1]!r}）")
            time.sleep(self._poll)

    def _click(self, x: int, y: int, hwnd: int,
               button: str = "left", clicks: int = 1) -> dict:
        if button not in MOUSE_BUTTONS:
            raise ExecutorError(INVALID_PARAMS, f"button 非法: {button}")
        if isinstance(clicks, bool) or not isinstance(clicks, int) \
                or clicks not in (1, 2, 3):
            raise ExecutorError(INVALID_PARAMS, f"clicks 非法(1/2/3): {clicks}")
        self._check_point(hwnd, x, y)
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        self._check_occlusion(hwnd, x, y)     # ISS-0017 C：激活后再验遮挡
        _failsafe_guard(pyautogui.click, x, y, button=button, clicks=clicks)
        return {"status": "ok"}

    # ---------- REQ-001 原语层:mouse_down/mouse_up/hold ----------

    def _mouse_down(self, button: str, hwnd: int) -> dict:
        """按下指定键并登记;位置无关(光标态操作),不激活不拍图(MOUSE-14)。"""
        self._mouse.press(button)
        pyautogui.mouseDown(button=button)
        return {"status": "ok", "button": button,
                "pressed": self._mouse.snapshot()}

    def _mouse_up(self, button: str, hwnd: int) -> dict:
        """抬起指定键并核销;无对应按下时 no-op(released=false,防重试误抬)。"""
        if self._mouse.release(button):
            pyautogui.mouseUp(button=button)
            return {"status": "ok", "button": button, "released": True}
        return {"status": "ok", "button": button, "released": False}

    def _hold(self, duration_ms: int, button: str, hwnd: int) -> dict:
        """按住不放:按下→等待→抬起;任何异常路径键必抬(finally)。"""
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) \
                or not (1 <= duration_ms <= 30000):
            raise ExecutorError(
                INVALID_PARAMS,
                f"duration_ms 越界(1~30000): {duration_ms}")
        self._mouse.press(button)
        pyautogui.mouseDown(button=button)
        try:
            time.sleep(duration_ms / 1000)
        finally:
            pyautogui.mouseUp(button=button)
            self._mouse.release(button)
        return {"status": "ok", "button": button, "held_ms": duration_ms}

    def _mouse_watchdog_tick(self) -> None:
        """看门狗单轮检测(公开接缝:测试手动驱动;生产由装配方启动线程)。"""
        self._mouse_watchdog.tick()

    def _force_release_button(self, button: str) -> None:
        pyautogui.mouseUp(button=button)

    def _force_release_all(self) -> None:
        """安全网①:estop 冻结监听器——强制抬起全部按下键。"""
        for b in self._mouse.release_all():
            try:
                pyautogui.mouseUp(button=b)
            except Exception:                   # noqa: BLE001
                pass

    def _click_text(self, params: dict, hwnd: int) -> dict:
        """ISS-0021 A：按文字点击——前置实拍→OCR→换算→与 click 同安全链。

        失败分类 fail-closed（未命中/多命中/越窗/参数非法）一律零点击；
        落点复用 _check_point/_check_occlusion 防误射管线。
        """
        button = params.get("button", "left")
        if button not in MOUSE_BUTTONS:
            raise ExecutorError(INVALID_PARAMS, f"button 非法: {button}")
        clicks = params.get("clicks", 1)
        if isinstance(clicks, bool) or not isinstance(clicks, int) \
                or clicks not in (1, 2, 3):
            raise ExecutorError(INVALID_PARAMS, f"clicks 非法(1/2/3): {clicks}")
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        rect = self._binding_rect(hwnd)
        if rect is None:
            raise ExecutorError(WINDOW_GONE, "绑定窗口矩形不可得（可能已消失）")
        region = self._resolve_region("window", None, hwnd)
        ocr = self.ocr(region)                      # 实拍+识别（懒加载）
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
        self._check_point(hwnd, x, y)
        self._check_occlusion(hwnd, x, y)     # 与 click 同遮挡校验
        _failsafe_guard(pyautogui.click, x, y, button=button, clicks=clicks)
        return {"status": "ok", "target": [x, y],
                "matched": payload["matched"]}

    def _drag(self, start, end, hwnd: int, button: str = "left",
              via=None, duration_ms=None) -> dict:
        """REQ-004:via=途经点列表(≤32,超限 fail-closed;各途经点沿用
        终点同闸逐屏判定,越界拒绝零派发);duration_ms=总时长(按弧长
        比例分配各段,匀速);缺省=现行为直线两点 24 步×0.02 逐点不变。"""
        if button not in MOUSE_BUTTONS:
            raise ExecutorError(INVALID_PARAMS, f"button 非法: {button}")
        self._check_point(hwnd, *start)   # 起点防误射不变(绑定窗内)
        use_traj = bool(via) or duration_ms is not None
        if use_traj:
            if via is not None and len(via) > 32:
                raise ExecutorError(
                    INVALID_PARAMS,
                    f"via 途经点超限（{len(via)} > 32，fail-closed）")
            anchors = [list(start)] + [list(p) for p in (via or [])] + [list(end)]
            for p in anchors[1:]:
                self._check_drag_end(*p)  # 途经点与终点同闸(逐屏判定)
        else:
            self._check_drag_end(*end)        # ISS-0047:终点=虚拟桌面逐屏判定
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        self._check_occlusion(hwnd, *start)   # ISS-0017 C：激活后再验遮挡
        # ISS-0056:段级收敛——按下/移动/抬起序列整体经单点 guard,
        # 内层 finally(抬键+核销)语义不变(FAILSAFE 触发也先抬键)
        def _do_drag():
            pyautogui.moveTo(*start)
            # REQ-001:按下表对称登记/核销(任意 button;安全网覆盖一切物理按下)
            self._mouse.press(button)
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
                self._mouse.release(button)
        _failsafe_guard(_do_drag)
        return {"status": "ok"}

    def _scroll(self, direction: str, amount: int, hwnd: int) -> dict:
        rect = self._probe.rect_of(hwnd)
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        if direction in ("left", "right"):
            # REQ-001 水平滚轮:left=负向,right=正向(与垂直对称)
            pyautogui.hscroll(-amount if direction == "left" else amount,
                              x=cx, y=cy)
        else:
            pyautogui.scroll(-amount if direction == "down" else amount,
                             x=cx, y=cy)
        return {"status": "ok"}

    def _key(self, raw_key: str, hwnd: int) -> dict:
        norm = normalize_key(raw_key)
        parts = [_pyauto_key_alias.get(p, p) for p in norm.split("+")]
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        def _send():
            if len(parts) == 1:
                pyautogui.press(parts[0])
            else:
                pyautogui.hotkey(*parts)
        _failsafe_guard(_send)                  # ISS-0056:收敛单点
        return {"status": "ok", "key": norm}

    def _type_text(self, text: str, hwnd: int) -> dict:
        """全量走剪贴板桥（INV-5：全程无预清空动作）。

        ISS-0100 A：逐键模拟路径废止——中文 IME 激活时按键流进组合器，
        落地内容由词库决定（demo 录制实证乱码）；任何文本一律走桥。
        ISS-0100 C：读回校验修真——比对失败重试耗尽报 TYPE_MISMATCH；
        读回三通道全灭 raise READBACK_UNAVAILABLE（fail-closed，
        不再 ok:true 放行）。
        """
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        # ISS-0104(裁定 A):首次粘贴前聚焦首个 Edit/Document 控件——
        # 窗口前台 ≠ 键盘焦点在编辑区(Win11 记事本焦点可在标签条,
        # ctrl+v 对非编辑焦点是空操作,W6 实盘)。聚焦只做一次(重贴
        # 不重复聚焦,选择态副作用最小化);无编辑控件/聚焦失败不阻断,
        # fail-closed 由读回保证(§5)。
        self._focus_first_edit(hwnd)

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
                self._activate_if_needed(hwnd)
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
                    current = self._read_edit_value(hwnd)
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
            self._walk(child, nodes, depth + 1)

    def _read_edit_value(self, hwnd: int) -> str | None:
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
        self._ensure_com()
        try:
            root = uiautomation.ControlFromHandle(hwnd)
            values: list[str] = []
            has_edit = False
            for node in self._iter_controls(root, depth=0):
                if node.ControlTypeName in _EDIT_TYPE_NAMES:
                    has_edit = True
                    value = self._node_text(node)
                    if value:
                        values.append(value)
            if values:
                return "\n".join(values)
            if has_edit:
                return self._read_via_selection()
            return None
        except Exception:
            return None

    def _focus_first_edit(self, hwnd: int) -> None:
        """粘贴前聚焦（ISS-0104 §5）：窗口内第一个 Edit/Document 控件
        调 UIA SetFocus（复用 _iter_controls+_EDIT_TYPE_NAMES 枚举,
        与读回通道同一控件面）。无命中节点/任何异常吞掉不阻断——
        聚焦是成功率优化,fail-closed 由读回校验保证;
        选择态副作用（如全选）属裁定接受的交互副作用（§5 登记）。

        ISS-0106:首行 _ensure_com()(同 _read_edit_value 的绕缝修复)。
        """
        self._ensure_com()
        try:
            root = uiautomation.ControlFromHandle(hwnd)
            for node in self._iter_controls(root, depth=0):
                if node.ControlTypeName in _EDIT_TYPE_NAMES:
                    node.SetFocus()
                    return
        except Exception:                           # noqa: BLE001
            pass

    @staticmethod
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

    @staticmethod
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

    def _iter_controls(self, control, depth: int = 0):
        if control is None or depth > _UI_TREE_MAX_DEPTH:
            return
        yield control
        try:
            children = control.GetChildren()
        except Exception:
            return
        for child in children:
            yield from self._iter_controls(child, depth + 1)

    def _iter_summaries(self, control, depth: int = 0):
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
                "rect": self._node_rect(control),
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
            yield from self._iter_summaries(child, depth + 1)
