# -*- coding: utf-8 -*-
"""REQ-005 三轮·补测:C=edge://accessibility 开关机制 + B=策略键复核(edge://policy 验证)。

C: 开 native 勾选 → render widget UIA 内容观测 → profile Preferences diff 找落点。
B: 写 RendererAccessibilityEnabled=1 → edge://policy 看是否被识别/生效。
"""
from __future__ import annotations

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
from r08_a11y import render_widget_hwnd  # noqa: E402

POLICY_PATH = r"Software\Policies\Microsoft\Edge"
POLICY_NAME = "RendererAccessibilityEnabled"


class Inst:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="req008c-")
        self.proc = launch_managed_edge(self.tmp, extra_args=[
            "--window-size=1280,900", "--window-position=60,40",
            "--lang=zh-CN"], url="about:blank")
        self.cdp = self.sid = self.hwnd = None
        self.rw_hwnd = self.rw_rect = None

    def open(self):
        port, ws = read_devtools_active_port(self.tmp)
        self.cdp = CDP(f"ws://127.0.0.1:{port}{ws}", timeout=40)
        targets = self.cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        self.sid = self.cdp.call(
            "Target.attachToTarget",
            {"targetId": page["targetId"], "flatten": True})["sessionId"]
        time.sleep(2)

    def attach_page(self, url_sub):
        """切到 url 含 url_sub 的 page target。"""
        targets = self.cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"]
                    if t["type"] == "page" and url_sub in t["url"])
        self.sid = self.cdp.call(
            "Target.attachToTarget",
            {"targetId": page["targetId"], "flatten": True})["sessionId"]
        return page["url"]

    def new_tab(self, url):
        t = self.cdp.call("Target.createTarget", {"url": url})
        time.sleep(2.5)
        return t["targetId"]

    def ev(self, expr):
        return self.cdp.call("Runtime.evaluate",
                             {"expression": expr, "returnByValue": True},
                             session_id=self.sid).get("result", {}).get("value")

    def bind_window(self):
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

    def content_count(self):
        if not self.rw_hwnd:
            self.bind_window()
        tree = dcall("get_ui_tree", {"window": self.rw_hwnd})
        return len((tree.get("data") or {}).get("elements") or [])

    def prefs_accessibility(self):
        """profile 内 accessibility 相关键(Preferences + Local State)。"""
        out = {}
        for fn, tag in ((os.path.join("Default", "Preferences"), "prefs"),
                        ("Local State", "local_state")):
            p = os.path.join(self.tmp, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)

                def walk(d, path=""):
                    hits = {}
                    if isinstance(d, dict):
                        for k, v in d.items():
                            np = f"{path}.{k}" if path else k
                            if "accessib" in k.lower() or "a11y" in k.lower():
                                hits[np] = v
                            hits.update(walk(v, np))
                    return hits

                out[tag] = walk(data)
            except OSError:
                out[tag] = "absent"
        return out

    def close(self):
        if self.cdp:
            self.cdp.close()
        kill_managed_edge(self.tmp, self.proc.pid)
        time.sleep(2)
        return self.tmp

    def rmtmp(self):
        for _ in range(10):
            try:
                shutil.rmtree(self.tmp)
                break
            except OSError:
                time.sleep(0.8)
        return not os.path.exists(self.tmp)


def main():
    R: dict = {}

    # ---- C: edge://accessibility native 勾选 ----
    inst = Inst()
    inst.open()
    inst.new_tab("https://www.baidu.com")
    inst.bind_window()
    R["C_before"] = inst.content_count()
    R["C_prefs_before"] = inst.prefs_accessibility()
    inst.new_tab("edge://accessibility")
    inst.attach_page("edge://accessibility")
    R["C_toggle"] = inst.ev(
        "(()=>{const c=document.getElementById('native');"
        "if(!c)return 'no-checkbox';c.click();return c.checked})()")
    time.sleep(2)
    inst.attach_page("baidu")
    R["C_after_native_on"] = inst.content_count()
    R["C_prefs_after"] = inst.prefs_accessibility()
    print("C:", R["C_before"], "→", R["C_after_native_on"],
          "toggle:", R["C_toggle"])
    print("C prefs diff keys:",
          json.dumps(R["C_prefs_after"], ensure_ascii=False)[:300])
    inst.close()
    R["cleanup_C"] = inst.rmtmp()

    # ---- B 复核:edge://policy 是否识别该策略 ----
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, POLICY_PATH)
    winreg.SetValueEx(k, POLICY_NAME, 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(k)
    try:
        inst = Inst()
        inst.open()
        inst.attach_page("about:blank")
        inst.new_tab("edge://policy")
        inst.attach_page("edge://policy")
        time.sleep(2)
        body = inst.ev("document.body.innerText") or ""
        R["B_policy_page_mentions"] = POLICY_NAME in body
        idx = body.find(POLICY_NAME)
        R["B_policy_page_context"] = body[max(0, idx - 80):idx + 200] \
            if idx >= 0 else body[:200]
        inst.new_tab("https://www.baidu.com")
        inst.bind_window()
        R["B_content_recheck"] = inst.content_count()
        print("B policy page mentions:", R["B_policy_page_mentions"],
              "content:", R["B_content_recheck"])
        print("ctx:", R["B_policy_page_context"][:200])
        inst.close()
        R["cleanup_B"] = inst.rmtmp()
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
    R["policy_absent_final"] = True

    with open(os.path.join(HERE, "r08_bc_check.json"), "w",
              encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)
    print("SAVED r08_bc_check.json")


if __name__ == "__main__":
    main()
