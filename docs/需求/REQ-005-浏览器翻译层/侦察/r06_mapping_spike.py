# -*- coding: utf-8 -*-
"""REQ-005 技术穿刺:CDP viewport CSS 坐标 → 虚拟桌面物理坐标 映射精度实测。

假设公式: screen = 内容区矩形原点 + viewport_css × devicePixelRatio
物理点击全部经 daemon 强制层(/call 端点,与 scripts/mcp_call.py 常驻模式同通道)。
真值来源:daemon 物理截图 + 按钮纯色像素扫描(独立于公式)。
dpr≠1 的真实物理缩放用 --force-device-scale-factor 受管实例(等价于系统 DPI/
页面缩放对渲染的物理效应);ctrl+= 键事件缩放与 Emulation 指标覆盖两法如实记录。
产物:穿刺数据-坐标映射.json
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
import urllib.request

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from r05_cdp_client import (CDP, launch_managed_edge, read_devtools_active_port,
                            kill_managed_edge)  # noqa: E402

TESTPAGE = "file:///" + os.path.join(HERE, "r06_testpage.html").replace("\\", "/")
OUT_JSON = os.path.join(HERE, "穿刺数据-坐标映射.json")
# daemon 装配的允许根=dist ∪ dist/audit(从 dist 启动),截图只能落其内
SHOT_DIR = r"C:\code\workspace\deskpilot\dist\audit\req006_shots"

BUTTONS_FIXED = ["b_tl", "b_tr", "b_c", "b_bl", "b_br"]
BUTTONS_SCROLL = ["s_l", "s_c", "s_r"]
COLORS = {  # 与 r06_testpage.html 一致
    "b_tl": (255, 209, 102), "b_tr": (6, 214, 160), "b_c": (17, 138, 178),
    "b_bl": (239, 71, 111), "b_br": (131, 56, 236),
    "s_l": (255, 159, 28), "s_c": (46, 196, 182), "s_r": (231, 29, 54),
}


def dcall(tool, params):
    payload = json.dumps({"tool": tool, "params": params},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:9420/call", data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def render_widget_rect(hwnd):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, lp):
        buf = ctypes.create_unicode_buffer(64)
        ctypes.windll.user32.GetClassNameW(h, buf, 64)
        if buf.value == "Chrome_RenderWidgetHostHWND":
            found.append(h)
            return False
        return True

    ctypes.windll.user32.EnumChildWindows(hwnd, cb, 0)
    if not found:
        return None
    r = wt.RECT()
    ctypes.windll.user32.GetWindowRect(found[0], ctypes.byref(r))
    return [r.left, r.top, r.right, r.bottom]


def button_true_center(shot_path, bid, win_origin, near=None):
    """物理截图中按纯色扫按钮 bbox → 屏幕坐标真值中心。

    near=计算屏幕点:先把搜索圈定在其 ±150px 内,防远处同色块污染。
    行/列密度门槛:只保留像素数过半预期宽高的连续区,防细条桥接伪影。
    """
    arr = np.asarray(Image.open(shot_path).convert("RGB")).astype(int)
    c = COLORS[bid]
    mask = (np.abs(arr - np.array(c)).max(axis=2) <= 6)
    if near is not None:
        nx, ny = int(near[0] - win_origin[0]), int(near[1] - win_origin[1])
        h, w = mask.shape
        roi = np.zeros_like(mask)
        roi[max(0, ny - 150):min(h, ny + 150),
            max(0, nx - 150):min(w, nx + 150)] = True
        mask &= roi
    if mask.sum() < 200:
        return None
    row_ok = mask.sum(axis=1) > 40          # 按钮宽 ~92+px,半宽门槛
    col_ok = mask.sum(axis=0) > 15          # 按钮高 ~36+px,半高门槛
    ys, xs = np.nonzero(row_ok), np.nonzero(col_ok)
    if len(ys[0]) < 4 or len(xs[0]) < 20:
        return None
    y0, y1 = ys[0].min(), ys[0].max()
    x0, x1 = xs[0].min(), xs[0].max()
    cx = (x0 + x1) / 2 + win_origin[0]
    cy = (y0 + y1) / 2 + win_origin[1]
    return [round(cx, 2), round(cy, 2)], [int(x1 - x0 + 1), int(y1 - y0 + 1)]


class Session:
    """一个受管 Edge 实例(一种 scale 档位)内跑若干阶段。"""

    def __init__(self, scale, results, meta):
        self.scale = scale            # None=不强制,否则 --force-device-scale-factor
        self.results = results
        self.meta = meta
        self.tmp = tempfile.mkdtemp(prefix="req006-edge-")
        self.proc = None
        self.cdp = None
        self.sid = None
        self.token = None
        self.hwnd = None

    def ev(self, expr):
        r = self.cdp.call("Runtime.evaluate",
                          {"expression": expr, "returnByValue": True},
                          session_id=self.sid)
        return r.get("result", {}).get("value")

    def css_center(self, bid):
        doc = self.cdp.call("DOM.getDocument", session_id=self.sid)
        q = self.cdp.call("DOM.querySelector",
                          {"nodeId": doc["root"]["nodeId"], "selector": f"#{bid}"},
                          session_id=self.sid)
        box = self.cdp.call("DOM.getBoxModel", {"nodeId": q["nodeId"]},
                            session_id=self.sid)
        c = box["model"]["content"]
        return [(c[0] + c[2] + c[4] + c[6]) / 4, (c[1] + c[3] + c[5] + c[7]) / 4]

    def zoom_key(self, vk, code, key):
        """ctrl 组合:rawKeyDown + keyUp(keyDown 已实测不触发浏览器缩放)。"""
        for t in ("rawKeyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent",
                          {"type": t, "modifiers": 2, "key": key, "code": code,
                           "windowsVirtualKeyCode": vk,
                           "nativeVirtualKeyCode": vk}, session_id=self.sid)

    def cell(self, phase, bid):
        # 每击前重新前置(跑程中其他窗口可能被系统/用户抬升遮挡)
        dcall("activate_window", {"token": self.token})
        time.sleep(0.25)
        cre = render_widget_rect(self.hwnd)
        css = self.css_center(bid)
        dpr = self.ev("window.devicePixelRatio")
        iw = self.ev("window.innerWidth")
        pt = [cre[0] + css[0] * dpr, cre[1] + css[1] * dpr]
        prev = self.ev(f"window.__counts['{bid}']")

        cr = dcall("click", {"token": self.token, "x": round(pt[0]),
                             "y": round(pt[1])})
        if not cr.get("ok"):
            raise RuntimeError(f"click 失败: {cr}")
        time.sleep(0.4)
        count = self.ev(f"window.__counts['{bid}']")

        # CSS 侧交叉验证:getNodeForLocation 应解析回本按钮
        try:
            loc = self.cdp.call("DOM.getNodeForLocation",
                                {"x": int(css[0]), "y": int(css[1])},
                                session_id=self.sid)
            desc = self.cdp.call("DOM.describeNode",
                                 {"backendNodeId": loc["backendNodeId"]},
                                 session_id=self.sid)
            attrs = desc["node"].get("attributes", [])
            idmap = dict(zip(attrs[::2], attrs[1::2]))
            css_ok = idmap.get("id") == bid or \
                desc["node"].get("nodeName") == "BUTTON"
        except Exception as e:
            css_ok = f"err:{e}"

        # 物理真值:daemon 窗口截图(window 参数收 hwnd 不收 token)+ 色块扫描
        shot = os.path.join(SHOT_DIR, f"{phase}_{bid}.png")
        sr = dcall("screenshot", {"scope": "window", "window": self.hwnd,
                                  "path": shot})
        if not sr.get("ok"):
            raise RuntimeError(f"screenshot 失败: {sr}")
        win = dcall("find_window", {"hwnd": self.hwnd})
        wrect = (win.get("data") or {}).get("rect") or \
            (win.get("data") or {}).get("windows", [{}])[0].get("rect")
        truth = button_true_center(shot, bid, (wrect[0], wrect[1]), near=pt)
        rec = {
            "phase": phase, "button": bid,
            "dpr": dpr, "innerWidth": iw,
            "content_rect": cre,
            "css_center": [round(v, 2) for v in css],
            "computed_screen": [round(v, 2) for v in pt],
            "clicked": [round(pt[0]), round(pt[1])],
            "count_before": prev, "count_after": count,
            "hit": count == (prev or 0) + 1,
            "css_getNodeForLocation_ok": css_ok,
        }
        if truth:
            (tcx, tcy), tsize = truth
            rec["true_screen_center"] = [tcx, tcy]
            rec["true_button_size_px"] = tsize
            rec["error_px"] = [round(pt[0] - tcx, 2), round(pt[1] - tcy, 2)]
            rec["error_dist"] = round(
                ((pt[0] - tcx) ** 2 + (pt[1] - tcy) ** 2) ** 0.5, 2)
        else:
            rec["true_screen_center"] = None
        self.results.append(rec)
        print(json.dumps(rec, ensure_ascii=False))
        return rec

    def open(self, extra_args=None):
        if self.scale:
            # 强制缩放档窗口物理尺寸=DIP×scale,须缩窗贴角避免任务栏遮挡
            args = ["--window-size=900,600", "--window-position=0,0"]
        else:
            args = ["--window-size=1200,900", "--window-position=100,50"]
        if self.scale:
            args.append(f"--force-device-scale-factor={self.scale}")
        if extra_args:
            args.extend(extra_args)
        self.proc = launch_managed_edge(self.tmp, extra_args=args, url=TESTPAGE)
        port, ws_path = read_devtools_active_port(self.tmp)
        self.cdp = CDP(f"ws://127.0.0.1:{port}{ws_path}")
        targets = self.cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        self.sid = self.cdp.call(
            "Target.attachToTarget",
            {"targetId": page["targetId"], "flatten": True})["sessionId"]
        self.cdp.call("Accessibility.enable", session_id=self.sid)
        time.sleep(2.0)
        fw = dcall("find_window", {"title": "REQ005坐标穿刺"})
        self.hwnd = (fw.get("data") or {}).get("windows", [{}])[0]["hwnd"]
        self.token = (dcall("attach", {"hwnd": self.hwnd})
                      .get("data") or {})["token"]
        dcall("activate_window", {"token": self.token})
        time.sleep(0.6)
        tag = f"scale{self.scale or 'natural'}"
        self.meta[tag] = {
            "content_rect": render_widget_rect(self.hwnd),
            "inner": [self.ev("window.innerWidth"),
                      self.ev("window.innerHeight")],
            "dpr": self.ev("window.devicePixelRatio"),
        }
        print("META", tag, json.dumps(self.meta[tag], ensure_ascii=False))

    def close(self):
        if self.token:
            try:
                dcall("detach", {"token": self.token})
            except Exception:
                pass
        if self.cdp:
            self.cdp.close()
        if self.proc:
            kill_managed_edge(self.tmp, self.proc.pid)
        for _ in range(10):
            try:
                shutil.rmtree(self.tmp)
                break
            except OSError:
                time.sleep(0.8)
        self.meta[f"cleanup_scale{self.scale or 'natural'}"] = \
            not os.path.exists(self.tmp)


def scroll_to_btn(s, bid, margin=250):
    """window.scrollTo 滚到目标按钮入视野(距顶 margin css px)。"""
    doc_top = s.ev(f"document.getElementById('{bid}')"
                   ".getBoundingClientRect().top + window.scrollY")
    s.ev(f"window.scrollTo(0, {doc_top - margin})")
    time.sleep(0.4)
    return s.ev("window.scrollY")


def main():
    os.makedirs(SHOT_DIR, exist_ok=True)
    results: list = []
    meta: dict = {}

    # ---- 会话 A:自然 dpr(本机系统缩放 100% → dpr=1)----
    s = Session(None, results, meta)
    s.open()
    try:
        for b in BUTTONS_FIXED:                       # 基线 zoom100 无滚动
            s.cell("base100_dpr1", b)

        # 真 zoom 尝试:rawKeyDown ctrl+= (如实记录 dpr 是否动)
        for _ in range(3):
            s.zoom_key(187, "Equal", "=")
            time.sleep(0.5)
        meta["zoom_ctrl_equal_rawkeydown"] = {
            "dpr_after_3_presses": s.ev("window.devicePixelRatio"),
            "innerWidth_after": s.ev("window.innerWidth"),
        }
        if abs(s.ev("window.devicePixelRatio") - 1.0) > 0.01:
            for b in BUTTONS_FIXED:
                s.cell("zoom_real", b)
        # 复位 zoom(ctrl+0),否则 override 与 zoom 叠加(dpr 2.25 实测过)
        s.zoom_key(48, "Digit0", "0")
        time.sleep(0.5)
        meta["dpr_after_ctrl0"] = s.ev("window.devicePixelRatio")

        # Emulation 指标覆盖(模拟 dpr;首跑已证其不物理缩放,两钮存证即可)
        s.cdp.call("Emulation.setDeviceMetricsOverride",
                   {"width": 1176, "height": 808, "deviceScaleFactor": 1.5,
                    "mobile": False}, session_id=s.sid)
        time.sleep(0.6)
        meta["override1.5"] = {
            "dpr": s.ev("window.devicePixelRatio"),
            "inner": [s.ev("window.innerWidth"), s.ev("window.innerHeight")],
        }
        for b in ("b_tl", "b_br"):
            try:
                s.cell("override1.5_virtual", b)
            except RuntimeError as e:
                # 公式在 override 下算错点,daemon OUT_OF_BOUNDS 拦截=存证
                s.results.append({"phase": "override1.5_virtual",
                                  "button": b, "hit": False,
                                  "click_blocked": str(e)[:200]})
                print("BLOCKED", b, str(e)[:120])
        s.cdp.call("Emulation.clearDeviceMetricsOverride", session_id=s.sid)
        time.sleep(0.6)

        # 滚动:按元素文档位置算 scrollY(保证入视野),滚动量均 >800px
        for b in BUTTONS_SCROLL:
            scroll_to_btn(s, b)
            s.cell("scroll_dpr1", b)
        meta["scroll_session_a"] = s.ev("window.scrollY")
        s.cell("scroll_dpr1", "b_c")                  # fixed 按钮滚动后复测
    finally:
        s.close()

    # ---- 会话 B/C:force-device-scale-factor 真实物理缩放 ----
    for scale, phase in (("1.25", "forced1.25"), ("1.5", "forced1.5")):
        s = Session(scale, results, meta)
        s.open()
        try:
            for b in BUTTONS_FIXED:
                s.cell(phase, b)
            # 缩放档下滚动复测(s_l/s_r 不与 fixed 角钮叠位;逐钮滚动)
            for b in ("s_l", "s_r"):
                scroll_to_btn(s, b)
                s.cell(f"{phase}_scroll", b)
            s.cell(f"{phase}_scroll", "b_c")
        finally:
            s.close()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "cells": results}, f,
                  ensure_ascii=False, indent=2)
    print("SAVED", OUT_JSON, "cells:", len(results))


if __name__ == "__main__":
    main()
