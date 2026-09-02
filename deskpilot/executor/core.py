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

from ..errors import (ELEMENT_AMBIGUOUS, ELEMENT_DISABLED, ELEMENT_NOT_FOUND,
                      ELEMENT_UNSUPPORTED, EMERGENCY_STOP, INTERNAL_ERROR,
                      OUT_OF_BOUNDS, TIMEOUT, WINDOW_GONE, WINDOW_OCCLUDED,
                      ExecutorError)
from ..policy import normalize_key
from .probe import DesktopProbe

_NOT_WIRED = {
    "get_clickable_map", "ocr", "template_match",
}  # 驱动未包含在 M1 构建（OCR/模板匹配/SoM 见里程碑 M3）

_pyauto_key_alias = {"escape": "esc"}


class Executor:
    """执行层公开入口。"""

    def __init__(self, estop, audit_dir: str, poll_interval: float = 0.5,
                 wait_timeout_max: float = 300.0, clock: Callable[[], float] = time.monotonic,
                 probe=None, element_source=None, shot_fn=None, ocr_engine=None):
        self._probe = probe if probe is not None else DesktopProbe()
        self._estop = estop
        self._shots_dir = Path(audit_dir) / "shots"
        self._poll = poll_interval
        self._wait_max = wait_timeout_max
        self._clock = clock
        self._element_source = element_source   # UIA 根控件工厂（可注入，测试接缝）
        self._shot_fn = shot_fn                 # 区域截图工厂（可注入，测试接缝）
        self._ocr_engine = ocr_engine           # OCR 引擎（可注入，测试接缝）
        self.ocr_factory = None                 # ISS-0008 §6：OCR 懒加载工厂（公开属性）
        self._ocr_lock = threading.Lock()       # ISS-0008 P2：懒初始化一次性锁
        self._ocr_failed: str | None = None     # ISS-0008 P2：初始化失败记忆化
        self._som_cache: dict[int, dict] = {}   # SoM 编号缓存（§9.9）
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
        before = self._evidence_shot(tool, "before", rect)
        try:
            result = self._dispatch(tool, params, hwnd)
        except ExecutorError:
            raise
        except pyautogui.FailSafeException as e:
            # ISS-0009 §6 C：三方异常收敛（光标角落 FAILSAFE 语义即急停）
            raise ExecutorError(EMERGENCY_STOP,
                                f"pyautogui FAILSAFE 触发: {e}") from e
        except Exception as e:
            # ISS-0009 §6 C：未知异常不再裸抛（防 handler/进程断连）
            raise ExecutorError(INTERNAL_ERROR,
                                f"执行层未处理异常: {e}") from e
        after = self._evidence_shot(tool, "after", rect)
        result = dict(result or {})
        result["before_shot"] = before
        result["after_shot"] = after
        return result

    def _binding_rect(self, hwnd) -> tuple | None:
        """绑定窗口矩形（无绑定或探测失败回退 None → 证据图转全桌面）。"""
        if hwnd is None:
            return None
        try:
            return self._probe.rect_of(hwnd)
        except Exception:
            return None

    def focused_control_type(self) -> str | None:
        """查询当前焦点元素的 UIA 控件类型；查询失败返回 None（fail-closed 由调用方处理）。"""
        try:
            control = uiautomation.GetFocusedControl()
            return control.ControlTypeName if control else None
        except Exception:
            return None

    # ---------- 感知（L0，tools 层直调） ----------

    def screenshot(self, scope: str, rect=None, window=None) -> dict:
        region = self._resolve_region(scope, rect, window)
        path = self._save_shot(region, "sense")
        out = {"path": str(path), "width": region["width"],
               "height": region["height"]}
        if scope == "fullscreen":
            # ISS-0007 C：坐标系声明 + 每屏边界列表
            from ..monitors import enum_monitors
            out["coord_space"] = "virtual_desktop"
            out["monitors"] = enum_monitors()
        return out

    def find_windows(self, title=None, process=None, hwnd=None) -> list[dict]:
        return self._probe.find_windows(title=title, process=process, hwnd=hwnd)

    def get_ui_tree(self, window) -> dict:
        hwnd = self._resolve_window(window)
        root = self._element_root(hwnd)      # 走元素源接缝（测试可注入）
        nodes: list[dict] = []
        self._walk(root, nodes, depth=0)
        # ISS-0007 C：坐标系声明（rect 为虚拟桌面坐标，可含负值）
        return {"hwnd": hwnd, "elements": nodes,
                "truncated": len(nodes) >= 800,
                "coord_space": "virtual_desktop"}

    def get_cursor(self) -> dict:
        pos = pyautogui.position()
        return {"x": pos.x, "y": pos.y}

    def get_clipboard(self) -> dict:
        return {"text": pyperclip.paste()}

    def move(self, x: int, y: int) -> dict:
        """移动鼠标（L1，无写入）。"""
        pyautogui.moveTo(x, y)
        return {"status": "ok"}

    def ocr(self, source) -> dict:
        """文字识别（§12.6）：图像路径来源直读；区域来源实拍后识别。

        ISS-0008 P2 懒加载：引擎首次使用时经 ocr_factory 恰好初始化一次
        （线程安全）；初始化失败记忆化，后续调用直接显式报错（INV-7）。
        """
        if self._ocr_engine is None:
            self._ensure_ocr_engine()
        if isinstance(source, str):
            try:
                img = Image.open(source)
            except OSError as e:
                raise ExecutorError(INTERNAL_ERROR, f"OCR 源图像不可读: {e}") from e
        else:
            img = self._capture(self._region_dict(source))
        items = self._ocr_engine(img)
        return {"items": items, "count": len(items)}

    def _ensure_ocr_engine(self) -> None:
        """懒初始化 OCR 引擎（ISS-0008 §6）：恰好一次；失败记忆化。"""
        if self._ocr_failed is not None:
            raise ExecutorError(INTERNAL_ERROR,
                                f"OCR 引擎不可用: {self._ocr_failed}")
        with self._ocr_lock:
            if self._ocr_engine is not None:
                return
            if self._ocr_failed is not None:
                raise ExecutorError(INTERNAL_ERROR,
                                    f"OCR 引擎不可用: {self._ocr_failed}")
            if self.ocr_factory is None:
                self._ocr_failed = ("未装配 ocr_factory"
                                    "（请安装 rapidocr-onnxruntime）")
                raise ExecutorError(INTERNAL_ERROR,
                                    f"OCR 引擎不可用: {self._ocr_failed}")
            try:
                self._ocr_engine = self.ocr_factory()
            except Exception as e:
                self._ocr_failed = str(e)
                raise ExecutorError(INTERNAL_ERROR,
                                    f"OCR 引擎不可用: {e}") from e

    def template_match(self, template: str, scope, threshold: float = 0.8) -> dict:
        """模板匹配（§12.6）：在屏幕范围搜索模板，未达阈值如实返回最高置信度。"""
        tpl = cv2.imread(template, cv2.IMREAD_COLOR)
        if tpl is None:
            raise ExecutorError(INTERNAL_ERROR, f"模板图像不可读: {template}")
        scene_img = self._capture(self._region_dict(scope))
        scene = np.asarray(scene_img.convert("RGB"))[:, :, ::-1]
        if scene.shape[0] < tpl.shape[0] or scene.shape[1] < tpl.shape[1]:
            return {"found": False, "best_confidence": 0.0, "matches": []}
        res = cv2.matchTemplate(scene, tpl, cv2.TM_CCOEFF_NORMED)
        h, w = tpl.shape[:2]
        best = float(res.max())
        matches: list[dict] = []
        if best >= threshold:
            # 高于阈值的全部峰，按模板尺寸做非极大值抑制
            suppressed: set[tuple[int, int]] = set()
            peaks = sorted(zip(*np.where(res >= threshold)),
                           key=lambda p: -res[p[0], p[1]])
            for y, x in peaks:
                if (y, x) in suppressed:
                    continue
                for dy in range(max(0, y - h), min(res.shape[0], y + h + 1)):
                    for dx in range(max(0, x - w), min(res.shape[1], x + w + 1)):
                        suppressed.add((dy, dx))
                matches.append({"x": int(x + w // 2), "y": int(y + h // 2),
                                "confidence": float(res[y, x])})
        return {"found": bool(matches), "best_confidence": best,
                "matches": matches[:20]}

    def get_clickable_map(self, window) -> dict:
        """SoM 标注（§12.6）：可交互非零面积元素按阅读顺序编号入图，
        对照表连同窗口句柄存入缓存（60 秒有效）。"""
        hwnd = self._resolve_window(window)
        root = self._element_root(hwnd)
        wl, wt, wr, wb = self._probe.rect_of(hwnd)
        # ISS-0008 P4：每节点属性一次成型（同名属性不重复读 COM）
        interactable = []
        for s in self._iter_summaries(root):
            if not s["enabled"]:
                continue
            rect = s["rect"]
            if rect is None or rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
                continue
            interactable.append(s)
        interactable.sort(key=lambda s: (s["rect"][1], s["rect"][0]))
        img = self._capture({"left": wl, "top": wt,
                             "width": wr - wl, "height": wb - wt})
        draw = ImageDraw.Draw(img)
        entries: list[dict] = []
        now = self._clock()
        for i, s in enumerate(interactable, start=1):
            l, t, r, b = s["rect"]
            rel = [l - wl, t - wt, r - wl, b - wt]
            draw.rectangle(rel, outline=(255, 60, 60), width=3)
            draw.text((rel[0] + 2, max(0, rel[1] - 16)), str(i), fill=(255, 0, 0))
            entries.append({"id": i, "name": s["name"],
                            "control_type": s["control_type"],
                            "automation_id": s["automation_id"],
                            "rect": [l, t, r, b]})
            self._som_cache[i] = {"hwnd": hwnd, "name": s["name"],
                                  "automation_id": s["automation_id"],
                                  "expires": now + 60.0}
        out = self._shots_dir / time.strftime("%Y%m%d")
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{time.strftime('%H%M%S')}_som_{int(time.time()*1000)%100000}.png"
        img.save(path)
        return {"path": str(path), "count": len(entries), "entries": entries}

    def capture_approval_shot(self, rect) -> str:
        """审批用目标窗口实拍（闸四）：按绑定矩形截图并落盘，返回路径。"""
        l, t, r, b = (int(v) for v in rect)
        region = {"left": l, "top": t, "width": r - l, "height": b - t}
        if region["width"] <= 0 or region["height"] <= 0:
            raise ExecutorError(INTERNAL_ERROR, f"目标窗口矩形无效: {rect}")
        return str(self._save_shot(region, "approval"))

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
            return self._click(params["x"], params["y"], hwnd)
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
            return self._drag(params["start"], params["end"], hwnd)
        if tool == "activate_window":
            ok = self._activate_if_needed(hwnd)
            if not ok:
                raise ExecutorError(WINDOW_GONE, "窗口无法前置（可能已消失）")
            return {"status": "ok"}
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

    def _find_elements(self, root, *, name=None, automation_id=None) -> list:
        """按名称/自动化标识在绑定窗口树内查找（§14.7 定位条件）。

        WinUI 树存在幽灵重复（同名同型同矩形可见/离屏两份）——按
        名称+自动化标识+矩形三元组去重，视为同一元素。
        """
        matches = []
        seen: set[tuple] = set()
        for s in self._iter_summaries(root):           # ISS-0008 P4：摘要复用
            if name is not None and automation_id is not None:
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
            matches.append(s["control"])
        return matches

    def _resolve_unique_element(self, root, *, name=None, automation_id=None):
        """唯一性解析：不存在 / 多匹配 / 禁用逐级显式报错（§14.7 流程）。"""
        matches = self._find_elements(root, name=name, automation_id=automation_id)
        if not matches:
            raise ExecutorError(
                ELEMENT_NOT_FOUND,
                f"元素不存在（条件 name={name!r}, automation_id={automation_id!r}）。"
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
        """区域截图（shot_fn 为测试接缝；默认 mss 实拍）。"""
        if self._shot_fn is not None:
            return self._shot_fn(region)
        with mss.mss() as sct:
            shot = sct.grab(region)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    @staticmethod
    def _region_dict(rect) -> dict:
        return {"left": int(rect[0]), "top": int(rect[1]),
                "width": int(rect[2]), "height": int(rect[3])}

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
        if som_id is not None:
            entry = self._som_cache.get(int(som_id))
            if (entry is None or entry["hwnd"] != hwnd
                    or self._clock() > entry["expires"]):
                raise ExecutorError(
                    ELEMENT_NOT_FOUND,
                    "SoM 编号已失效或不属于当前绑定窗口，"
                    "请重新调用 get_clickable_map 取图")
            root = self._element_root(hwnd)
            element = self._resolve_unique_element(
                root, name=entry["name"] or None,
                automation_id=entry["automation_id"] or None)
        else:
            root = self._element_root(hwnd)
            element = self._resolve_unique_element(
                root, name=params.get("name"),
                automation_id=params.get("automation_id"))
        self._invoke_element(element, hwnd)
        return {"status": "ok", "element": self._element_summary(element)}

    def _invoke_element(self, element, hwnd: int | None = None) -> None:
        """元素激活：Invoke 优先，SelectionItem 选择模式次之，像素点击兜底。
        像素兜底前必须成功前置绑定窗口（fail-closed 防误射）。"""
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
        if hwnd is not None and not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，元素点击中止（防误射）")
        self._pixel_click((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)

    def _pixel_click(self, x: int, y: int) -> None:
        try:
            pyautogui.click(x, y)
        except pyautogui.FailSafeException as e:
            raise ExecutorError(EMERGENCY_STOP, f"pyautogui FAILSAFE 触发: {e}") from e

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
                f"请改用 type_text 走键盘路径输入")
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

    def _click(self, x: int, y: int, hwnd: int) -> dict:
        self._check_point(hwnd, x, y)
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        self._check_occlusion(hwnd, x, y)     # ISS-0017 C：激活后再验遮挡
        try:
            pyautogui.click(x, y)
        except pyautogui.FailSafeException as e:
            raise ExecutorError(EMERGENCY_STOP, f"pyautogui FAILSAFE 触发: {e}") from e
        return {"status": "ok"}

    def _drag(self, start, end, hwnd: int) -> dict:
        self._check_point(hwnd, *start)
        self._check_point(hwnd, *end)
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        self._check_occlusion(hwnd, *start)   # ISS-0017 C：激活后再验遮挡
        try:
            pyautogui.moveTo(*start)
            pyautogui.mouseDown()
            time.sleep(0.15)                      # 让目标应用识别按下
            steps = 24                            # 分段慢移，保证轨迹被采到
            for i in range(1, steps + 1):
                x = start[0] + (end[0] - start[0]) * i / steps
                y = start[1] + (end[1] - start[1]) * i / steps
                pyautogui.moveTo(x, y, duration=0.02)
            time.sleep(0.1)
            pyautogui.mouseUp()
        except pyautogui.FailSafeException as e:
            raise ExecutorError(EMERGENCY_STOP, f"pyautogui FAILSAFE 触发: {e}") from e
        return {"status": "ok"}

    def _scroll(self, direction: str, amount: int, hwnd: int) -> dict:
        rect = self._probe.rect_of(hwnd)
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        pyautogui.scroll(-amount if direction == "down" else amount, x=cx, y=cy)
        return {"status": "ok"}

    def _key(self, raw_key: str, hwnd: int) -> dict:
        norm = normalize_key(raw_key)
        parts = [_pyauto_key_alias.get(p, p) for p in norm.split("+")]
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        try:
            if len(parts) == 1:
                pyautogui.press(parts[0])
            else:
                pyautogui.hotkey(*parts)
        except pyautogui.FailSafeException as e:
            raise ExecutorError(EMERGENCY_STOP, f"pyautogui FAILSAFE 触发: {e}") from e
        return {"status": "ok", "key": norm}

    def _type_text(self, text: str, hwnd: int) -> dict:
        """ASCII 逐键模拟；非 ASCII 走剪贴板桥（INV-5：全程无预清空动作）。"""
        if not self._activate_if_needed(hwnd):
            raise ExecutorError(WINDOW_GONE, "窗口无法前置，输入中止（防误射）")
        if all(ord(c) < 128 for c in text):
            pyautogui.write(text, interval=0.01)
            return {"status": "ok", "mode": "keyboard"}

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
                time.sleep(0.3)
                current = self._read_edit_value(hwnd)
                if current is None:
                    # 读回校验不可用：只粘贴一次即停止，避免重复粘贴
                    note = "读回校验不可用（目标无 UIA 值模式）"
                    break
                if text in current:
                    note = "读回校验一致"
                    break
                attempts += 1
                if attempts >= 2:
                    raise ExecutorError(INTERNAL_ERROR, "粘贴读回校验不一致且重试耗尽")
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
        if hwnd is None:
            return True
        if self._probe.is_foreground(hwnd):
            return True
        return bool(self._probe.activate(hwnd))

    def _check_point(self, hwnd: int, x: int, y: int) -> None:
        rect = self._probe.rect_of(hwnd)   # 执行时刻矩形
        if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
            raise ExecutorError(OUT_OF_BOUNDS, "落点在绑定窗口矩形外")

    def _check_occlusion(self, hwnd: int, x: int, y: int) -> None:
        """ISS-0017 C：遮挡判定（激活后调用）——落点处顶层窗口非目标/
        非其子窗口则拒绝（fail-closed,绝不盲打）。"""
        u32 = _occlusion_user32
        if u32 is None:
            import ctypes
            u32 = ctypes.windll.user32
        from ctypes import wintypes
        pt_hwnd = u32.WindowFromPoint(wintypes.POINT(x, y))
        if pt_hwnd != hwnd and not u32.IsChild(hwnd, pt_hwnd):
            raise ExecutorError(
                WINDOW_OCCLUDED, "落点被其他窗口遮挡，请先前置目标窗口")

    def _resolve_window(self, window) -> int:
        if isinstance(window, int):
            hwnd = window
        else:
            found = self._probe.find_windows(title=str(window))
            if not found:
                raise ExecutorError(WINDOW_GONE, f"找不到窗口: {window}")
            hwnd = found[0]["hwnd"]
        if not self._probe.hwnd_alive(hwnd):
            raise ExecutorError(WINDOW_GONE, "目标窗口已消失")
        return hwnd

    def _resolve_region(self, scope: str, rect, window) -> dict:
        if scope == "fullscreen":
            with mss.MSS() as sct:
                mon = sct.monitors[0]
            return {"left": mon["left"], "top": mon["top"],
                    "width": mon["width"], "height": mon["height"]}
        if scope == "region":
            return {"left": int(rect[0]), "top": int(rect[1]),
                    "width": int(rect[2]), "height": int(rect[3])}
        if scope == "window":
            hwnd = self._resolve_window(window)
            left, top, right, bottom = self._probe.rect_of(hwnd)
            return {"left": left, "top": top,
                    "width": right - left, "height": bottom - top}
        raise ExecutorError(INTERNAL_ERROR, f"未知截图范围: {scope}")

    def _save_shot(self, region: dict, tag: str, fmt: str = "PNG") -> Path:
        day = time.strftime("%Y%m%d")
        # ISS-0018 A：返回绝对路径——客户端无需猜测基准目录
        out_dir = (self._shots_dir / day).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        if fmt == "JPEG":                         # ISS-0008 P3：证据图 JPEG 质量 80
            path = out_dir / f"{time.strftime('%H%M%S')}_{tag}_{int(time.time()*1000)%100000}.jpg"
            img = self._capture(region)
            img.convert("RGB").save(path, "JPEG", quality=80)
            return path
        path = out_dir / f"{time.strftime('%H%M%S')}_{tag}_{int(time.time()*1000)%100000}.png"
        with mss.MSS() as sct:
            img = sct.grab(region)
            mss.tools.to_png(img.rgb, img.size, output=str(path))
        return path

    def _evidence_shot(self, tool: str, tag: str, rect: tuple | None = None) -> str:
        """写操作证据图（ISS-0008 P3）：有绑定矩形取绑定窗口区域，否则虚拟桌面全域。"""
        try:
            if rect is not None:
                l, t, r, b = (int(v) for v in rect)
                region = {"left": l, "top": t, "width": r - l, "height": b - t}
            else:
                with mss.MSS() as sct:
                    mon = sct.monitors[0]
                region = mon
            return str(self._save_shot(region, f"{tag}_{tool}", fmt="JPEG"))
        except Exception:
            return ""

    def _walk(self, control, nodes: list, depth: int) -> None:
        if depth > 10 or len(nodes) >= 800:
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
        """收集窗口内全部 Edit/Document 控件的值（拼接），供读回校验。"""
        try:
            root = uiautomation.ControlFromHandle(hwnd)
            values: list[str] = []
            for node in self._iter_controls(root, depth=0):
                if node.ControlTypeName in ("Edit", "Document"):
                    try:
                        value = node.GetValuePattern().Current.Value
                        if isinstance(value, str):
                            values.append(value)
                    except Exception:
                        continue
            return "\n".join(values) if values else None
        except Exception:
            return None

    def _iter_controls(self, control, depth: int = 0):
        if control is None or depth > 8:
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
        """
        if control is None or depth > 8:
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
        yield summary
        try:
            children = control.GetChildren()
        except Exception:
            return
        for child in children:
            yield from self._iter_summaries(child, depth + 1)
