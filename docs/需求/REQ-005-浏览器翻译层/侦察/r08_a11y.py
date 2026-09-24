# -*- coding: utf-8 -*-
"""REQ-005 三轮 v2:a11y 开启机制实测(A=SPI / B=注册表策略 / D=flag 复核)。

v2 修正(首跑两大测量坑):
- daemon get_ui_tree 深度帽=10,网页内容根(Chrome Legacy Window)恰在 depth 10,
  内容子节点永不可见 → 内容观测改对 **render widget hwnd** 调 get_ui_tree
  (根即内容文档,深度从 0 起算);
- 窗口/render widget 查找加启动竞态重试。
纪律:SPI 与注册表先读原值、测完还原,json 附还原证据;临时 profile 零残留。
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
import winreg

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from r05_cdp_client import (CDP, launch_managed_edge, read_devtools_active_port,
                            kill_managed_edge)  # noqa: E402
from r06_mapping_spike import dcall  # noqa: E402

SPI_GETSCREENREADER = 0x0046
SPI_SETSCREENREADER = 0x0047
SPIF_SENDCHANGE = 0x02
URL = "https://www.baidu.com"
POLICY_PATH = r"Software\Policies\Microsoft\Edge"
POLICY_NAME = "RendererAccessibilityEnabled"


def spi_get():
    v = wt.BOOL(0)
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETSCREENREADER, 0,
                                               ctypes.byref(v), 0)
    return bool(v.value)


def spi_set(on: bool):
    return bool(ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETSCREENREADER, on, None, SPIF_SENDCHANGE))


def render_widget_hwnd(main_hwnd, tries=20):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, lp):
        buf = ctypes.create_unicode_buffer(64)
        ctypes.windll.user32.GetClassNameW(h, buf, 64)
        if buf.value == "Chrome_RenderWidgetHostHWND":
            found.append(h)
            return False
        return True

    for _ in range(tries):
        found.clear()
        ctypes.windll.user32.EnumChildWindows(main_hwnd, cb, 0)
        if found:
            r = wt.RECT()
            ctypes.windll.user32.GetWindowRect(found[0], ctypes.byref(r))
            return found[0], [r.left, r.top, r.right, r.bottom]
        time.sleep(0.5)
    return None, None


def count_top_windows():
    n = [0]

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, lp):
        if ctypes.windll.user32.IsWindowVisible(h):
            n[0] += 1
        return True

    ctypes.windll.user32.EnumWindows(cb, 0)
    return n[0]


class Inst:
    def __init__(self, extra_flags=None):
        self.tmp = tempfile.mkdtemp(prefix="req008-edge-")
        flags = ["--window-size=1280,900", "--window-position=60,40",
                 "--lang=zh-CN", "--accept-lang=zh-CN"]
        if extra_flags:
            flags += extra_flags
        self.proc = launch_managed_edge(self.tmp, extra_args=flags, url=URL)
        self.cdp = self.sid = self.token = self.hwnd = None
        self.rw_hwnd = self.rw_rect = None

    def open(self):
        port, ws = read_devtools_active_port(self.tmp)
        self.cdp = CDP(f"ws://127.0.0.1:{port}{ws}", timeout=40)
        targets = self.cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        self.sid = self.cdp.call(
            "Target.attachToTarget",
            {"targetId": page["targetId"], "flatten": True})["sessionId"]
        self.cdp.call("Accessibility.enable", session_id=self.sid)
        for _ in range(30):
            fw = dcall("find_window", {"process": "msedge.exe"})
            wins = [w for w in (fw.get("data") or {}).get("windows", [])
                    if w.get("rect") and abs(w["rect"][0] - 60) < 25
                    and abs(w["rect"][1] - 40) < 25]
            if wins:
                self.hwnd = wins[0]["hwnd"]
                break
            time.sleep(0.5)
        self.rw_hwnd, self.rw_rect = render_widget_hwnd(self.hwnd)
        self.token = (dcall("attach", {"hwnd": self.hwnd}).get("data")
                      or {})["token"]
        time.sleep(3)

    def ev(self, expr):
        return self.cdp.call("Runtime.evaluate",
                             {"expression": expr, "returnByValue": True},
                             session_id=self.sid).get("result", {}).get("value")

    def uia_survey(self):
        """内容观测:对 render widget hwnd 调 get_ui_tree;附主窗壳计数。"""
        out = {}
        if self.rw_hwnd:
            tree = dcall("get_ui_tree", {"window": self.rw_hwnd})
            data = tree.get("data") or {}
            els = data.get("elements") or []
            types: dict[str, int] = {}
            for e in els:
                t = e.get("control_type", "?")
                types[t] = types.get(t, 0) + 1
            out.update({
                "content_elements": len(els),
                "content_types": types,
                "truncated": data.get("truncated"),
                "ok": tree.get("ok"), "err": tree.get("error_code") or None,
                "sample_links": [e["name"] for e in els
                                 if e.get("control_type") == "HyperlinkControl"
                                 and e.get("name")][:10],
                "sample_buttons": [e["name"] for e in els
                                   if e.get("control_type") == "ButtonControl"
                                   and e.get("name")][:6],
            })
        shell = dcall("get_ui_tree", {"window": self.hwnd})
        out["shell_elements"] = len((shell.get("data") or {})
                                    .get("elements") or [])
        return out

    def ax_count(self):
        return len(self.cdp.call("Accessibility.getFullAXTree",
                                 session_id=self.sid)["nodes"])

    def rect_consistency(self, names):
        out = []
        if not self.rw_hwnd:
            return out
        els = (dcall("get_ui_tree", {"window": self.rw_hwnd}).get("data")
               or {}).get("elements") or []
        cre = self.rw_rect
        dpr = self.ev("window.devicePixelRatio")
        for nm in names:
            e = next((x for x in els
                      if x.get("control_type") == "HyperlinkControl"
                      and x.get("name") == nm and x.get("rect")), None)
            if not e:
                out.append({"name": nm, "found": False})
                continue
            self.ev(f"(()=>{{const a=[...document.querySelectorAll('a')]"
                    f".find(a=>a.textContent.trim()==='{nm}'&&a.offsetParent);"
                    f"if(!a)return false;a.setAttribute('data-dp','1');"
                    f"return true}})()")
            doc = self.cdp.call("DOM.getDocument", session_id=self.sid)
            q = self.cdp.call("DOM.querySelector",
                              {"nodeId": doc["root"]["nodeId"],
                               "selector": "[data-dp='1']"}, session_id=self.sid)
            box = self.cdp.call("DOM.getBoxModel", {"nodeId": q["nodeId"]},
                                session_id=self.sid)
            c = box["model"]["content"]
            css = [(c[0] + c[2] + c[4] + c[6]) / 4,
                   (c[1] + c[3] + c[5] + c[7]) / 4]
            pt = [cre[0] + css[0] * dpr, cre[1] + css[1] * dpr]
            r = e["rect"]
            uc = [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2]
            self.ev("document.querySelector('[data-dp=\\'1\\']')"
                    ".removeAttribute('data-dp')")
            out.append({"name": nm, "uia_center": [round(v, 1) for v in uc],
                        "cdp_screen": [round(v, 1) for v in pt],
                        "err_dist": round(((pt[0] - uc[0]) ** 2
                                           + (pt[1] - uc[1]) ** 2) ** 0.5, 2)})
        return out

    def close(self):
        if self.token:
            try:
                dcall("detach", {"token": self.token})
            except Exception:
                pass
        if self.cdp:
            self.cdp.close()
        kill_managed_edge(self.tmp, self.proc.pid)
        for _ in range(10):
            try:
                shutil.rmtree(self.tmp)
                break
            except OSError:
                time.sleep(0.8)
        return not os.path.exists(self.tmp)


def phase(tag, R, flags=None):
    inst = Inst(extra_flags=flags)
    inst.open()
    R[tag] = inst.uia_survey()
    R[tag]["axtree_nodes"] = inst.ax_count()
    print(tag, "content:", R[tag].get("content_elements"),
          "shell:", R[tag]["shell_elements"],
          "links:", R[tag].get("sample_links", [])[:4])
    R[f"cleanup_{tag}"] = inst.close()
    return R[tag]


def main():
    R: dict = {"spi_original": spi_get(), "policy_key_existed": False}

    phase("P0_baseline", R)

    # ---- D 复核 ----
    phase("D_force_flag", R, flags=["--force-renderer-accessibility"])

    # ---- B 注册表策略 ----
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, POLICY_PATH,
                            0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, POLICY_NAME)
            R["policy_key_existed"] = True
    except OSError:
        pass
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, POLICY_PATH)
    winreg.SetValueEx(k, POLICY_NAME, 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(k)
    try:
        phase("B_policy_on", R)
    finally:
        try:
            kk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, POLICY_PATH, 0,
                                winreg.KEY_SET_VALUE)
            winreg.DeleteValue(kk, POLICY_NAME)
            winreg.CloseKey(kk)
        except OSError:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, POLICY_PATH)
        except OSError:
            pass
    R["policy_restored_absent"] = not R["policy_key_existed"]
    phase("B_policy_off_recheck", R)

    # ---- A SPI_SETSCREENREADER(对运行中实例)----
    inst = Inst()
    inst.open()
    R["A_before"] = inst.uia_survey()
    R["windows_before_spi"] = count_top_windows()
    R["spi_set_ok"] = spi_set(True)
    polls = {}
    t = 0
    for wait in (0, 2, 5, 10):
        time.sleep(wait - t)
        t = wait
        s = inst.uia_survey()
        polls[f"t{wait}s"] = s.get("content_elements")
        print(f"A t+{wait}s content:", s.get("content_elements"))
    R["A_polls"] = polls
    R["A_after"] = inst.uia_survey()
    print("A after links:", R["A_after"].get("sample_links", [])[:6])
    R["windows_during_spi"] = count_top_windows()
    R["A_rect_consistency"] = inst.rect_consistency(["地图", "图片", "网盘"])
    print("rect:", json.dumps(R["A_rect_consistency"], ensure_ascii=False))
    # 用完即关:还原后树是否回落
    spi_set(R["spi_original"])
    R["spi_restored_value"] = spi_get()
    off = {}
    t = 0
    for wait in (0, 3, 8):
        time.sleep(wait - t)
        t = wait
        s = inst.uia_survey()
        off[f"t{wait}s"] = s.get("content_elements")
        print(f"A-off t+{wait}s content:", s.get("content_elements"))
    R["A_off_polls"] = off
    R["cleanup_A"] = inst.close()

    R["spi_final"] = spi_get()
    with open(os.path.join(HERE, "r08_a11y.json"), "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)
    print("SAVED; spi_final:", R["spi_final"],
          "policy_absent:", R["policy_restored_absent"])


if __name__ == "__main__":
    main()
