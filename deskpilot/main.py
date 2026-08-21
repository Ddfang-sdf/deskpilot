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
from typing import Callable

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
from .freeze_notify import FreezeNotifier
from .httpd import DEFAULT_HOST, DEFAULT_PORT, probe_daemon
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


def _hotkey_loop(estop: EstopMonitor, audit: AuditLogger,
                 sleep: Callable[[float], None] = time.sleep) -> None:
    """注册全局热键的消息循环线程（急停 Ctrl+Shift+F12 / 复位 Ctrl+Shift+F11）。

    RegisterHotKey 全系统单持有者：注册失败按 1s 起步、倍增至 60s 上限的
    退避循环重试，逐次审计 + stderr 告警，禁止静默 return（ISS-0002）。
    sleep 可注入（测试接缝，详细设计 §11.6）。
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    delay = 1
    while True:
        ok1 = user32.RegisterHotKey(None, 1, _MOD_CONTROL | _MOD_SHIFT, _VK_F12)
        ok2 = user32.RegisterHotKey(None, 2, _MOD_CONTROL | _MOD_SHIFT, _VK_F11)
        if ok1 and ok2:
            break
        audit.record_event("急停热键注册失败",
                           f"热键可能被占用；{delay}s 后重试；甩角触发仍可用")
        print(f"急停热键注册失败（{delay}s 后重试）：热键可能被其他程序占用",
              file=sys.stderr)
        sleep(delay)
        delay = min(delay * 2, 60)
    audit.record_event("急停热键注册", "Ctrl+Shift+F12 触发 / Ctrl+Shift+F11 复位")
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == _WM_HOTKEY:
            if msg.wParam == 1:
                estop.on_trigger_hotkey()
            elif msg.wParam == 2:
                estop.on_reset_hotkey()


def _corner_loop(estop: EstopMonitor, notifier: FreezeNotifier) -> None:
    """鼠标甩角轮询线程（50ms）；兼任弹窗解冻请求消费（ISS-0004）。"""
    import pyautogui
    while True:
        pos = pyautogui.position()
        estop.check_corner(pos.x, pos.y)
        notifier.check_reset_request(estop)
        time.sleep(0.05)


def _start_estop_listeners(estop: EstopMonitor, audit: AuditLogger,
                           notifier: FreezeNotifier) -> None:
    """启动急停监听线程（热键 + 甩角）；先写 frozen:false 清状态文件残留。"""
    notifier.on_state_change(False, "服务启动")
    threading.Thread(target=_hotkey_loop, args=(estop, audit), daemon=True).start()
    threading.Thread(target=_corner_loop, args=(estop, notifier),
                     daemon=True).start()


def _cli_reset() -> int:
    """本地 CLI 复位命令入口（--reset，详细设计 §11.8，ISS-0002）。

    经本机 HTTP POST /estop/reset 触达常驻 daemon（冻结标志持有者）；
    daemon 离线时显式报错、非零退出（禁止静默）。"""
    import json
    import urllib.request

    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    if not probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
        print(f"无法连接常驻服务 {url}（daemon 未启动）", file=sys.stderr)
        return 4
    req = urllib.request.Request(f"{url}/estop/reset", data=b"",
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except OSError as e:
        print(f"无法连接常驻服务 {url}: {e}", file=sys.stderr)
        return 4
    print(body.get("message", ""))
    return 0 if body.get("ok") else 4


def _build_ocr_engine(rapid):
    """把 RapidOCR 实例适配为执行层 OCR 引擎（img → items）。

    RapidOCR 接受路径/ndarray(BGR)，不接受 PIL Image；返回四点框
    [[x,y]×4]，契约（tests/test_m3.py）为平铺包围盒 [x1,y1,x2,y2]。
    """
    import numpy as np

    def engine(img):
        out = []
        for line in (rapid(np.asarray(img)[:, :, ::-1])[0] or []):
            xs = [p[0] for p in line[0]]
            ys = [p[1] for p in line[0]]
            out.append({"text": line[1],
                        "position": [int(min(xs)), int(min(ys)),
                                     int(max(xs)), int(max(ys))]})
        return out

    return engine


def main() -> int:
    """进程入口。返回进程退出码（0 正常；非 0 启动失败）。"""
    if "--reset" in sys.argv:
        return _cli_reset()
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

    notifier = FreezeNotifier(policy.audit_dir,
                              remind_interval=policy.freeze_remind_interval)
    estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit,
                         on_state_change=notifier.on_state_change)
    if "--daemon" not in sys.argv and probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
        # stdio 瘦代理：冻结标志归 daemon 所有，本进程注册热键只会抢占
        # 复位通道（RegisterHotKey 全系统单持有者，ISS-0002 根因修复）
        audit.record_event("瘦代理跳过热键注册",
                           "daemon 在线；急停热键与甩角监听归 daemon 持有")
    else:
        _start_estop_listeners(estop, audit, notifier)

    probe = DesktopProbe()
    bindings = BindingManager(probe, policy.binding_ttl, time.monotonic)
    approvals = ApprovalManager(DenyAllChannel(), policy.approval_ttl, time.monotonic)
    try:
        from .approval_ui import TkApprovalChannel
        approvals.set_channel(TkApprovalChannel())
    except Exception as e:
        print(f"审批弹窗通道不可用（L3 将恒拒绝）: {e}", file=sys.stderr)
    executor = Executor(estop, policy.audit_dir, policy.wait_poll_interval,
                        policy.wait_timeout_max)
    try:
        from rapidocr_onnxruntime import RapidOCR
        executor._ocr_engine = _build_ocr_engine(RapidOCR())
    except Exception as e:
        print(f"OCR 引擎不可用（ocr 工具将显式报错）: {e}", file=sys.stderr)
    enforcement = Enforcement(policy, bindings, approvals, estop, executor, audit)
    ctx = ToolContext(policy=policy, enforcement=enforcement, bindings=bindings,
                      executor=executor, audit=audit)

    audit.record_event("服务启动", "MCP stdio 就绪")
    if "--daemon" in sys.argv:
        # 常驻形态（ISS-0001）：内部 HTTP 服务，状态跨调用保持
        from .httpd import HttpDaemon
        daemon = HttpDaemon(ctx, estop=estop)
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
