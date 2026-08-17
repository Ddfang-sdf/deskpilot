"""启动装配程序（详细设计 §3）。

启动顺序固定：策略 → 审计目录 → 急停监听 → 内存表 → 执行层/强制层装配 → MCP 服务；
任何一步失败即拒绝启动（fail-closed）。
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from pathlib import Path

# DPI 感知必须在任何窗口/坐标 API 使用前声明（实盘教训：
# 150% 缩放主机上 UIA 物理像素与键鼠虚拟坐标错位，画笔落点全偏）。
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

from .approval import ApprovalManager, DenyAllChannel
from .audit import AuditLogger
from .binding import BindingManager
from .enforcement import Enforcement
from .errors import AuditFailure, PolicyError
from .estop import EstopMonitor
from .executor import DesktopProbe, Executor
from .mcp_server import serve
from .policy import load_policy
from .tools import ToolContext

_WM_HOTKEY = 0x0312
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_VK_F11 = 0x7A
_VK_F12 = 0x7B


def _find_policy_path() -> Path | None:
    candidates = [Path.cwd() / "policy.yml",
                  Path(sys.argv[0]).resolve().parent / "policy.yml"]
    if getattr(sys, "frozen", False):                      # PyInstaller 打包形态
        candidates.insert(0, Path(sys.executable).resolve().parent / "policy.yml")
    for c in candidates:
        if c.is_file():
            return c
    return None


def _hotkey_loop(estop: EstopMonitor, audit: AuditLogger) -> None:
    """注册全局热键的消息循环线程（急停 Ctrl+Shift+F12 / 复位 Ctrl+Shift+F11）。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    ok1 = user32.RegisterHotKey(None, 1, _MOD_CONTROL | _MOD_SHIFT, _VK_F12)
    ok2 = user32.RegisterHotKey(None, 2, _MOD_CONTROL | _MOD_SHIFT, _VK_F11)
    if not (ok1 and ok2):
        audit.record_event("急停热键注册失败", "热键可能被占用；甩角触发仍可用")
        return
    audit.record_event("急停热键注册", "Ctrl+Shift+F12 触发 / Ctrl+Shift+F11 复位")
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == _WM_HOTKEY:
            if msg.wParam == 1:
                estop.on_trigger_hotkey()
            elif msg.wParam == 2:
                estop.on_reset_hotkey()


def _corner_loop(estop: EstopMonitor) -> None:
    """鼠标甩角轮询线程（50ms）。"""
    import pyautogui
    while True:
        pos = pyautogui.position()
        estop.check_corner(pos.x, pos.y)
        time.sleep(0.05)


def main() -> int:
    """进程入口。返回进程退出码（0 正常；非 0 启动失败）。"""
    policy_path = _find_policy_path()
    if policy_path is None:
        print("未找到 policy.yml", file=sys.stderr)
        return 2
    try:
        policy = load_policy(str(policy_path))
    except PolicyError as e:
        print(f"策略加载失败: {e}", file=sys.stderr)
        return 2

    audit = AuditLogger(policy.audit_dir)
    try:
        audit.record_event("策略加载", f"policy: {policy_path}")
    except AuditFailure as e:
        print(f"审计目录不可用: {e}", file=sys.stderr)
        return 3

    estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit)
    threading.Thread(target=_hotkey_loop, args=(estop, audit), daemon=True).start()
    threading.Thread(target=_corner_loop, args=(estop,), daemon=True).start()

    probe = DesktopProbe()
    bindings = BindingManager(probe, policy.binding_ttl, time.monotonic)
    approvals = ApprovalManager(DenyAllChannel(), policy.approval_ttl, time.monotonic)
    try:
        from .approval_ui import TkApprovalChannel
        approvals.set_channel(TkApprovalChannel(on_approved=approvals.issue_token))
    except Exception as e:
        print(f"审批弹窗通道不可用（L3 将恒拒绝）: {e}", file=sys.stderr)
    executor = Executor(estop, policy.audit_dir, policy.wait_poll_interval,
                        policy.wait_timeout_max)
    try:
        from rapidocr_onnxruntime import RapidOCR
        _rapid = RapidOCR()
        executor._ocr_engine = lambda img: [
            {"text": line[1], "position": [int(v) for v in line[0]]}
            for line in (_rapid(img)[0] or [])]
    except Exception as e:
        print(f"OCR 引擎不可用（ocr 工具将显式报错）: {e}", file=sys.stderr)
    enforcement = Enforcement(policy, bindings, approvals, estop, executor, audit)
    ctx = ToolContext(policy=policy, enforcement=enforcement, bindings=bindings,
                      executor=executor, audit=audit)

    audit.record_event("服务启动", "MCP stdio 就绪")
    if "--daemon" in sys.argv:
        # 常驻形态（ISS-0001）：内部 HTTP 服务，状态跨调用保持
        from .httpd import HttpDaemon
        daemon = HttpDaemon(ctx)
        daemon.start()
        audit.record_event("服务启动",
                           f"常驻 HTTP 服务 http://127.0.0.1:{daemon.port}")
        print(f"DeskPilot 常驻服务已启动: http://127.0.0.1:{daemon.port}",
              file=sys.stderr)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            daemon.stop()
            audit.record_event("服务停止", "常驻服务停止")
            return 0
    serve(ctx)                                   # 阻塞于 stdio
    audit.record_event("服务停止", "stdio 关闭")
    return 0
