"""执行层核心（详细设计 §9）：真实桌面驱动。

只执行、不判断（安全判定全在强制层）。写路径动手前复查冻结标志（双检查）。
驱动：截图 mss；键鼠 pyautogui；UIA uiautomation；剪贴板 pyperclip；窗口探测 ctypes。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import mss
import mss.tools
import pyautogui
import pyperclip
import uiautomation

from ..errors import (EMERGENCY_STOP, INTERNAL_ERROR, OUT_OF_BOUNDS, TIMEOUT,
                      WINDOW_GONE, ExecutorError)
from ..policy import normalize_key
from .probe import DesktopProbe

_NOT_WIRED = {
    "get_clickable_map", "ocr", "template_match",
}  # 驱动未包含在 M1 构建（OCR/模板匹配/SoM 见里程碑 M3）

_pyauto_key_alias = {"escape": "esc"}


class Executor:
    """执行层公开入口。"""

    def __init__(self, estop, audit_dir: str, poll_interval: float = 0.5,
                 wait_timeout_max: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self._probe = DesktopProbe()
        self._estop = estop
        self._shots_dir = Path(audit_dir) / "shots"
        self._poll = poll_interval
        self._wait_max = wait_timeout_max
        self._clock = clock
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
        before = self._evidence_shot(tool, "before")
        result = self._dispatch(tool, params, hwnd)
        after = self._evidence_shot(tool, "after")
        result = dict(result or {})
        result["before_shot"] = before
        result["after_shot"] = after
        return result

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
        return {"path": str(path), "width": region["width"], "height": region["height"]}

    def find_windows(self, title=None, process=None, hwnd=None) -> list[dict]:
        return self._probe.find_windows(title=title, process=process, hwnd=hwnd)

    def get_ui_tree(self, window) -> dict:
        hwnd = self._resolve_window(window)
        root = uiautomation.ControlFromHandle(hwnd)
        if root is None:
            raise ExecutorError(WINDOW_GONE, "目标窗口已消失")
        nodes: list[dict] = []
        self._walk(root, nodes, depth=0)
        return {"hwnd": hwnd, "elements": nodes, "truncated": len(nodes) >= 800}

    def get_cursor(self) -> dict:
        pos = pyautogui.position()
        return {"x": pos.x, "y": pos.y}

    def get_clipboard(self) -> dict:
        return {"text": pyperclip.paste()}

    def move(self, x: int, y: int) -> dict:
        """移动鼠标（L1，无写入）。"""
        pyautogui.moveTo(x, y)
        return {"status": "ok"}

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
        raise ExecutorError(INTERNAL_ERROR, f"工具 {tool} 的执行驱动未接线")

    def _click(self, x: int, y: int, hwnd: int) -> dict:
        self._check_point(hwnd, x, y)
        self._activate_if_needed(hwnd)
        try:
            pyautogui.click(x, y)
        except pyautogui.FailSafeException as e:
            raise ExecutorError(EMERGENCY_STOP, f"pyautogui FAILSAFE 触发: {e}") from e
        return {"status": "ok"}

    def _drag(self, start, end, hwnd: int) -> dict:
        self._check_point(hwnd, *start)
        self._check_point(hwnd, *end)
        self._activate_if_needed(hwnd)
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
        self._activate_if_needed(hwnd)
        pyautogui.scroll(-amount if direction == "down" else amount, x=cx, y=cy)
        return {"status": "ok"}

    def _key(self, raw_key: str, hwnd: int) -> dict:
        norm = normalize_key(raw_key)
        parts = [_pyauto_key_alias.get(p, p) for p in norm.split("+")]
        self._activate_if_needed(hwnd)
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
        self._activate_if_needed(hwnd)
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

    def _activate_if_needed(self, hwnd: int) -> None:
        """仅当目标窗口不在前台时才前置——避免重激活导致弹出的菜单/画廊被销毁。"""
        if hwnd is not None and not self._probe.is_foreground(hwnd):
            self._probe.activate(hwnd)

    def _check_point(self, hwnd: int, x: int, y: int) -> None:
        rect = self._probe.rect_of(hwnd)   # 执行时刻矩形
        if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
            raise ExecutorError(OUT_OF_BOUNDS, "落点在绑定窗口矩形外")

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

    def _save_shot(self, region: dict, tag: str) -> Path:
        day = time.strftime("%Y%m%d")
        out_dir = self._shots_dir / day
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{time.strftime('%H%M%S')}_{tag}_{int(time.time()*1000)%100000}.png"
        with mss.MSS() as sct:
            img = sct.grab(region)
            mss.tools.to_png(img.rgb, img.size, output=str(path))
        return path

    def _evidence_shot(self, tool: str, tag: str) -> str:
        try:
            with mss.MSS() as sct:
                mon = sct.monitors[0]
            return str(self._save_shot(mon, f"{tag}_{tool}"))
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
                left, top, right, bottom = rect[0], rect[1], rect[2], rect[3]
            nodes.append({
                "name": control.Name,
                "control_type": control.ControlTypeName,
                "automation_id": control.AutomationId,
                "rect": [left, top, right, bottom],
                "interactable": bool(control.IsEnabled),
                "depth": depth,
            })
        except Exception:
            return
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

    def _iter_controls(self, control, depth: int):
        if control is None or depth > 8:
            return
        yield control
        try:
            children = control.GetChildren()
        except Exception:
            return
        for child in children:
            yield from self._iter_controls(child, depth + 1)
