"""感知/证据族(ISS-0055 S2):截图区域解析/捕获/落盘/指定路径护栏/
证据图/光标与剪贴板读——自 Executor 外迁。

搬函数留委托(self→ex 首参;跨族调用经 ex 委托门面回 core,
本模块不 import 任何兄弟族模块)。`_region_dict` 保持 staticmethod
形态(委托面漂移逐名核对之一)。
"""

from __future__ import annotations

import time
from pathlib import Path

import mss
import pyautogui
import pyperclip
from PIL import Image

from ..errors import (EMERGENCY_STOP, INTERNAL_ERROR, INVALID_PARAMS,
                      ExecutorError)
from ..audit_events import EV_SCREENSHOT_OVERWRITE


def get_cursor(ex) -> dict:
    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


def get_clipboard(ex) -> dict:
    return {"text": pyperclip.paste()}


def screenshot(ex, scope: str, rect=None, window=None,
               ocr: bool = False, screen=None, path=None) -> dict:
    """ISS-0102 §3.3:path 给定时改落指定路径(护栏见 _save_shot_to);
    None→受管目录落盘(现状零变化)。返回 path 恒为绝对路径。"""
    region = ex._resolve_region(scope, rect, window, screen)
    if path is None:
        path = ex._save_shot(region, "sense")
    else:
        path = ex._save_shot_to(region, path)
    out = {"path": str(path), "width": region["width"],
           "height": region["height"]}
    # ISS-0021 C：坐标系元数据——像素→虚拟桌面坐标换算全要素
    # （落盘原图 scale 恒 1.0;virtual_rect 给出偏移基准。
    # ISS-0089 A3 契约修订:MCP 内联预览图长边 >2000 时等比降采样,
    # 届时 mcp_server 把 scale_x/scale_y 改写为缩放比 f<1——
    # 虚拟坐标 = virtual_rect 原点 + 内联像素 / scale;f=1 退化原语义）
    out["virtual_rect"] = [region["left"], region["top"],
                           region["left"] + region["width"],
                           region["top"] + region["height"]]
    out["scale_x"] = 1.0
    out["scale_y"] = 1.0
    # ISS-0083 ②:coverage = 本图面积 ÷ 虚拟桌面外接矩形面积——
    # 各档统一携带,AI 可自见「这次只看到多少」;region 的用途定位
    # 是精读/局部核对,全屏/按屏才是默认路径
    from ..monitors import enum_monitors
    mons = enum_monitors()
    if mons:
        bl = min(m["rect"][0] for m in mons)
        bt = min(m["rect"][1] for m in mons)
        br = max(m["rect"][2] for m in mons)
        bb = max(m["rect"][3] for m in mons)
        out["coverage"] = (region["width"] * region["height"]
                           / ((br - bl) * (bb - bt)))
    if scope in ("fullscreen", "screen"):
        # ISS-0007 C：坐标系声明 + 每屏边界列表
        out["coord_space"] = "virtual_desktop"
        out["monitors"] = mons if mons else enum_monitors()
    # ISS-0037 A：盲眼自愈——调用方无法查看图像时的降级指引
    out["vision_note"] = (f"本响应附有截图图像内容块;若你无法查看"
                          f"图像,可改调 ocr(source={path}) 获取文字"
                          f"清单,或用 get_ui_tree/get_clickable_map "
                          f"替代感知")
    # ISS-0037 B：ocr:true 一次返回图像+文字清单（引擎复用;
    # 失败显式携带,禁止静默降级,图像本身不受损）
    if ocr:
        try:
            out["ocr_items"] = ex.ocr(str(path))["items"]
        except Exception as e:                       # noqa: BLE001
            out["ocr_error"] = {
                "code": getattr(e, "code", "INTERNAL_ERROR"),
                "message": str(e)}
    return out


def capture_approval_shot(ex, rect) -> str:
    """审批用目标窗口实拍（闸四）：按绑定矩形截图并落盘，返回路径。"""
    l, t, r, b = (int(v) for v in rect)
    region = {"left": l, "top": t, "width": r - l, "height": b - t}
    if region["width"] <= 0 or region["height"] <= 0:
        raise ExecutorError(INTERNAL_ERROR, f"目标窗口矩形无效: {rect}")
    return str(ex._save_shot(region, "approval"))


def _capture(ex, region: dict) -> Image.Image:
    """区域截图（shot_fn 为测试接缝；默认 mss 实拍）。"""
    if ex._shot_fn is not None:
        return ex._shot_fn(region)
    with mss.mss() as sct:
        shot = sct.grab(region)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _region_dict(rect) -> dict:
    return {"left": int(rect[0]), "top": int(rect[1]),
            "width": int(rect[2]), "height": int(rect[3])}


def _resolve_region(ex, scope: str, rect, window, screen=None) -> dict:
    if scope == "fullscreen":
        with mss.MSS() as sct:
            mon = sct.monitors[0]
        return {"left": mon["left"], "top": mon["top"],
                "width": mon["width"], "height": mon["height"]}
    if scope == "screen":
        # ISS-0083 ①:按屏取图——AI 只报屏号(enum_monitors 列表序号,
        # 与 fullscreen 返回的 monitors 同一清单),矩形由工具查,
        # 不再让 AI 自己算偏移;越界 fail-closed,不静默回退
        from ..monitors import enum_monitors
        mons = enum_monitors()
        if (screen is None or isinstance(screen, bool)
                or not isinstance(screen, int)
                or not (0 <= screen < len(mons))):
            raise ExecutorError(
                INVALID_PARAMS,
                f"屏号非法或越界: {screen!r};当前共 {len(mons)} 屏"
                f"(屏号 0~{len(mons) - 1},即 fullscreen 返回的 monitors 序号)")
        l, t, r, b = (int(v) for v in mons[screen]["rect"])
        return {"left": l, "top": t, "width": r - l, "height": b - t}
    if scope == "region":
        return {"left": int(rect[0]), "top": int(rect[1]),
                "width": int(rect[2]), "height": int(rect[3])}
    if scope == "window":
        hwnd = ex._resolve_window(window)
        left, top, right, bottom = ex._probe.rect_of(hwnd)
        return {"left": left, "top": top,
                "width": right - left, "height": bottom - top}
    raise ExecutorError(INTERNAL_ERROR, f"未知截图范围: {scope}")


def _save_shot(ex, region: dict, tag: str, fmt: str = "PNG") -> Path:
    day = time.strftime("%Y%m%d")
    # ISS-0018 A：返回绝对路径——客户端无需猜测基准目录
    out_dir = (ex._shots_dir / day).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "JPEG":                         # ISS-0008 P3：证据图 JPEG 质量 80
        path = out_dir / f"{time.strftime('%H%M%S')}_{tag}_{int(time.time()*1000)%100000}.jpg"
        img = ex._capture(region)
        img.convert("RGB").save(path, "JPEG", quality=80)
        return path
    path = out_dir / f"{time.strftime('%H%M%S')}_{tag}_{int(time.time()*1000)%100000}.png"
    with mss.MSS() as sct:
        img = sct.grab(region)
        mss.tools.to_png(img.rgb, img.size, output=str(path))
    return path


def _save_shot_to(ex, region: dict, target: str) -> Path:
    """ISS-0102 §3.2：screenshot path 指定路径落盘（护栏 fail-closed）。

    闸序：冻结闸（冻结期写操作全拒补破口）→ 允许根判定（相对路径锚
    allowed_roots[0]=仓库根，装配约定置首；绝对原样；统一 .resolve()
    后 is_relative_to 任一允许根，越界/穿越一律拒，消息含允许根——
    与 screen 越界 fail-closed 同码先例）→ 父目录须已存在（不替 AI
    建目录，§3.4）→ 目标已存在先审计「screenshot覆盖写」再写
    （留痕失败=写失败，AuditFailure 自然上抛）。返回目标绝对路径
    （ISS-0018 绝对语义）。指定路径文件不受受管清理约束（§3.4 入档）。
    """
    if ex._estop is not None and ex._estop.is_frozen():
        raise ExecutorError(EMERGENCY_STOP,
                            "急停冻结中，指定路径截图写操作中止")
    if not ex._allowed_roots:
        raise ExecutorError(
            INVALID_PARAMS,
            "未配置允许根（Executor 装配未接线），指定路径落盘拒绝")
    roots = [Path(r).resolve() for r in ex._allowed_roots]
    p = Path(target)
    if not p.is_absolute():
        p = roots[0] / p              # 相对路径锚仓库根（装配约定置首）
    p = p.resolve()
    if not any(p.is_relative_to(r) for r in roots):
        raise ExecutorError(
            INVALID_PARAMS,
            f"落盘路径越界（fail-closed）: {p};"
            f"允许根: {[str(r) for r in roots]}")
    if not p.parent.is_dir():
        raise ExecutorError(
            INVALID_PARAMS,
            f"落盘父目录不存在（不代为创建）: {p.parent}")
    if p.exists() and ex._audit is not None:
        ex._audit.record_event(EV_SCREENSHOT_OVERWRITE, str(p))
    with mss.MSS() as sct:
        img = sct.grab(region)
        mss.tools.to_png(img.rgb, img.size, output=str(p))
    return p


def _evidence_shot(ex, tool: str, tag: str, rect: tuple | None = None) -> str:
    """写操作证据图（ISS-0008 P3）：有绑定矩形取绑定窗口区域，否则虚拟桌面全域。"""
    try:
        if rect is not None:
            l, t, r, b = (int(v) for v in rect)
            region = {"left": l, "top": t, "width": r - l, "height": b - t}
        else:
            with mss.MSS() as sct:
                mon = sct.monitors[0]
            region = mon
        return str(ex._save_shot(region, f"{tag}_{tool}", fmt="JPEG"))
    except Exception:
        return ""
