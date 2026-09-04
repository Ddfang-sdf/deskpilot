"""启动装配程序（详细设计 §3）。

启动顺序固定：策略 → 审计目录 → 急停监听 → 内存表 → 执行层/强制层装配 → MCP 服务；
任何一步失败即拒绝启动（fail-closed）。
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

def _set_dpi_awareness() -> str:
    """ISS-0007 D：DPI 感知——优先 Per-Monitor V2，失败回退 V1，再败不阻断。

    返回所用形态（"pmv2" / "v1" / "none"）。
    """
    import ctypes
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4).value):
            return "pmv2"
    except Exception:
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "v1"
    except Exception:
        pass
    return "none"


# DPI 感知必须在任何窗口/坐标 API 使用前声明（实盘教训：
# 150% 缩放主机上 UIA 物理像素与键鼠虚拟坐标错位，画笔落点全偏；
# ISS-0007：双屏混合 DPI 下 V1 会在副屏被位图拉伸，须 Per-Monitor V2）。
_DPI_MODE = _set_dpi_awareness()

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
    """鼠标甩角轮询线程（50ms）；兼任弹窗解冻请求消费（ISS-0004）与
    解冻全局同步（ISS-0006：共享 frozen=false → 本地立即复位）。"""
    import pyautogui
    while True:
        pos = pyautogui.position()
        estop.check_corner(pos.x, pos.y)
        notifier.check_reset_request(estop)
        notifier.sync_local_with_shared_state(estop)
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


def policy_sha256_audit(policy_path: str, audit) -> str:
    """ISS-0012 §6 C：启动指纹审计——计算 policy.yml SHA-256 并写审计。

    返回指纹（小写 hex）；审计事件"策略指纹"含路径与指纹。
    """
    from .whitelist_admin import file_sha256
    fp = file_sha256(policy_path)
    audit.record_event("策略指纹", f"{policy_path} sha256={fp}")
    return fp


def local_policy_sha256_audit(local_path: str, audit) -> str:
    """ISS-0030 E：用户策略数据(policy.local.yml)指纹审计——双轨第二轨。

    审计事件「用户策略数据指纹」;出厂文件与用户数据分别留痕。
    """
    from .whitelist_admin import file_sha256
    fp = file_sha256(local_path)
    audit.record_event("用户策略数据指纹", f"{local_path} sha256={fp}")
    return fp


class _PolicyWatchThread(threading.Thread):
    """ISS-0012 §6 C：策略文件指纹周期比对线程（stop() 可停）。"""

    def __init__(self, policy_path: str, audit, interval: float,
                 fingerprint: str):
        super().__init__(daemon=True, name="deskpilot-policy-watch")
        self._path = policy_path
        self._audit = audit
        self._interval = interval
        self._fp = fingerprint
        self._stopped = threading.Event()

    def run(self) -> None:
        from .whitelist_admin import file_sha256
        while not self._stopped.wait(self._interval):
            try:
                cur = file_sha256(self._path)
            except OSError:
                continue
            if cur != self._fp:
                try:
                    self._audit.record_event(
                        "策略文件被外部修改",
                        f"{self._path} sha256 {self._fp} -> {cur}")
                except Exception:
                    pass
                self._fp = cur

    def stop(self) -> None:
        self._stopped.set()


def _start_policy_watch(policy_path: str, audit, interval: float = 60.0,
                        fingerprint: str = "") -> _PolicyWatchThread:
    """ISS-0012 §6 C：启动策略守望线程（不重载不冻结，仅留痕告警）。"""
    t = _PolicyWatchThread(policy_path, audit, interval, fingerprint)
    t.start()
    return t


def _start_janitor(policy, audit: AuditLogger) -> None:
    """ISS-0010 C：清理者装配——启动时跑一遍；interval>0 时按周期定时跑。"""
    from .janitor import run_janitor

    def once():
        try:
            run_janitor(policy.audit_dir, time.time(),
                        policy.logs_max_age_days * 86400,
                        policy.shots_max_age_days * 86400,
                        policy.shots_max_bytes,
                        policy.cleanup_grace_seconds, audit_log=audit)
        except Exception as e:
            try:
                audit.record_event("截图清理异常", str(e))
            except Exception:
                pass

    once()
    if policy.cleanup_interval_seconds > 0:
        def loop():
            while True:
                time.sleep(policy.cleanup_interval_seconds)
                once()

        threading.Thread(target=loop, daemon=True).start()


def _run_migrate_policy(args: list[str]) -> int:
    """ISS-0030 F：--migrate-policy <old> <new> <local> 升级迁移子命令。

    把旧策略中不属于新出厂的白名单差额迁入用户数据文件(审计「入白迁移」)。
    """
    if len(args) != 3:
        print("用法: deskpilot.exe --migrate-policy <旧policy.yml> "
              "<新出厂policy.yml> <policy.local.yml>", file=sys.stderr)
        return 2
    old, new, local = args
    from .policy import migrate_whitelist
    audit = None
    try:
        from .audit import AuditLogger
        audit = AuditLogger(load_policy(new).audit_dir)
    except Exception:
        pass                    # 审计不可用时迁移照常(尽力留痕)
    try:
        migrated = migrate_whitelist(old, new, local, audit=audit)
    except PolicyError as e:
        print(f"入白迁移失败: {e}", file=sys.stderr)
        return 2
    print(f"入白迁移: {', '.join(migrated) if migrated else '无差异'}")
    return 0


def main() -> int:
    """进程入口。返回进程退出码（0 正常；非 0 启动失败）。"""
    if "--reset" in sys.argv:
        return _cli_reset()
    if "--migrate-policy" in sys.argv:
        i = sys.argv.index("--migrate-policy")
        return _run_migrate_policy(sys.argv[i + 1:i + 4])
    policy_path = _find_policy_path()
    if policy_path is None:
        print("未找到 policy.yml", file=sys.stderr)
        return 2
    # ISS-0030 A：双文件——出厂只读 + 用户数据(policy.local.yml)
    local_path = policy_path.with_name("policy.local.yml")
    try:
        base_policy = load_policy(str(policy_path))
        policy = load_policy(str(policy_path), local_path=str(local_path))
    except PolicyError as e:
        print(f"策略加载失败: {e}", file=sys.stderr)
        return 2
    # 惰性创建(ISS-0031 修正):local 文件在首次永久入白时才落盘,
    # 纯加载不产生空文件(避免仓库/目录被空数据文件污染)

    audit = AuditLogger(policy.audit_dir)
    try:
        audit.record_event("策略加载", f"policy: {policy_path}")
    except AuditFailure as e:
        print(f"审计目录不可用: {e}", file=sys.stderr)
        return 3

    # ISS-0012 C：策略指纹入审计 + 运行期外部修改留痕
    fp = policy_sha256_audit(str(policy_path), audit)
    _start_policy_watch(str(policy_path), audit, fingerprint=fp)
    # ISS-0030 E：用户数据第二轨指纹+守望(文件未创建则跳过,
    # 首笔永久入白落盘后由下次启动纳入)
    if local_path.is_file():
        local_fp = local_policy_sha256_audit(str(local_path), audit)
        _start_policy_watch(str(local_path), audit, fingerprint=local_fp)
    # ISS-0012 A/D：运行期白名单管理（静态∪会话；落盘由 daemon 原子完成）
    from .whitelist_admin import WhitelistAdmin
    whitelist_admin = WhitelistAdmin(str(policy_path), policy.whitelist,
                                     audit=audit,
                                     local_path=str(local_path),
                                     base_whitelist=base_policy.whitelist)
    # ISS-0012 TC-FAST-04：并行暖名称/描述解析缓存（管理窗口/审批弹窗提速）
    from .appnames import warm_caches
    threading.Thread(target=warm_caches, kwargs={"parallel": True},
                     daemon=True, name="deskpilot-warm-caches").start()

    from .dialog_service import get_dialog_service
    dialog_service = get_dialog_service()         # ISS-0008 P6：弹窗线程常驻
    from .audit_paths import AuditPaths
    audit_paths = AuditPaths(policy.audit_dir)    # ISS-0010 B：受管目录归队
    notifier = FreezeNotifier(policy.audit_dir,
                              remind_interval=policy.freeze_remind_interval,
                              dialog_service=dialog_service)
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
        # 弹窗倒计时须由 policy.approval_ttl 驱动（此前硬编码默认 60s，
        # policy 调大不生效——"5 分钟承诺实际 60 秒"事故）
        approvals.set_channel(TkApprovalChannel(
            timeout=policy.approval_ttl,
            dialog_service=dialog_service, audit_paths=audit_paths))
    except Exception as e:
        print(f"审批弹窗通道不可用（L3 将恒拒绝）: {e}", file=sys.stderr)
    executor = Executor(estop, policy.audit_dir, policy.wait_poll_interval,
                        policy.wait_timeout_max)

    def _ocr_factory():
        """ISS-0008 P2：OCR 懒加载工厂——首次 ocr 调用才加载模型。"""
        from rapidocr_onnxruntime import RapidOCR
        return _build_ocr_engine(RapidOCR())

    executor.ocr_factory = _ocr_factory
    enforcement = Enforcement(policy, bindings, approvals, estop, executor,
                              audit, whitelist_admin=whitelist_admin)
    # ISS-0012 E3/E4：撤回确认通道与入白撤销 toast 接线
    from .whitelist_window import DialogRevokeChannel
    revoke_channel = DialogRevokeChannel(dialog_service,
                                         audit_paths=audit_paths)
    whitelist_admin.notify_permanent = lambda proc: dialog_service.show(
        "enroll_notice",
        {"process": proc,
         "on_undo": lambda p=proc: whitelist_admin.remove(p)})
    ctx = ToolContext(policy=policy, enforcement=enforcement, bindings=bindings,
                      executor=executor, audit=audit,
                      whitelist_admin=whitelist_admin,
                      revoke_channel=revoke_channel)

    audit.record_event("服务启动", "MCP stdio 就绪")
    _start_janitor(policy, audit)                 # ISS-0010 C：清理者装配
    if "--daemon" in sys.argv:
        # 常驻形态（ISS-0001）：内部 HTTP 服务，状态跨调用保持
        from .httpd import HttpDaemon
        daemon = HttpDaemon(ctx, estop=estop,
                            idle_timeout_s=policy.idle_timeout_minutes * 60,
                            whitelist_admin=whitelist_admin)
        daemon.start()
        audit.record_event("服务启动",
                           f"常驻 HTTP 服务 http://127.0.0.1:{daemon.port}")
        print(f"DeskPilot 常驻服务已启动: http://127.0.0.1:{daemon.port}",
              file=sys.stderr)
        # ISS-0012 E1：系统托盘图标（白名单管理可视化入口；托盘即在跑）
        from .tray import TrayIcon
        base_url = f"http://127.0.0.1:{daemon.port}"

        def _open_manager() -> None:
            import subprocess
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--whitelist-manager", base_url]
                env = {k: v for k, v in os.environ.items()
                       if k != "_MEIPASS2"}
            else:
                cmd = [sys.executable, "-m", "deskpilot.whitelist_window",
                       base_url]
                env = None
            try:
                subprocess.Popen(cmd, env=env)
            except OSError:
                pass

        tray = TrayIcon(on_manage=_open_manager)
        tray.start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            tray.stop()
            daemon.stop()
            audit.record_event("服务停止", "常驻服务停止")
            return 0
    serve(ctx)                                   # 阻塞于 stdio
    audit.record_event("服务停止", "stdio 关闭")
    return 0
