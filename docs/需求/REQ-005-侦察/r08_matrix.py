# -*- coding: utf-8 -*-
"""REQ-005 三轮·因果钉死:{SPI×CDP enable×flag} 三因子对 UIA 内容的影响。

4 个独立受管实例(互不沾):
  M1: 纯基线(无 SPI、无 CDP enable、无 flag)
  M2: 仅 SPI(拉起后设,不碰 CDP Accessibility)
  M3: 仅 --force-renderer-accessibility(不设 SPI、不碰 CDP)
  M4: 仅 CDP Accessibility.enable(不设 SPI、无 flag)
观测:直读 uiautomation 从 render widget 根 walk(深度 16/帽 3000),
0/3/8s 三采。SPI 原值先读、测完还原。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r05_cdp_client  # noqa: E402
from r05_cdp_client import (CDP, read_devtools_active_port,  # noqa: E402
                            kill_managed_edge)
from r08_a11y import spi_get, spi_set, render_widget_hwnd  # noqa: E402

import uiautomation as uia  # noqa: E402

URL = "https://www.baidu.com"


def find_managed_hwnd():
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, lp):
        if ctypes.windll.user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(h, buf, 256)
            if "Edge" in buf.value:
                r = wt.RECT()
                ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
                if abs(r.left - 60) < 25 and abs(r.top - 40) < 25:
                    hits.append(h)
        return True

    ctypes.windll.user32.EnumWindows(cb, 0)
    return hits[0] if hits else None


def walk_count(rw):
    root = uia.ControlFromHandle(rw)
    nodes = []

    def walk(c, d=0):
        if d > 16 or len(nodes) > 3000:
            return
        try:
            nodes.append((c.ControlTypeName, c.Name))
        except Exception:
            pass
        try:
            ch = c.GetChildren()
        except Exception:
            return
        for x in ch:
            walk(x, d + 1)

    walk(root)
    types: dict[str, int] = {}
    for t, _ in nodes:
        types[t] = types.get(t, 0) + 1
    links = [n for t, n in nodes if t == "HyperlinkControl" and n][:6]
    edits = [n for t, n in nodes
             if t in ("EditControl", "ButtonControl")][:6]
    return {"total": len(nodes), "types": types,
            "sample_links": links, "sample_edit_btn": edits}


def run_case(tag, use_spi, use_flag, use_cdp, R):
    tmp = tempfile.mkdtemp(prefix="req008m-")
    flags = ["--window-size=1280,900", "--window-position=60,40",
             "--lang=zh-CN"]
    if use_flag:
        flags.append("--force-renderer-accessibility")
    proc = r05_cdp_client.launch_managed_edge(tmp, extra_args=flags, url=URL)
    cdp = None
    try:
        port, ws = read_devtools_active_port(tmp)
        cdp = CDP(f"ws://127.0.0.1:{port}{ws}", timeout=40)
        targets = cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        sid = cdp.call("Target.attachToTarget",
                       {"targetId": page["targetId"], "flatten": True})["sessionId"]
        time.sleep(5)
        if use_cdp:
            cdp.call("Accessibility.enable", session_id=sid)
        hwnd = None
        for _ in range(20):
            hwnd = find_managed_hwnd()
            if hwnd:
                break
            time.sleep(0.5)
        rw, _ = render_widget_hwnd(hwnd)
        if use_spi:
            spi_set(True)
        polls = {}
        t = 0
        for wait in (0, 3, 8):
            time.sleep(wait - t)
            t = wait
            s = walk_count(rw)
            polls[f"t{wait}s"] = s["total"]
            print(f"{tag} t+{wait}s: {s['total']}")
        final = walk_count(rw)
        R[tag] = {"spi": use_spi, "flag": use_flag, "cdp": use_cdp,
                  "polls": polls, "final": final}
        print(tag, "final:", final["total"],
              "links:", final["sample_links"][:3],
              "edit/btn:", final["sample_edit_btn"][:3])
    finally:
        if use_spi:
            spi_set(R["spi_original"])
        if cdp:
            cdp.close()
        kill_managed_edge(tmp, proc.pid)
        for _ in range(10):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.8)
        R[f"cleanup_{tag}"] = not os.path.exists(tmp)


def main():
    R: dict = {"spi_original": spi_get()}
    run_case("M1_baseline", False, False, False, R)
    run_case("M2_spi_only", True, False, False, R)
    run_case("M3_flag_only", False, True, False, R)
    run_case("M4_cdp_only", False, False, True, R)
    R["spi_final"] = spi_get()
    with open(os.path.join(HERE, "r08_matrix.json"), "w",
              encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)
    print("SAVED r08_matrix.json spi_final:", R["spi_final"])


if __name__ == "__main__":
    main()
