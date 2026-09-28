"""M4 共管浏览器管理器(REQ-005 详设 §3.7):拉起(幂等)/注册/回收/探活。

拉起参数:--remote-debugging-port=0 --force-renderer-accessibility
--user-data-dir=%LOCALAPPDATA%\\DeskPilot\\browser-profile;二进制选择序
Edge → Chrome(注册表/常见路径探测,均无则报错含安装指引)。
归属注册表为内存态:拉起写入、回收注销。
T4-04:拉起/回收/死亡全程审计(词汇表三事件);拉起提示走 i18n
双键(REQ-007 规)。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..audit_events import (EV_BROWSER_INSTANCE_DEAD,
                            EV_BROWSER_INSTANCE_LAUNCH,
                            EV_BROWSER_INSTANCE_RECLAIM)
from ..errors import WINDOW_GONE, ExecutorError
from ..i18n import tr

_REGISTRY: dict = {}                 # 归属注册表(内存态,T4:拉起写入/回收注销)
_AUDIT = None                        # 装配缝:daemon 装配期挂 AuditLogger


def set_audit(audit) -> None:
    """装配缝:挂审计通道(T4-04 全程留痕)。"""
    global _AUDIT
    _AUDIT = audit


def _audit_event(event: str, detail: str) -> None:
    if _AUDIT is None:
        return
    try:
        _AUDIT.record_event(event, detail)
    except Exception:
        pass


# ---------- 纯决策面(单元钉;可调用缝注入) ----------

def ensure_instance(*, registry: dict, launch, alive) -> dict:
    """幂等拉起(T4-01):注册表已有存活实例则直接复用,不重复拉起。

    入参:registry=归属注册表(内存态 dict);launch=拉起接缝(可调用,
    返回归属注册表项);alive=实例探活接缝。返回:归属注册表项
    {窗口 hwnd、CDP 端口、profile 路径、拉起时间、浏览器二进制路径}。
    """
    inst = registry.get("managed")
    if inst is not None and alive(inst):
        return inst                           # T4-01:复用不重复拉起
    inst = launch()
    registry["managed"] = inst
    return inst


def reclaim(*, registry: dict, kill_by_profile) -> list:
    """回收(T4-03):注册表注销 + 按 profile 路径匹配进程命令行补刀。

    入参:registry=归属注册表;kill_by_profile=按 profile 清理接缝。
    返回:被清理的实例标识清单。
    """
    cleaned = []
    for key in list(registry.keys()):
        inst = registry.pop(key)
        kill_by_profile(inst.get("profile", ""))
        cleaned.append(key)
    return cleaned


def probe(instance: dict, *, port_alive, process_alive) -> bool:
    """探活(T5-02):端口+进程双查,有一失败即判死。"""
    return bool(port_alive(instance.get("port"))
                and process_alive(instance.get("pid")))


# ---------- 生产面(拉起/探活/补刀的真实实现) ----------

def _profile_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))
    return base / "DeskPilot" / "browser-profile"


def _find_binary() -> str:
    """二进制选择序 Edge → Chrome(注册表/常见路径探测);均无则报错
    含安装指引。"""
    candidates = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise ExecutorError(
        WINDOW_GONE,
        "未找到可共管的浏览器(Edge/Chrome 均无);请安装 Microsoft Edge "
        "后重试(共管浏览器为系统级预装组件,通常无需安装)")


def _read_devtools_port(profile: Path, timeout_s: float = 15.0):
    """T4-02:DevToolsActivePort 读首行端口+次行 ws 路径;读不到=拉起
    失败(带日志指引)。"""
    f = profile / "DevToolsActivePort"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2 and lines[0].strip().isdigit():
                return int(lines[0].strip()), lines[1].strip()
        except OSError:
            pass
        time.sleep(0.2)
    raise ExecutorError(
        WINDOW_GONE,
        f"共管浏览器拉起后 DevToolsActivePort 不可读({f});"
        "请检查浏览器日志或改用用户自拉浏览器窗口(window 参数)")


def _hwnd_of_pid(pid: int) -> int | None:
    """按 pid 找主窗口句柄(顶层可见窗)。"""
    import ctypes
    from ctypes import wintypes
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)

    def _cb(hwnd, _lp):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            p = wintypes.DWORD(0)
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(p))
            if p.value == pid:
                found.append(hwnd)
                return False
        return True

    ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found[0] if found else None


def _real_launch() -> dict:
    """真实拉起(详设 §3.7 拉起参数表)+审计+拉起提示(T4-04)。"""
    binary = _find_binary()
    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [binary, "--remote-debugging-port=0",
         "--force-renderer-accessibility",
         f"--user-data-dir={profile}"])
    port, ws_path = _read_devtools_port(profile)
    hwnd = None
    deadline = time.monotonic() + 10.0
    while hwnd is None and time.monotonic() < deadline:
        hwnd = _hwnd_of_pid(proc.pid)
        if hwnd is None:
            time.sleep(0.3)
    inst = {"hwnd": hwnd, "port": port, "profile": str(profile),
            "launched_at": time.time(), "binary": binary,
            "pid": proc.pid, "ws_path": ws_path}
    # T4-04:拉起审计 + 身份类登录提示(i18n 双键)
    print(f"{tr('br.launch.title')}: {tr('br.launch.hint')}",
          file=sys.stderr)
    _audit_event(EV_BROWSER_INSTANCE_LAUNCH,
                 f"pid={proc.pid} port={port} binary={binary}")
    return inst


def _port_alive(port) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)),
                                      timeout=0.5):
            return True
    except (OSError, ValueError):
        return False


def _process_alive(pid) -> bool:
    import ctypes
    if not pid:
        return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def _kill_by_profile(profile: str) -> None:
    """T4-03:按 profile 路径匹配进程命令行补刀(壳不级联实测坑)。"""
    if not profile:
        return
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object "
             "{ $_.CommandLine -and $_.CommandLine.Contains('"
             + profile.replace("'", "''") + "') } | ForEach-Object "
             "{ Stop-Process -Id $_.ProcessId -Force -ErrorAction "
             "SilentlyContinue }"],
            capture_output=True, timeout=15)
    except Exception:
        pass


class Manager:
    """生产门面(路由器默认装配):模块级注册表 + 真拉起/探活/回收。"""

    def lookup(self, hwnd):
        for inst in _REGISTRY.values():
            if inst.get("hwnd") == hwnd:
                return inst
        return None

    def ensure_instance(self) -> dict:
        return ensure_instance(
            registry=_REGISTRY, launch=_real_launch,
            alive=lambda i: probe(i, port_alive=_port_alive,
                                  process_alive=_process_alive))

    def probe(self, instance) -> bool:
        alive = probe(instance, port_alive=_port_alive,
                      process_alive=_process_alive)
        if not alive:
            _audit_event(EV_BROWSER_INSTANCE_DEAD,
                         f"hwnd={instance.get('hwnd')} "
                         f"port={instance.get('port')}")
        return alive

    def reclaim_all(self) -> list:
        """T4-03:daemon 停止等回收触发点(daemon 装配侧调用)。"""
        cleaned = reclaim(registry=_REGISTRY,
                          kill_by_profile=_kill_by_profile)
        for key in cleaned:
            _audit_event(EV_BROWSER_INSTANCE_RECLAIM, key)
        return cleaned
