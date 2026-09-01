"""ISS-0008 性能基准（scripts/benchmark_iss8.py，TC-BM-01~05）。

measure_all()：全指标实测，返回 {指标: {value, unit, method, samples}}。
main()：打印对照表。

测量行为（TC-BM-04/05 语义内建）：
- daemon 杀起恢复——测量结束 daemon 必在线；
- 弹窗残留清理——测量结束无"审批"窗口。
全部本地实测，无任何网络依赖。
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import threading
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

EXE = str(Path(__file__).resolve().parents[1] / "dist" / "deskpilot.exe")
BASE = "http://127.0.0.1:9420"
_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32

# ---------------- 基础工具 ----------------

def _post(tool: str, params: dict, timeout: float = 120.0) -> dict:
    body = json.dumps({"tool": tool, "params": params}).encode()
    req = urllib.request.Request(f"{BASE}/call", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _health_ok(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _deskpilot_pids() -> list[int]:
    """deskilot.exe 全部进程 PID（psapi 枚举）。"""
    psapi = ctypes.windll.psapi
    pids = (wintypes.DWORD * 1024)()
    needed = wintypes.DWORD()
    out = []
    if psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed)):
        for i in range(min(needed.value // 4, 1024)):
            h = _k32.OpenProcess(0x1000, False, pids[i])
            if not h:
                continue
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if _k32.QueryFullProcessImageNameW(h, 0, buf,
                                                   ctypes.byref(size)):
                    if Path(buf.value).name.lower() == "deskpilot.exe":
                        out.append(pids[i])
            finally:
                _k32.CloseHandle(h)
    return out


def _kill_daemon() -> None:
    for pid in _deskpilot_pids():
        h = _k32.OpenProcess(0x0001, False, pid)          # PROCESS_TERMINATE
        if h:
            try:
                _k32.TerminateProcess(h, 0)
            finally:
                _k32.CloseHandle(h)
    time.sleep(0.8)


def _start_daemon() -> None:
    subprocess.Popen([EXE, "--daemon"],
                     creationflags=0x00000008)             # DETACHED_PROCESS
    t0 = time.monotonic()
    while time.monotonic() - t0 < 20:
        if _health_ok():
            return
        time.sleep(0.1)
    raise RuntimeError("daemon 启动超时")


def _find_window(*titles: str) -> int:
    for t in titles:
        hwnd = _u32.FindWindowW(None, t)
        if hwnd:
            return hwnd
    return 0


def _close_approval_windows() -> int:
    n = 0
    for title in ("DeskPilot 入白审批", "DeskPilot 审批"):
        while True:
            hwnd = _u32.FindWindowW(None, title)
            if not hwnd:
                break
            _u32.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE
            n += 1
            time.sleep(0.15)
    return n


# ---------------- 指标 ----------------

def m_cold_start() -> dict:
    ts = []
    for _ in range(3):
        _kill_daemon()
        t0 = time.monotonic()
        _start_daemon()
        ts.append(round(time.monotonic() - t0, 2))
    return {"value": ts, "unit": "s", "samples": 3,
            "method": "杀进程→启动→/health 200 ×3",
            "median": sorted(ts)[1]}


def m_l0_latency() -> dict:
    lat = []
    for _ in range(10):
        t0 = time.monotonic()
        _post("get_cursor", {}, timeout=10)
        lat.append(round((time.monotonic() - t0) * 1000, 1))
    lat_s = sorted(lat)
    return {"value": lat_s[len(lat_s) // 2], "unit": "ms", "samples": 10,
            "method": "/call get_cursor ×10 取中位", "raw": lat}


def m_approval_cycle() -> tuple[dict, dict]:
    """一次 L3 审批挂起，同周期测两项（共享写锁语义，避免串行锁互相饿死）：

    - dialog_thread_ms：/call→FindWindowW 命中（线程内建窗出现延迟）
    - health_during_approval_ms：挂起中 /health ×5 取最大
    说明：挂起的审批在 approval_ttl(90s)后自动超时释放写锁（写路径串行为设计语义）。
    """
    def call():
        try:
            _post("launch_app", {"app": "no-such-xyz-app.exe"}, timeout=120)
        except Exception:
            pass
    t0 = time.monotonic()
    threading.Thread(target=call, daemon=True).start()
    ms = None
    while time.monotonic() - t0 < 15:
        if _find_window("DeskPilot 入白审批", "DeskPilot 审批"):
            ms = round((time.monotonic() - t0) * 1000)
            break
        time.sleep(0.01)
    lat = []
    for _ in range(5):
        t1 = time.monotonic()
        _health_ok(timeout=3)
        lat.append(round((time.monotonic() - t1) * 1000, 1))
        time.sleep(0.2)
    _close_approval_windows()
    thread = {"value": ms, "unit": "ms", "samples": 1,
              "method": "/call→FindWindowW 命中（线程内建窗）"}
    health = {"value": max(lat), "unit": "ms", "samples": 5,
              "method": "L3 审批挂起中 /health ×5 取最大", "raw": lat}
    return thread, health


def m_dialog_subprocess() -> dict:
    desc = Path("C:/temp/bm-desc.txt")
    desc.parent.mkdir(parents=True, exist_ok=True)
    desc.write_text("基准测量\n---\n子进程弹窗", encoding="utf-8")
    result = Path("C:/temp/bm-result.txt")
    t0 = time.monotonic()
    p = subprocess.Popen([EXE, "--approval-dialog", str(desc), str(result), "90"])
    ms = None
    while time.monotonic() - t0 < 15:
        if _find_window("DeskPilot 审批", "DeskPilot 入白审批"):
            ms = round((time.monotonic() - t0) * 1000)
            break
        time.sleep(0.01)
    try:
        p.terminate()
    except Exception:
        pass
    _close_approval_windows()
    return {"value": ms, "unit": "ms", "samples": 1,
            "method": "spawn exe --approval-dialog→FindWindowW（热缓存）"}


def m_jpeg_encode() -> dict:
    import mss
    from PIL import Image
    with mss.mss() as sct:
        img = sct.grab(sct.monitors[1])
    im = Image.frombytes("RGB", img.size, img.rgb)
    n = 5
    t0 = time.monotonic()
    for _ in range(n):
        im.save("C:/temp/bm.png")
    tp = (time.monotonic() - t0) / n * 1000
    t0 = time.monotonic()
    for _ in range(n):
        im.save("C:/temp/bm.jpg", quality=80)
    tj = (time.monotonic() - t0) / n * 1000
    pct = round((1 - tj / tp) * 100)
    import os
    ps, js = (os.path.getsize("C:/temp/bm.png") / 1024,
              os.path.getsize("C:/temp/bm.jpg") / 1024)
    return {"value": pct, "unit": "%", "samples": n,
            "method": "1920×1080 编码 ×5(PNG vs JPEG q80)",
            "png_ms": round(tp, 1), "jpeg_ms": round(tj, 1)}


def m_png_vs_jpeg_size() -> dict:
    import os
    ps = os.path.getsize("C:/temp/bm.png") / 1024
    js = os.path.getsize("C:/temp/bm.jpg") / 1024
    return {"value": {"png_kb": round(ps), "jpeg_kb": round(js),
                      "ratio_pct": round(js / ps * 100)},
            "unit": "KB", "samples": 1,
            "method": "同区域图同存两种格式（内容相关，如实呈现）"}


def m_exe_size() -> dict:
    mb = round(Path(EXE).stat().st_size / 1024 / 1024, 1)
    return {"value": mb, "unit": "MB", "samples": 1, "method": "dist exe 文件大小"}


def m_daemon_rss() -> dict:
    psapi = ctypes.windll.psapi

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    rss = 0
    for pid in _deskpilot_pids():
        h = _k32.OpenProcess(0x1000, False, pid)
        if h:
            try:
                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    rss = max(rss, pmc.WorkingSetSize)
            finally:
                _k32.CloseHandle(h)
    return {"value": round(rss / 1024 / 1024), "unit": "MB", "samples": 1,
            "method": "WorkingSet64(含暖源缓存)"}


# ---------------- 汇总 ----------------

def measure_all() -> dict:
    """全指标实测；测完 daemon 在线、无审批窗口残留（TC-BM-04/05）。"""
    thread, health = m_approval_cycle()
    out = {
        "cold_start_s": m_cold_start(),
        "l0_latency_ms": m_l0_latency(),
        "health_during_approval_ms": health,
        "dialog_thread_ms": thread,
        "dialog_subprocess_ms": m_dialog_subprocess(),
        "jpeg_encode_speedup_pct": m_jpeg_encode(),
        "png_vs_jpeg_size": m_png_vs_jpeg_size(),
        "exe_size_mb": m_exe_size(),
        "daemon_rss_mb": m_daemon_rss(),
    }
    # TC-BM-04/05 恢复语义:daemon 在线 + 无弹窗残留
    if not _health_ok():
        _start_daemon()
    _close_approval_windows()
    return out


def main() -> None:
    r = measure_all()
    print(f"{'指标':<28}{'实测值':<16}{'单位':<6}方法")
    for k, v in r.items():
        print(f"{k:<28}{str(v['value']):<16}{v['unit']:<6}{v['method']}")


if __name__ == "__main__":
    main()
