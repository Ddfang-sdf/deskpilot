# -*- coding: utf-8 -*-
"""REQ-005 二轮:UIA 通道对 Chromium 网页内容的懒启用实测。

假说:Chrome 的渲染进程 accessibility 在首个 UIA 请求后异步开启——
首次 walk 只见浏览器壳,等待后二次 walk 才能见到网页内容。
方法:受管 Edge 百度页,uiautomation 直读(诊断通道),同窗 walk 三次
(0s/3s/8s),统计元素数与网页内容标志(含页面链接名的 Hyperlink)。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from r05_cdp_client import launch_managed_edge, read_devtools_active_port, \
    kill_managed_edge  # noqa: E402

import ctypes
import ctypes.wintypes as wt
import uiautomation as uia  # noqa: E402


def find_hwnd(title_part):
    hwnds = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, lp):
        if ctypes.windll.user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(h, buf, 256)
            if title_part in buf.value:
                hwnds.append(h)
        return True

    ctypes.windll.user32.EnumWindows(cb, 0)
    return hwnds[0] if hwnds else None


def walk(control, nodes, depth=0, max_depth=14, cap=2000):
    if depth > max_depth or len(nodes) >= cap:
        return
    try:
        nodes.append({"name": control.Name, "type": control.ControlTypeName})
    except Exception:
        pass
    try:
        children = control.GetChildren()
    except Exception:
        return
    for c in children:
        walk(c, nodes, depth + 1, max_depth, cap)


def survey(hwnd):
    root = uia.ControlFromHandle(hwnd)
    nodes: list = []
    walk(root, nodes)
    types: dict[str, int] = {}
    for n in nodes:
        types[n["type"]] = types.get(n["type"], 0) + 1
    content_marks = [n["name"] for n in nodes
                     if n["type"] == "HyperlinkControl"
                     and any(k in (n["name"] or "")
                             for k in ("新闻", "地图", "贴吧", "图片"))]
    return {"elements": len(nodes), "type_counts": types,
            "page_content_links": content_marks[:6]}


def main():
    tmp = tempfile.mkdtemp(prefix="req007lazy-")
    proc = launch_managed_edge(tmp, extra_args=[
        "--window-size=1280,900", "--window-position=60,40",
        "--lang=zh-CN"], url="https://www.baidu.com")
    out = {}
    try:
        read_devtools_active_port(tmp)
        time.sleep(6)
        hwnd = find_hwnd("百度一下")
        out["t0"] = survey(hwnd)
        print("t0:", out["t0"]["elements"],
              json.dumps(out["t0"]["type_counts"])[:180],
              out["t0"]["page_content_links"])
        time.sleep(3)
        out["t3"] = survey(hwnd)
        print("t3:", out["t3"]["elements"],
              out["t3"]["page_content_links"])
        time.sleep(5)
        out["t8"] = survey(hwnd)
        print("t8:", out["t8"]["elements"],
              out["t8"]["page_content_links"])
        out["lazy_confirmed"] = (
            out["t8"]["elements"] > out["t0"]["elements"]
            or len(out["t8"]["page_content_links"]) > 0)
    finally:
        kill_managed_edge(tmp, proc.pid)
        for _ in range(10):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.8)
        out["cleanup"] = not os.path.exists(tmp)
    with open(os.path.join(HERE, "r07_uia_lazy.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("SAVED r07_uia_lazy.json lazy_confirmed:", out["lazy_confirmed"])


if __name__ == "__main__":
    main()
