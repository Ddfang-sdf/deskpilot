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
    """DPI 感知声明 + 查询制如实回报(ISS-0007 D / ISS-0051)。

    声明:优先 Per-Monitor V2,失败回退系统级——ISS-0051:必须传
    c_void_p 对象;.value 拆包成 64 位巨无符号整数,无 argtypes 时
    ctypes 按 c_int 封送溢出抛 ArgumentError,被回退静默吞掉
    (PMV2 自 ISS-0007 起从未真正生效的实证根因)。

    回报:不按调用成败记账(清单预设/调用被拒/封送异常都可能说谎),
    一律查询真实上下文——pmv2/pmv1/v1/unaware/unknown。
    """
    import ctypes
    u32 = ctypes.windll.user32
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
        u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            u32.SetProcessDPIAware()
        except Exception:
            pass
    return _query_dpi_mode()


def _query_dpi_mode() -> str:
    """查询进程真实 DPI 感知形态(ISS-0051:回报必须如实)。

    原始句柄含标志位(实证:PMV2 上下文原值可为 34),必须经
    AreDpiAwarenessContextsEqual 归一比较,禁止直比句柄数值;
    句柄同样传 c_void_p 对象(同 ISS-0051 封送教训)。
    """
    import ctypes
    try:
        u32 = ctypes.windll.user32
        ctx = u32.GetThreadDpiAwarenessContext()
        eq = u32.AreDpiAwarenessContextsEqual
        for value, name in ((-4, "pmv2"), (-3, "pmv1"),
                            (-2, "v1"), (-1, "unaware")):
            if eq(ctx, ctypes.c_void_p(value)):
                return name
        return "unknown"
    except Exception:
        return "unknown"


# DPI 感知必须在任何窗口/坐标 API 使用前声明（实盘教训：
# 150% 缩放主机上 UIA 物理像素与键鼠虚拟坐标错位，画笔落点全偏；
# ISS-0007：双屏混合 DPI 下 V1 会在副屏被位图拉伸，须 Per-Monitor V2）。
_DPI_MODE = _set_dpi_awareness()


def _startup_detail(form: str) -> str:
    """启动审计明细：形态 + DPI 感知形态(ISS-0050:DPI 形态必须可诊断,
    否则混合缩放主机上 V2 静默回退后"AI 点不准"无从定位)。"""
    return f"{form}; DPI={_DPI_MODE}"

from .approval import ApprovalManager, DenyAllChannel
from .audit_events import (
    EV_AUTOSTART_REGISTERED, EV_CORNER_LOOP_ERROR,
    EV_DAEMON_SINGLETON_EXIT, EV_HOTKEY_REGISTER_FAILED,
    EV_HOTKEY_REGISTERED, EV_OWNER_BIND_9420_FAILED,
    EV_POLICY_EXTERNALLY_MODIFIED, EV_POLICY_FINGERPRINT,
    EV_POLICY_LOADED, EV_POLICY_LOCAL_EXTERNALLY_MODIFIED,
    EV_POLICY_LOCAL_FINGERPRINT, EV_PROXY_SKIPS_HOTKEY,
    EV_MANAGER_WINDOW_LAUNCH, EV_NAME_CACHE_WARMED,
    EV_SCREENSHOT_CLEANUP_ERROR, EV_SERVICE_START,
    EV_SERVICE_STOP, EV_STDIO_BECOME_OWNER)
from .audit import AuditLogger
from .binding import BindingManager
from .enforcement import Enforcement
from .errors import AuditFailure, PolicyError
from .estop import EstopMonitor
from .executor import DesktopProbe, Executor
from .freeze_notify import FreezeNotifier
from .httpd import DEFAULT_HOST, DEFAULT_PORT, probe_daemon
from .i18n import tr
from .mcp_server import serve
from .policy import load_policy
from .secure_desktop import SecureDesktopGuard
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
    failed_rounds = 0
    while True:
        ok1 = user32.RegisterHotKey(None, 1, _MOD_CONTROL | _MOD_SHIFT, _VK_F12)
        ok2 = user32.RegisterHotKey(None, 2, _MOD_CONTROL | _MOD_SHIFT, _VK_F11)
        if ok1 and ok2:
            break
        failed_rounds += 1
        # ISS-0084 ②节流:失败审计只记首次——逐次审计曾是实机每分钟刷屏之源;
        # stderr 每次照打(控制台即时可见),审计面只留首败与恢复两条
        if failed_rounds == 1:
            audit.record_event(EV_HOTKEY_REGISTER_FAILED,
                               f"热键可能被占用;退避重试中(节流:仅记首败);"
                               f"甩角触发仍可用")
        print(f"急停热键注册失败（{delay}s 后重试）：热键可能被其他程序占用",
              file=sys.stderr)
        sleep(delay)
        delay = min(delay * 2, 60)
    if failed_rounds:
        audit.record_event(EV_HOTKEY_REGISTERED,
                           f"Ctrl+Shift+F12 触发 / Ctrl+Shift+F11 复位"
                           f"(恢复:重试 {failed_rounds} 轮后成功)")
    else:
        audit.record_event(EV_HOTKEY_REGISTERED,
                           "Ctrl+Shift+F12 触发 / Ctrl+Shift+F11 复位")
    msg = wintypes.MSG()
    msg_failed_rounds = 0
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == _WM_HOTKEY:
            # ISS-0092 ①:热键处理异常不杀消息循环(同甩角守卫,
            # 审计归同一「甩角轮询异常」类型=单据 §5 四类审计之一,
            # detail 前缀区分来源循环;节流:仅记首败+恢复一条)
            try:
                if msg.wParam == 1:
                    estop.on_trigger_hotkey()
                elif msg.wParam == 2:
                    estop.on_reset_hotkey()
            except Exception as e:                          # noqa: BLE001
                msg_failed_rounds += 1
                if msg_failed_rounds == 1:
                    audit.record_event(
                        EV_CORNER_LOOP_ERROR,
                        f"热键消息循环: {e!r}(节流:仅记首败,恢复时另记一条)")
                print(f"热键处理异常（消息循环继续）: {e!r}", file=sys.stderr)
            else:
                if msg_failed_rounds:
                    audit.record_event(
                        EV_CORNER_LOOP_ERROR,
                        f"热键消息循环恢复:连续异常 {msg_failed_rounds} 轮后"
                        f"恢复正常")
                    msg_failed_rounds = 0


def _corner_loop(estop: EstopMonitor, notifier: FreezeNotifier,
                 audit: AuditLogger | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 stop: Callable[[], bool] | None = None) -> None:
    """鼠标甩角轮询线程（50ms）；兼任弹窗子进程退出码消费（ISS-0093 §9.2）
    与共享状态单向对账（ISS-0093 §9.4 v0.5：本地权威,只修共享不改本地）。

    ISS-0092 ①线程异常守卫：循环体 try/except，单轮异常不杀线程
    （写回失败异常曾沿此链打死甩角线程→冻结卡死+解冻消费死）；
    节流审计「甩角轮询异常」（仅记首败，恢复时记一条含失败轮数，
    镜像 _hotkey_loop ISS-0084 ②模式），stderr 每轮照打。
    sleep/stop 为测试接缝（详设 §11.6 sleep 注入先例）；stop 置位
    即收口退出，供测试与未来的优雅停机用。
    """
    import pyautogui
    failed_rounds = 0
    while True:
        if stop is not None and stop():
            return
        try:
            pos = pyautogui.position()
            estop.check_corner(pos.x, pos.y)
            notifier.check_dialog_exit(estop)    # ISS-0093 §9.2:退出码消费
            notifier.sync_local_with_shared_state(estop)
        except Exception as e:                              # noqa: BLE001
            failed_rounds += 1
            if failed_rounds == 1 and audit is not None:
                audit.record_event(
                    EV_CORNER_LOOP_ERROR, f"{e!r}（节流:仅记首败,恢复时另记一条）")
            print(f"甩角轮询异常（已容错,继续轮询）: {e!r}", file=sys.stderr)
        else:
            if failed_rounds:
                if audit is not None:
                    audit.record_event(
                        EV_CORNER_LOOP_ERROR,
                        f"恢复:连续异常 {failed_rounds} 轮后恢复正常")
                failed_rounds = 0
        finally:
            sleep(0.05)


def _open_manager_for(port: int, audit=None, stderr_log=None):
    """白名单管理窗口的拉起命令(托盘 on_manage 回调;daemon/stdio 属主共用)。

    ISS-0095:O1=Popen 前记「管理窗拉起」(base_url);O2=子进程 stderr
    重定向到受管目录滚动日志(单文件追加;打开失败静默降级)——
    全部埋点 fail-closed,异常不阻断开窗。
    """
    def _open() -> None:
        import subprocess
        base_url = f"http://127.0.0.1:{port}"
        if audit is not None:                    # O1:拉起打点(不阻断)
            try:
                audit.record_event(EV_MANAGER_WINDOW_LAUNCH, base_url)
            except Exception:                    # noqa: BLE001
                pass
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--whitelist-manager", base_url]
            env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2"}
        else:
            cmd = [sys.executable, "-m", "deskpilot.whitelist_window",
                   base_url]
            env = None
        err = None
        if stderr_log is not None:               # O2:stderr→受管滚动日志
            try:
                Path(stderr_log).parent.mkdir(parents=True, exist_ok=True)
                err = open(stderr_log, "a", encoding="utf-8")
            except OSError:
                err = None                       # 打开失败静默降级
        try:
            subprocess.Popen(cmd, env=env,
                             **({"stderr": err} if err is not None else {}))
        except OSError:
            pass
        finally:
            if err is not None:                  # Popen 已复制句柄,父侧即关
                try:
                    err.close()
                except OSError:
                    pass
    return _open


def _warm_caches_with_audit(audit=None) -> None:
    """名称缓存暖机计时埋点(ISS-0095 O4):dur_ms+ok 留痕;
    暖机失败记 ok=False 且不上抛(fail-closed,不阻断启动)。"""
    from .appnames import warm_caches
    t0 = time.monotonic()
    ok, err = True, ""
    try:
        warm_caches(parallel=True)
    except Exception as e:                       # noqa: BLE001
        ok, err = False, f": {e!r}"
    dur_ms = (time.monotonic() - t0) * 1000
    if audit is not None:
        try:
            audit.record_event(EV_NAME_CACHE_WARMED,
                               f"dur_ms={dur_ms:.0f} ok={ok}{err}")
        except Exception:                        # noqa: BLE001
            pass


def _start_estop_listeners(estop: EstopMonitor, audit: AuditLogger,
                           notifier: FreezeNotifier) -> None:
    """启动急停监听线程（热键 + 甩角）；先写 frozen:false 清状态文件残留。"""
    notifier.on_state_change(False, "服务启动")
    threading.Thread(target=_hotkey_loop, args=(estop, audit), daemon=True).start()
    threading.Thread(target=_corner_loop, args=(estop, notifier),
                     kwargs={"audit": audit}, daemon=True).start()


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
    audit.record_event(EV_POLICY_FINGERPRINT, f"{policy_path} sha256={fp}")
    return fp


def local_policy_sha256_audit(local_path: str, audit) -> str:
    """ISS-0030 E：用户策略数据(policy.local.yml)指纹审计——双轨第二轨。

    审计事件「用户策略数据指纹」;出厂文件与用户数据分别留痕。
    """
    from .whitelist_admin import file_sha256
    fp = file_sha256(local_path)
    audit.record_event(EV_POLICY_LOCAL_FINGERPRINT, f"{local_path} sha256={fp}")
    return fp


class _PolicyWatchThread(threading.Thread):
    """ISS-0012 §6 C：策略文件指纹周期比对线程（stop() 可停）。

    ISS-0034 B1：check_once 提取为单测接缝;refresh 供服务内部写入方
    （WhitelistAdmin on_written 回调）同步基线——内部写入零假警,
    真外部改动仍即时留痕。event_name 区分出厂/用户数据两轨。
    """

    def __init__(self, policy_path: str, audit, interval: float,
                 fingerprint: str, event_name: str = EV_POLICY_EXTERNALLY_MODIFIED):
        super().__init__(daemon=True, name="deskpilot-policy-watch")
        self._path = policy_path
        self._audit = audit
        self._interval = interval
        self._fp = fingerprint
        self._event_name = event_name
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def check_once(self) -> None:
        """单轮比对(提取接缝,run 与测试共用)。"""
        from .whitelist_admin import file_sha256
        try:
            cur = file_sha256(self._path)
        except OSError:
            return
        with self._lock:
            if cur != self._fp:
                try:
                    self._audit.record_event(
                        self._event_name,
                        f"{self._path} sha256 {self._fp} -> {cur}")
                except Exception:
                    pass
                self._fp = cur

    def refresh(self, fingerprint: str) -> None:
        """服务内部写入后的基线刷新(ISS-0034 B1)。"""
        with self._lock:
            self._fp = fingerprint

    def run(self) -> None:
        while not self._stopped.wait(self._interval):
            self.check_once()

    def stop(self) -> None:
        self._stopped.set()


def _start_policy_watch(policy_path: str, audit, interval: float = 60.0,
                        fingerprint: str = "",
                        event_name: str = EV_POLICY_EXTERNALLY_MODIFIED
                        ) -> _PolicyWatchThread:
    """ISS-0012 §6 C：启动策略守望线程（不重载不冻结，仅留痕告警）。"""
    t = _PolicyWatchThread(policy_path, audit, interval, fingerprint,
                           event_name=event_name)
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
                audit.record_event(EV_SCREENSHOT_CLEANUP_ERROR, str(e))
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
        from .audit_paths import resolve_audit_dir
        new_policy = load_policy(new)
        # ISS-0032 B4:相对 audit_dir 锚定到新策略所在目录,
        # 不随安装器 CWD 流浪
        anchored = resolve_audit_dir(new_policy.audit_dir,
                                     policy_path=os.path.abspath(new))
        audit = AuditLogger(str(anchored))
    except Exception:
        pass                    # 审计不可用时迁移照常(尽力留痕)
    try:
        migrated = migrate_whitelist(old, new, local, audit=audit)
    except PolicyError as e:
        print(f"入白迁移失败: {e}", file=sys.stderr)
        return 2
    print(f"入白迁移: {', '.join(migrated) if migrated else '无差异'}")
    return 0


def _stage_load_policy() -> tuple[int | None, dict | None]:
    """策略段(ISS-0064 S1,纯重构):--migrate-policy 子命令分发+
    策略定位+双文件(出厂/用户数据)加载。

    返回 (rc, bundle):rc 非 None = 早退码(子命令结果或 2);
    bundle = {policy_path, local_path, base_policy, policy}。
    """
    if "--migrate-policy" in sys.argv:
        i = sys.argv.index("--migrate-policy")
        return _run_migrate_policy(sys.argv[i + 1:i + 4]), None
    policy_path = _find_policy_path()
    if policy_path is None:
        print("未找到 policy.yml", file=sys.stderr)
        return 2, None
    # ISS-0030 A：双文件——出厂只读 + 用户数据(policy.local.yml)
    local_path = policy_path.with_name("policy.local.yml")
    try:
        base_policy = load_policy(str(policy_path))
        policy = load_policy(str(policy_path), local_path=str(local_path))
    except PolicyError as e:
        print(f"策略加载失败: {e}", file=sys.stderr)
        return 2, None
    # 惰性创建(ISS-0031 修正):local 文件在首次永久入白时才落盘,
    # 纯加载不产生空文件(避免仓库/目录被空数据文件污染)
    return None, {"policy_path": policy_path, "local_path": local_path,
                  "base_policy": base_policy, "policy": policy}


def _stage_audit(policy, policy_path) -> tuple[int | None, AuditLogger | None]:
    """审计段(ISS-0064 S2,纯重构):审计装配 fail-closed(rc 3)。

    返回 (rc, audit):rc 非 None = 早退码(3,审计目录不可用);
    stderr 文案与审计事件逐字节不变。
    """
    audit = AuditLogger(policy.audit_dir)
    try:
        audit.record_event(EV_POLICY_LOADED, f"policy: {policy_path}")
    except AuditFailure as e:
        print(f"审计目录不可用: {e}", file=sys.stderr)
        return 3, None
    return None, audit


def _stage_daemon_precheck(audit: AuditLogger) -> int | None:
    """daemon 单例预检守门(ISS-0064 S2,纯重构,ISS-0046 A):已有属主
    在线时本实例显式退出(rc 4)——必须在甩角/热键监听与弹窗装配之前:
    非属主进程不监听、不弹窗、不绑端口。rc 4=早退;None=通过。"""
    if "--daemon" in sys.argv and probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
        audit.record_event(EV_DAEMON_SINGLETON_EXIT,
                           "9420 已有属主在线,拒绝双起(甩角监听/弹窗归属主)")
        print("已有 DeskPilot daemon 在线(127.0.0.1:9420),本实例退出",
              file=sys.stderr)
        return 4
    return None


def _stage_whitelist(policy, base_policy, policy_path, local_path,
                     audit: AuditLogger):
    """白名单段(ISS-0064 S3,纯重构):双轨指纹审计+守望线程+
    WhitelistAdmin 装配+暖名称/描述缓存线程。返回 WhitelistAdmin。"""
    # ISS-0012 C：策略指纹入审计 + 运行期外部修改留痕
    fp = policy_sha256_audit(str(policy_path), audit)
    _start_policy_watch(str(policy_path), audit, fingerprint=fp)
    # ISS-0030 E：用户数据第二轨指纹+守望(文件未创建则跳过,
    # 首笔永久入白落盘后由下次启动纳入)
    local_watch = None
    if local_path.is_file():
        local_fp = local_policy_sha256_audit(str(local_path), audit)
        local_watch = _start_policy_watch(
            str(local_path), audit, fingerprint=local_fp,
            event_name=EV_POLICY_LOCAL_EXTERNALLY_MODIFIED)
    # ISS-0012 A/D：运行期白名单管理（静态∪会话；落盘由 daemon 原子完成）
    from .whitelist_admin import WhitelistAdmin
    whitelist_admin = WhitelistAdmin(str(policy_path), policy.whitelist,
                                     audit=audit,
                                     local_path=str(local_path),
                                     base_whitelist=base_policy.whitelist,
                                     revoked=policy.revoked,
                                     on_written=(local_watch.refresh
                                                 if local_watch else None))
    # ISS-0012 TC-FAST-04：并行暖名称/描述解析缓存（管理窗口/审批弹窗提速）
    # ISS-0095 O4:暖机计时埋点包层(失败记 ok=False 不阻断启动)
    threading.Thread(target=_warm_caches_with_audit, kwargs={"audit": audit},
                     daemon=True, name="deskpilot-warm-caches").start()
    return whitelist_admin


def _stage_dialogs(policy, audit: AuditLogger) -> dict:
    """急停弹窗子段(ISS-0064 S4a,纯重构):弹窗服务/审计路径/共享目录/
    冻结通知/急停装配/遗嘱挂钩。返回运行时束 dict。"""
    from .dialog_service import get_dialog_service
    dialog_service = get_dialog_service()         # ISS-0008 P6：弹窗线程常驻
    from .audit_paths import AuditPaths
    audit_paths = AuditPaths(policy.audit_dir)    # ISS-0010 B：受管目录归队
    # ISS-0084:属主面文件与急停邮箱锚定 LOCALAPPDATA\DeskPilot(跨形态共享
    # ——daemon(dist)与 stdio(repo)的审计目录分离,属主面/邮箱若跟随审计
    # 目录则双世界分裂,v0.2 实证),与各形态自己的审计**日志**目录分离
    from .ownership import install_last_will
    _shared_dir = str(Path(os.environ.get("LOCALAPPDATA")
                           or str(Path.home())) / "DeskPilot")
    notifier = FreezeNotifier(_shared_dir,
                              remind_interval=policy.freeze_remind_interval,
                              dialog_service=dialog_service, audit=audit)
    estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit,
                         on_state_change=notifier.on_state_change)
    # ISS-0093 §9.1:freeze payload 注入进程内直调回调(模式同构
    # enroll_notice 的 payload["on_undo"] 先例)
    notifier.on_reset = estop.dialog_reset
    install_last_will(audit, "daemon" if "--daemon" in sys.argv else "stdio")
    return {"dialog_service": dialog_service, "audit_paths": audit_paths,
            "shared_dir": _shared_dir, "notifier": notifier, "estop": estop}


def _stage_runtime(policy, policy_path, estop, audit: AuditLogger,
                   dialog_service, audit_paths, whitelist_admin) -> dict:
    """执行器强制层子段(ISS-0064 S4b,纯重构):探针/绑定/审批通道/
    权重目录/允许根/执行器/检测器与 OCR 懒工厂/强制层/撤回通道/ToolContext。"""
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
    # REQ-003 §3.3：检测权重目录(可选顶层键)——锚定规矩与 audit_dir 同
    # (ISS-0010):绝对路径原样;冻结形态锚 exe 目录;源码形态锚策略文件目录。
    # 装配期预解析为绝对路径传入 Executor(resolve 对绝对路径幂等)
    from .executor.detector import resolve as _resolve_weight_dir
    _weights_dir = policy.detector_weights_dir
    if _weights_dir:
        _weights_dir = str(_resolve_weight_dir(
            _weights_dir, policy_path=os.path.abspath(str(policy_path))))
    # ISS-0102 §3.2:screenshot path 落盘允许根=仓库根(policy.yml 所在目录,
    # 装配约定置首=相对路径锚)∪审计根(resolve_audit_dir 绝对值)
    from .audit_paths import resolve_audit_dir
    _allowed_roots = (str(Path(policy_path).resolve().parent),
                      str(resolve_audit_dir(policy.audit_dir,
                                            str(policy_path)).resolve()))
    executor = Executor(estop, policy.audit_dir, policy.wait_poll_interval,
                        policy.wait_timeout_max, audit=audit,
                        detector_weights_dir=_weights_dir,
                        allowed_roots=_allowed_roots)
    executor._mouse_watchdog.start()        # REQ-001 看门狗线程(生产装配启动)

    def _detector_factory():
        """REQ-003 D-12 终裁:CV 管线检测器(注册表出厂标识 cv-contour,
        零权重零装填开销;与 _ocr_factory 同处的懒装填装配位)。"""
        from .executor.detector import DetectorRegistry
        return DetectorRegistry().build("cv-contour")

    executor.detector_factory = _detector_factory
    # weight_manifest **不赋值**:CV 线零权重,出厂空清单即真实形态(D-12/D-18),
    # 空清单下 _ensure_detector 跳过校验直接装填,生产 detect=true 即刻可用

    def _ocr_factory():
        """ISS-0008 P2：OCR 懒加载工厂——首次 ocr 调用才加载模型。"""
        from rapidocr_onnxruntime import RapidOCR
        return _build_ocr_engine(RapidOCR())

    executor.ocr_factory = _ocr_factory
    enforcement = Enforcement(policy, bindings, approvals, estop, executor,
                              audit, whitelist_admin=whitelist_admin)
    # ISS-0012 E3/E4：撤回确认通道与入白撤销 toast 接线
    # ISS-0097:落位一律主屏右下角(不额外判断)——ISS-0071 的
    # resolve_screen/_screen_of_process 跟随机制整体撤除
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
                      revoke_channel=revoke_channel,
                      secure_guard=SecureDesktopGuard(audit=audit))
    return {"executor": executor, "ctx": ctx}


def main() -> int:
    """进程入口。返回进程退出码（0 正常；非 0 启动失败）。"""
    # ISS-0093 §9.3:--reset CLI 复位通道已收口删除(AI 可 curl/调用自行
    # 解冻);解冻入口收敛为「弹窗点击+复位热键」两个人类独占通道。
    rc, bundle = _stage_load_policy()
    if rc is not None:
        return rc
    policy_path, local_path = bundle["policy_path"], bundle["local_path"]
    base_policy, policy = bundle["base_policy"], bundle["policy"]

    rc, audit = _stage_audit(policy, policy_path)
    if rc is not None:
        return rc

    rc = _stage_daemon_precheck(audit)
    if rc is not None:
        return rc

    whitelist_admin = _stage_whitelist(policy, base_policy, policy_path,
                                       local_path, audit)

    dialogs = _stage_dialogs(policy, audit)
    dialog_service = dialogs["dialog_service"]
    audit_paths = dialogs["audit_paths"]
    _shared_dir = dialogs["shared_dir"]
    notifier = dialogs["notifier"]
    estop = dialogs["estop"]

    runtime = _stage_runtime(policy, policy_path, estop, audit,
                             dialog_service, audit_paths, whitelist_admin)
    executor = runtime["executor"]
    ctx = runtime["ctx"]

    # ---------- ISS-0084 属主权装配(①②③⑤⑥) ----------
    from .ownership import (RoleSupervisor, ensure_autostart,  # noqa: F401
                            is_daemon_alive)
    supervisor: "RoleSupervisor | None" = None
    owner_httpd: dict = {"d": None}
    owner_tray: dict = {"t": None}

    def _become_owner() -> None:
        """属主升起(②⑥):9420 HTTP + 托盘 + 热键/甩角监听。"""
        from .httpd import HttpDaemon
        from .tray import TrayIcon
        d = HttpDaemon(ctx, estop=estop,
                       idle_timeout_s=policy.idle_timeout_minutes * 60,
                       whitelist_admin=whitelist_admin)
        try:
            d.start()
        except RuntimeError as e:
            # 锁与端口不一致的异常面:记审计,属主回调内不持 HTTP,
            # 调用方据此放锁退瘦代理
            audit.record_event(EV_OWNER_BIND_9420_FAILED, f"{e}")
            return
        owner_httpd["d"] = d
        t = TrayIcon(on_manage=_open_manager_for(
            d.port, audit=audit,
            stderr_log=audit_paths.logs / "manager-window.log"))
        t.start()
        owner_tray["t"] = t
        _start_estop_listeners(estop, audit, notifier)

    def _cede_owner() -> None:
        """daemon 复出回迁(②):停 HTTP/托盘,注销热键——属主语义回 daemon。"""
        if owner_httpd["d"] is not None:
            owner_httpd["d"].stop()
            owner_httpd["d"] = None
        if owner_tray["t"] is not None:
            owner_tray["t"].stop()
            owner_tray["t"] = None
        import ctypes as _ct
        _ct.windll.user32.UnregisterHotKey(None, 1)   # 热键(急停/复位)注销,
        _ct.windll.user32.UnregisterHotKey(None, 2)   # 消息循环随进程退运清理

    def _alarm_fn(msg: str) -> None:
        """③死亡告警:托盘气泡(属主形态)+ stderr 双通道。"""
        if owner_tray["t"] is not None:
            owner_tray["t"].notify(tr("tray.alarm.title"),
                                   tr("tray.alarm.text"))
        print(msg + "(白名单管理/热键复位不可用)", file=sys.stderr)

    def _ownership_watch() -> None:
        """属主周期:daemon 复出让位 / daemon 死亡自愈接管 / 死亡告警(③)。"""
        while supervisor is not None:
            time.sleep(10.0)
            supervisor.tick()

    if "--daemon" in sys.argv:
        # daemon:持锁重试(心跳在 supervisor.start 内先行——stdio 属主见之
        # 让位,§7.2);锁不得 → 干净退出(单例语义升级:锁先于端口)
        supervisor = RoleSupervisor(_shared_dir, "daemon", audit=audit)
        _acquired = False
        for _att in range(12):
            if supervisor.start():
                _acquired = True
                break
            time.sleep(min(1.0 * (_att + 1), 2.0))
        if not _acquired:
            audit.record_event(EV_DAEMON_SINGLETON_EXIT, "属主锁未获得:已有属主在线")
            print("属主锁未获得(已有属主在线),本实例退出", file=sys.stderr)
            return 4
        # ⑤开机自启:冻结形态幂等注册(源码形态跳过——开发形态不自启)
        if getattr(sys, "frozen", False):
            if ensure_autostart(str(Path(sys.executable).resolve())):
                audit.record_event(EV_AUTOSTART_REGISTERED, "HKCU Run: DeskPilotDaemon")
        _start_estop_listeners(estop, audit, notifier)
    elif probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
        # stdio 瘦代理：冻结标志归属主(9420 持有人)所有——本进程注册热键
        # 只会抢占复位通道(RegisterHotKey 全系统单持有者,ISS-0002 根因修复)
        audit.record_event(EV_PROXY_SKIPS_HOTKEY,
                           "daemon/既有属主在线；急停热键与甩角监听归其持有")
    else:
        # daemon 不在:心跳新鲜(启动中)则稍候重探;否则试持属主锁
        for _w in range(6):
            if not is_daemon_alive(_shared_dir):
                break
            time.sleep(1.0)
            if probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
                break
        if probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
            audit.record_event(EV_PROXY_SKIPS_HOTKEY,
                               "daemon 启动中(心跳新鲜),转瘦代理")
        else:
            supervisor = RoleSupervisor(
                _shared_dir, "stdio", audit=audit,
                on_become_owner=_become_owner, on_cede=_cede_owner,
                alarm_fn=_alarm_fn)
            if supervisor.start():
                if owner_httpd["d"] is None:
                    # 9420 绑定失败(锁与端口不一致的异常面):放锁退瘦代理
                    supervisor.stop()
                    supervisor = None
                    audit.record_event(EV_PROXY_SKIPS_HOTKEY,
                                       "9420 绑定失败(锁端口不一致),退瘦代理")
                else:
                    audit.record_event(EV_STDIO_BECOME_OWNER,
                                       "daemon 不在,本实例接管 9420/热键/托盘")
                    threading.Thread(target=_ownership_watch, daemon=True,
                                     name="deskpilot-ownership").start()
            else:
                audit.record_event(EV_PROXY_SKIPS_HOTKEY,
                                   "另一 stdio 属主在(属主锁被持)")

    audit.record_event(EV_SERVICE_START, _startup_detail("MCP stdio 就绪"))
    _start_janitor(policy, audit)                 # ISS-0010 C：清理者装配
    if "--daemon" in sys.argv:
        # 常驻形态（ISS-0001）：内部 HTTP 服务，状态跨调用保持
        from .httpd import HttpDaemon
        daemon = HttpDaemon(ctx, estop=estop,
                            idle_timeout_s=policy.idle_timeout_minutes * 60,
                            whitelist_admin=whitelist_admin)
        try:
            daemon.start()
        except RuntimeError as e:
            # ISS-0046 A:预检→绑定竞态的败者干净退出(不抛栈、不僵尸)
            audit.record_event(EV_DAEMON_SINGLETON_EXIT, f"端口绑定失败: {e}")
            print(f"daemon 启动退出: {e}", file=sys.stderr)
            return 4
        audit.record_event(EV_SERVICE_START, _startup_detail(
            f"常驻 HTTP 服务 http://127.0.0.1:{daemon.port}"))
        print(f"DeskPilot 常驻服务已启动: http://127.0.0.1:{daemon.port}",
              file=sys.stderr)
        # ISS-0012 E1：系统托盘图标（白名单管理可视化入口；托盘即在跑;
        # ISS-0084 ②:托盘随属主——daemon 属主形态此处,stdio 属主见
        # _become_owner)
        from .tray import TrayIcon
        base_url = f"http://127.0.0.1:{daemon.port}"

        tray = TrayIcon(on_manage=_open_manager_for(
            daemon.port, audit=audit,
            stderr_log=audit_paths.logs / "manager-window.log"))
        tray.start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            tray.stop()
            daemon.stop()
            if supervisor is not None:
                supervisor.stop()
            audit.record_event(EV_SERVICE_STOP, "常驻服务停止")
            return 0
    serve(ctx)                                   # 阻塞于 stdio
    audit.record_event(EV_SERVICE_STOP, "stdio 关闭")
    return 0
