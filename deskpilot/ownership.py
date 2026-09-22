"""ISS-0084 属主权模块(§7 整改设计,sdfang 2026-09-15 裁「全做」)。

进程属主 = 持 `audit/owner.lock` 文件锁者(msvcrt.locking 非阻塞;进程退出
OS 自动放锁,无残留锁)。**持锁者 = 属主**:开 9420 HTTP + 注册热键 + 挂托盘;
daemon 复出时 stdio 属主让位(②属主协议 + ⑥管理入口随 MCP 存活)。

心跳(`daemon-heartbeat.json`,周期原子写)+ 遗嘱(atexit/excepthook)使
一切死亡有痕(①);心跳过期告警使「守护进程不在」主动可知(③);
`ensure_autostart` 幂等注册开机自启(⑤)。④死因排查为非代码项,
①落地后观察。
"""

from __future__ import annotations

import atexit
import json
import msvcrt
import os
import sys
import threading
import time
from pathlib import Path

OWNER_LOCK_NAME = "owner.lock"
HEARTBEAT_NAME = "daemon-heartbeat.json"
HEARTBEAT_FRESH_S = 30.0    # 心跳新鲜度阈值(秒)
BEAT_INTERVAL_S = 10.0      # 心跳周期(秒)

_RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "DeskPilotDaemon"


def _version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return "unknown"


# ---------- 属主文件锁 ----------

class OwnerLock:
    """`audit/owner.lock` 文件锁:持锁者 = 属主(9420/热键/托盘)。

    msvcrt.locking 非阻塞(LK_NBLCK);进程死亡 OS 自动放锁——无残留锁、
    无「锁文件还在但进程没了」的陈旧锁问题。
    """

    def __init__(self, audit_dir: str, role: str):
        self._path = Path(audit_dir) / OWNER_LOCK_NAME
        self._role = role
        self._fh = None

    @property
    def is_owner(self) -> bool:
        return self._fh is not None

    def acquire(self) -> bool:
        if self._fh is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "a+b")
        # msvcrt.locking 作用于**句柄当前位置**的单字节,纪律:
        # ①空文件先补占位字节(空文件上锁后再写会 PermissionError,实测);
        # ②锁前 seek(0)(append 模式初始位置在 EOF,不 seek 会锁到别的字节,
        #   实测出现「第二句柄锁成功」的假共存);③释放前也须 seek(0)。
        try:
            if fh.seek(0, os.SEEK_END) == 0:
                fh.write(b" ")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"pid": os.getpid(), "role": self._role,
                             "ts": time.time()}).encode())
        fh.flush()
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._fh.close()
        self._fh = None


# ---------- 心跳 ----------

class HeartbeatWriter:
    """周期原子写心跳 {pid, role, ts, version};测试直接调 `beat_once`。

    daemon 与 stdio 属主同机制(role 字段区分)——stdio 侧死亡同样曾不可见
    (断连死因即缺此观测),纳入同一机制(①)。
    """

    def __init__(self, audit_dir: str, role: str, clock=time.time,
                 interval: float = BEAT_INTERVAL_S, audit=None):
        self._path = Path(audit_dir) / HEARTBEAT_NAME
        self._role = role
        self._clock = clock
        self._interval = interval
        # ISS-0094 ①:终败/恢复审计通道(可选;无则事件不落盘,对齐 _audit 惯例)
        self._audit = audit
        # ISS-0094 ②:tmp 按 pid 区分(构造期捕获,消除复出窗口双写互踩)
        self._pid = os.getpid()
        # ISS-0094 ①:节流状态(连续失败只记首败,恢复另记一条后复位)
        self._beat_failed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def beat_once(self) -> Path | None:
        """原子写一次心跳；成功返回路径，终败返回 None 不上抛。

        ISS-0094 ①（对齐 freeze_notify ISS-0092 ② 防护形态）：写盘
        OSError 三段退避重试（0.05/0.15/0.45s，每轮先预清同名旧 tmp）；
        终败记审计「心跳写失败」——节流（连续失败只记首败，恢复另记
        「心跳写恢复」一条；审计自身失败不上抛）。心跳是观测面，
        写失败不得阻断主功能（调用方 start() 直连本方法,故终败不上抛）。
        ISS-0094 ②：tmp 按 pid 区分（daemon-heartbeat.{pid}.tmp）。
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pid": self._pid, "role": self._role,
                   "ts": self._clock(), "version": _version()}
        tmp = self._path.with_name(f"{self._path.stem}.{self._pid}.tmp")
        last: OSError | None = None
        for backoff in (0.05, 0.15, 0.45):
            try:
                tmp.unlink(missing_ok=True)      # 预清同名旧 tmp(孤儿残留)
                tmp.write_text(json.dumps(payload, ensure_ascii=False),
                               encoding="utf-8")
                os.replace(tmp, self._path)
            except OSError as e:
                last = e
                time.sleep(backoff)
                continue
            self._record_recovery()
            return self._path
        self._record_failure(last)
        return None

    def _record_failure(self, e: OSError | None) -> None:
        """终败审计（节流:连续失败只记首败）。"""
        if self._beat_failed:
            return
        self._beat_failed = True
        self._audit_event(
            "心跳写失败",
            f"重试 3 次仍失败: {e!r}（节流:连续失败仅记首败,恢复另记一条）")

    def _record_recovery(self) -> None:
        """恢复审计（连败后首次成功另记一条,复位节流状态）。"""
        if not self._beat_failed:
            return
        self._beat_failed = False
        self._audit_event("心跳写恢复", "连续写失败后恢复落盘")

    def _audit_event(self, event: str, detail: str) -> None:
        """审计自身失败不上抛（观测面不得反噬主功能）。"""
        if self._audit is None:
            return
        try:
            self._audit.record_event(event, detail)
        except Exception:                           # noqa: BLE001
            pass

    def start(self) -> None:
        if self._thread is not None:
            return

        def _loop():
            while not self._stop.wait(self._interval):
                try:
                    self.beat_once()
                except Exception:                   # noqa: BLE001
                    pass        # 心跳是观测面,写失败不阻断主功能
        self._thread = threading.Thread(target=_loop, daemon=True,
                                        name="deskpilot-heartbeat")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
            self._thread = None


def is_daemon_alive(audit_dir: str, now: float | None = None) -> bool:
    """心跳文件存在、role=="daemon" 且 ts 新鲜(<30s)→ daemon 在。"""
    path = Path(audit_dir) / HEARTBEAT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if data.get("role") != "daemon":
        return False
    try:
        ts = float(data["ts"])
    except (TypeError, ValueError, KeyError):
        return False
    now = time.time() if now is None else now
    return now - ts < HEARTBEAT_FRESH_S


# ---------- 遗嘱 ----------

def write_last_will(audit_log, role: str, reason: str) -> None:
    """遗嘱载荷(钩子本体):落审计「进程退出」带角色与原因。尽力而为。"""
    try:
        if audit_log is not None:
            audit_log.record_event("进程退出", f"{role}: {reason}")
    except Exception:                               # noqa: BLE001
        pass


_will_installed_roles: set[str] = set()


def install_last_will(audit_log, role: str) -> None:
    """挂 atexit + sys.excepthook 钩子;同角色幂等(重复调用不重复挂)。"""
    if role in _will_installed_roles:
        return
    _will_installed_roles.add(role)
    atexit.register(write_last_will, audit_log, role, "正常退出")
    old_hook = sys.excepthook

    def _hook(exc_type, exc, tb):
        write_last_will(audit_log, role,
                        f"异常: {exc_type.__name__}: {exc}")
        old_hook(exc_type, exc, tb)

    sys.excepthook = _hook


# ---------- 开机自启 ----------

def ensure_autostart(exe_path: str, winreg_mod=None) -> bool:
    """冪等注册 HKCU Run `DeskPilotDaemon = "<exe>" --daemon`。

    返回是否发生了写入;已注册且内容一致 → 不写(False)。测试替身 winreg。
    """
    import winreg as _winreg
    wr = winreg_mod or _winreg
    value = f'"{exe_path}" --daemon'
    key = wr.OpenKey(wr.HKEY_CURRENT_USER, _RUN_SUBKEY, 0,
                     wr.KEY_READ | wr.KEY_SET_VALUE)
    try:
        try:
            existing = wr.QueryValueEx(key, _AUTOSTART_NAME)[0]
        except FileNotFoundError:
            existing = None
        if existing == value:
            return False
        wr.SetValueEx(key, _AUTOSTART_NAME, 0, wr.REG_SZ, value)
        return True
    finally:
        wr.CloseKey(key)


# ---------- 属主状态机 ----------

class RoleSupervisor:
    """属主状态机:`start` 抢锁;`tick` 周期检查(daemon 复出让位 + 死亡告警)。

    `on_become_owner`/`on_cede` 为装配回调(热键/托盘/HTTP 的起停归 main
    装配,测试注替身);`alarm_fn(message)` 为告警回调(弹窗/通知)。
    """

    def __init__(self, audit_dir: str, role: str, audit=None,
                 clock=time.time, on_become_owner=None, on_cede=None,
                 alarm_fn=None):
        self._lock = OwnerLock(audit_dir, role)
        self._dir = Path(audit_dir)
        self._role = role
        self._audit = audit
        self._clock = clock
        self._on_become = on_become_owner
        self._on_cede = on_cede
        self._alarm_fn = alarm_fn
        self._heartbeat: HeartbeatWriter | None = None
        self._last_alarmed_ts: float | None = None   # 死亡期去重键(③不轰炸)

    @property
    def is_owner(self) -> bool:
        return self._lock.is_owner

    def start(self) -> bool:
        """心跳先行(复出信号先于持锁,daemon 起舞的前提),再抢锁;抢到 →
        属主(on_become_owner)。抢不到 → 停心跳(瘦身),返回 False。"""
        self._heartbeat = HeartbeatWriter(str(self._dir), self._role,
                                          clock=self._clock,
                                          audit=self._audit)
        self._heartbeat.beat_once()
        self._heartbeat.start()
        if not self._lock.acquire():
            self._heartbeat.stop()
            self._heartbeat = None
            return False
        if self._on_become is not None:
            self._on_become()
        return True

    def tick(self) -> None:
        """周期检查:属主在 daemon 复出时让位;非属主在 daemon 死亡/锁空时
        自愈接管;所有角色都做死亡告警检查(③「任一实例」)。"""
        if self._lock.is_owner:
            if (self._role == "stdio"
                    and is_daemon_alive(str(self._dir), now=self._clock())):
                self._cede()
                return
        elif (self._role == "stdio"
                and not is_daemon_alive(str(self._dir), now=self._clock())):
            # daemon 不在且锁空 → 自愈接管(死亡放锁/锁空)
            if self._lock.acquire():
                self._heartbeat = HeartbeatWriter(str(self._dir), self._role,
                                                  clock=self._clock,
                                                  audit=self._audit)
                self._heartbeat.beat_once()
                self._heartbeat.start()
                if self._audit is not None:
                    self._audit.record_event("stdio 接管属主",
                                             "daemon 不在,本实例升属主")
                if self._on_become is not None:
                    self._on_become()
        self._alarm_check()

    def _alarm_check(self) -> None:
        """daemon 心跳文件存在但过期(曾活过,现死了) → 每段死亡期告警一次。"""
        path = self._dir / HEARTBEAT_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ts = float(data["ts"])
            role = data.get("role")
        except (OSError, ValueError, TypeError, KeyError):
            return          # 无文件/坏文件 = 从未有 daemon,不告「死亡」
        if role != "daemon":
            return          # stdio 心跳不是 daemon 存活证据
        if self._clock() - ts >= HEARTBEAT_FRESH_S and ts != self._last_alarmed_ts:
            self._last_alarmed_ts = ts
            if self._audit is not None:
                self._audit.record_event(
                    "daemon 死亡告警",
                    f"心跳过期({int(self._clock() - ts)}s 未更新):白名单管理/"
                    f"热键复位不可用,请重启 daemon")
            if self._alarm_fn is not None:
                self._alarm_fn("daemon 死亡:心跳过期")

    def stop(self) -> None:
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        self._lock.release()

    def _cede(self) -> None:
        """daemon 复出回迁:停心跳/回调停热键托盘 HTTP/放锁。"""
        if self._audit is not None:
            self._audit.record_event("stdio 属主让位", "daemon 复出,退回瘦代理")
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        if self._on_cede is not None:
            self._on_cede()
        self._lock.release()
