# -*- coding: utf-8 -*-
"""REQ-005 二轮·阶段 B:真实站坐标命中穿刺 + UIA/AXTree 双通道 + OCR 兜底。

v2 修正:
- get_ui_tree 的 window 参数收 hwnd(不收 token,此前误传导致假 0);
- 命中判定三通道:①页面内捕获监听器记录 e.target.closest('[data-dp]')
  (物理点击是否落在目标元素);②activeElement/href/panel 状态探针;
  ③导航类判定=location 变化 或 Target.getTargets 新增页(target=_blank),
  新页用后即 Target.closeTarget;
- getBoxModel 失败回退 getBoundingClientRect(同为 viewport CSS)。
纪律:不登录、不提交表单;物理点击全走 daemon 强制层。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from r05_cdp_client import (CDP, launch_managed_edge, read_devtools_active_port,
                            kill_managed_edge)  # noqa: E402
from r06_mapping_spike import dcall, render_widget_rect  # noqa: E402

SHOT_DIR = r"C:\code\workspace\deskpilot\dist\audit\req007_shots"

CLICK_HOOK = (
    "window.__clicks=[];"
    "document.addEventListener('click',e=>{"
    "window.__clicks.push({x:e.clientX,y:e.clientY,"
    "tag:e.target.tagName,"
    "hitMark:!!e.target.closest('[data-dp]'),"
    "trusted:e.isTrusted});"
    "if(window.__clicks.length>10)window.__clicks.shift()},true)")

BAIDU = {
    "url": "https://www.baidu.com",
    "cells": [
        {"name": "search_input(可见输入框)",
         "js": "document.getElementById('chat-textarea')||document.getElementById('kw')",
         "probe": "document.activeElement.id", "expect": "mark"},
        {"name": "hotlist_换一换(图标+文字链接)",
         "js": "[...document.querySelectorAll('a,span')].find(a=>a.textContent.trim().includes('换一换')&&a.offsetParent)",
         "probe": "(()=>{const e=document.querySelector('#hotsearch-content-wrapper li a, .hot-list li a');return e?e.textContent.slice(0,20):'absent'})()",
         "expect": "record"},
        {"name": "nav_图片_link",
         "js": "[...document.querySelectorAll('a')].find(a=>a.textContent.trim()==='图片'&&a.offsetParent)",
         "probe": "location.href", "expect": "nav"},
        {"name": "nav_地图_link",
         "js": "[...document.querySelectorAll('a')].find(a=>a.textContent.trim()==='地图'&&a.offsetParent)",
         "probe": "location.href", "expect": "nav"},
        {"name": "nav_网盘_link",
         "js": "[...document.querySelectorAll('a')].find(a=>a.textContent.trim()==='网盘'&&a.offsetParent)",
         "probe": "location.href", "expect": "nav"},
    ],
}

BING = {
    "url": "https://cn.bing.com",
    "cells": [
        {"name": "hamburger_#id_sc_设置和快速链接(无文字图标)",
         "js": "document.getElementById('id_sc')",
         "probe": "document.getElementById('id_sc').getAttribute('aria-expanded')",
         "expect": "mark_change"},
        {"name": "searchbox_#sb_form_q",
         "js": "document.getElementById('sb_form_q')",
         "probe": "document.activeElement.id", "expect": "sb_form_q"},
        {"name": "menuitem_图片",
         "js": "[...document.querySelectorAll('a')].find(a=>a.textContent.trim()==='图片'&&a.offsetParent)",
         "probe": "location.href", "expect": "nav"},
        {"name": "menuitem_视频",
         "js": "[...document.querySelectorAll('a')].find(a=>a.textContent.trim()==='视频'&&a.offsetParent)",
         "probe": "location.href", "expect": "nav"},
        {"name": "logo_#bLogo(图片链接)",
         "js": "document.querySelector('#bLogo')",
         "probe": "location.href", "expect": "mark"},
    ],
}


class Real:
    def __init__(self, extra_flags=None, exe=None):
        self.tmp = tempfile.mkdtemp(prefix="req007-edge-")
        flags = ["--window-size=1280,900", "--window-position=60,40",
                 "--lang=zh-CN", "--accept-lang=zh-CN"]
        if extra_flags:
            flags += extra_flags
        if exe:
            import r05_cdp_client
            r05_cdp_client.EDGE_EXE = exe
        self.proc = launch_managed_edge(self.tmp, extra_args=flags,
                                        url="about:blank")
        self.cdp = self.sid = self.token = self.hwnd = None
        self.results = []
        self.uia = {}

    def open(self):
        port, ws = read_devtools_active_port(self.tmp)
        self.cdp = CDP(f"ws://127.0.0.1:{port}{ws}", timeout=40)
        targets = self.cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        self.sid = self.cdp.call(
            "Target.attachToTarget",
            {"targetId": page["targetId"], "flatten": True})["sessionId"]
        self.cdp.call("Accessibility.enable", session_id=self.sid)
        self.cdp.call("Page.enable", session_id=self.sid)
        time.sleep(1.5)

    def ev(self, expr):
        return self.cdp.call("Runtime.evaluate",
                             {"expression": expr, "returnByValue": True},
                             session_id=self.sid).get("result", {}).get("value")

    def page_targets(self):
        return [t for t in self.cdp.call("Target.getTargets")["targetInfos"]
                if t["type"] == "page"]

    def goto(self, url):
        self.cdp.call("Page.navigate", {"url": url}, session_id=self.sid)
        waited = 0.0
        while waited < 25:
            try:
                if self.ev("document.readyState") == "complete":
                    break
            except Exception:
                pass
            time.sleep(0.5)
            waited += 0.5
        time.sleep(2.5)
        self.ev(CLICK_HOOK)
        return waited

    def attach_daemon(self):
        fw = dcall("find_window", {"process": "msedge.exe"})
        wins = (fw.get("data") or {}).get("windows", [])
        win = next((w for w in wins if w.get("rect")
                    and abs(w["rect"][0] - 60) < 25
                    and abs(w["rect"][1] - 40) < 25), None)
        if not win:
            raise RuntimeError(f"受管窗口未定位: {wins}")
        self.hwnd = win["hwnd"]
        self.token = (dcall("attach", {"hwnd": self.hwnd}).get("data")
                      or {})["token"]
        dcall("activate_window", {"token": self.token})
        time.sleep(0.5)

    def css_center_of_marked(self):
        doc = self.cdp.call("DOM.getDocument", session_id=self.sid)
        q = self.cdp.call("DOM.querySelector",
                          {"nodeId": doc["root"]["nodeId"],
                           "selector": "[data-dp='1']"}, session_id=self.sid)
        try:
            box = self.cdp.call("DOM.getBoxModel", {"nodeId": q["nodeId"]},
                                session_id=self.sid)
            c = box["model"]["content"]
            return [(c[0] + c[2] + c[4] + c[6]) / 4,
                    (c[1] + c[3] + c[5] + c[7]) / 4], "getBoxModel"
        except Exception:
            r = self.ev("(()=>{const el=document.querySelector('[data-dp=\\'1\\']');"
                        "const r=el.getBoundingClientRect();"
                        "return {left:r.left,top:r.top,"
                        "width:r.width,height:r.height}})()")
            return [r["left"] + r["width"] / 2,
                    r["top"] + r["height"] / 2], "getBoundingClientRect"

    def cell(self, site, cfg):
        rec = {"site": site, "element": cfg["name"]}
        try:
            dcall("activate_window", {"token": self.token})
            time.sleep(0.3)
            ok = self.ev(f"(()=>{{const e=({cfg['js']});if(!e)return false;"
                         f"e.setAttribute('data-dp','1');return true}})()")
            if not ok:
                rec.update(hit=False, note="element not found")
                self.results.append(rec)
                print("NF", json.dumps(rec, ensure_ascii=False))
                return rec
            css, how = self.css_center_of_marked()
            top_el = self.ev(f"(()=>{{const e=document.elementFromPoint("
                             f"{css[0]},{css[1]});return e?e.tagName+'#'+e.id"
                             f"+' inMark:'+!!e.closest('[data-dp]'):'none'}})()")
            rec["elementFromPoint_before"] = top_el
            dpr = self.ev("window.devicePixelRatio")
            cre = render_widget_rect(self.hwnd)
            pt = [cre[0] + css[0] * dpr, cre[1] + css[1] * dpr]
            before = self.ev(cfg["probe"])
            url_before = self.ev("location.href")
            ids_before = {t["targetId"] for t in self.page_targets()}
            cr = dcall("click", {"token": self.token, "x": round(pt[0]),
                                 "y": round(pt[1])})
            rec.update(css_center=[round(v, 1) for v in css], coords_via=how,
                       computed=[round(v, 1) for v in pt],
                       clicked=[round(pt[0]), round(pt[1])], dpr=dpr,
                       probe_before=before)
            if not cr.get("ok"):
                rec.update(hit=False,
                           note=f"click blocked: {cr.get('error_code')}")
                self.results.append(rec)
                print("BLK", json.dumps(rec, ensure_ascii=False))
                return rec
            time.sleep(1.5)
            targets_after = self.page_targets()
            new_ids = [t["targetId"] for t in targets_after
                       if t["targetId"] not in ids_before]
            new_tab = len(new_ids) > 0
            after = self.ev(cfg["probe"]) if not new_tab else "(new tab)"
            url_after = self.ev("location.href") if not new_tab else "(new tab)"
            clicks = self.ev("window.__clicks") if not new_tab else None
            mark_hit = bool(clicks and clicks[-1].get("hitMark"))
            rec.update(probe_after=after, click_event=clicks[-1] if clicks
                       else None, mark_hit=mark_hit, new_tab=new_tab)
            exp = cfg["expect"]
            if exp == "nav":
                rec["hit"] = (url_after != url_before) or new_tab
                rec["url_after"] = url_after
            elif exp == "change":
                rec["hit"] = after != before
            elif exp == "mark_change":
                rec["hit"] = mark_hit and after != before
            elif exp == "mark":
                rec["hit"] = mark_hit
            elif exp == "record":
                rec["hit"] = mark_hit
                rec["note"] = "probe 前后值供判读(动态内容)"
            else:
                rec["hit"] = mark_hit and after == exp
            # 新标签页善后:精确关掉本次点击开出的 delta 页
            if new_tab:
                for tid in new_ids:
                    try:
                        self.cdp.call("Target.closeTarget",
                                      {"targetId": tid})
                    except Exception:
                        pass
                time.sleep(0.8)
                self.attach_daemon()
            elif url_after != url_before:
                self.goto(cfg["_home"])
                self.attach_daemon()
            self.ev("document.querySelector('[data-dp=\\'1\\']')"
                    "&&document.querySelector('[data-dp=\\'1\\']')"
                    ".removeAttribute('data-dp')")
            self.results.append(rec)
            print("CELL", json.dumps(rec, ensure_ascii=False)[:420])
            return rec
        except Exception as e:
            rec.update(hit=False, note=f"exc: {e}"[:200])
            self.results.append(rec)
            print("EXC", json.dumps(rec, ensure_ascii=False)[:300])
            return rec

    def uia_count(self, site):
        tree = dcall("get_ui_tree", {"window": self.hwnd})   # 收 hwnd 不收 token
        data = tree.get("data") or {}
        els = data.get("elements") or []
        types: dict[str, int] = {}
        for e in els:
            t = e.get("control_type", "?")
            types[t] = types.get(t, 0) + 1
        self.uia[site] = {"uia_elements": len(els),
                          "truncated": data.get("truncated"),
                          "type_counts": types,
                          "ok": tree.get("ok"),
                          "err": tree.get("error_code") or None}
        print(f"UIA[{site}]:", len(els), json.dumps(types)[:200])
        return len(els)

    def ocr_sample(self, site):
        shot = os.path.join(SHOT_DIR, f"{site}_ocr.png")
        sr = dcall("screenshot", {"scope": "window", "window": self.hwnd,
                                  "path": shot, "ocr": True})
        data = sr.get("data") or {}
        items = data.get("ocr_items") or []
        texts = [i.get("text") for i in items if isinstance(i, dict)]
        self.uia[f"{site}_ocr"] = {"ocr_items": len(items),
                                   "sample": texts[:25]}
        print(f"OCR[{site}]:", len(items),
              json.dumps(texts[:12], ensure_ascii=False))

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


def run_site(tag, site, store):
    r = Real()
    r.open()
    try:
        r.goto(site["url"])
        r.attach_daemon()
        shot = r.cdp.call("Page.captureScreenshot", {"format": "png"},
                          session_id=r.sid)
        with open(os.path.join(HERE, f"r07_{tag}.png"), "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        r.uia_count(tag)
        r.ocr_sample(tag)
        for cfg in site["cells"]:
            cfg["_home"] = site["url"]
            r.cell(tag, cfg)
        store["cells_" + tag] = r.results
        store["uia_" + tag] = r.uia
    finally:
        store[f"cleanup_{tag}"] = r.close()


def main():
    os.makedirs(SHOT_DIR, exist_ok=True)
    store: dict = {}
    run_site("baidu", BAIDU, store)
    run_site("bing", BING, store)

    # UIA 对照:加 --force-renderer-accessibility 重测(量化 UIA 通道上限)
    r = Real(extra_flags=["--force-renderer-accessibility"])
    r.open()
    try:
        r.goto(BAIDU["url"])
        r.attach_daemon()
        store["uia_baidu_forced_ax"] = r.uia_count("baidu_forced_ax")
        r.goto(BING["url"])
        r.attach_daemon()
        store["uia_bing_forced_ax"] = r.uia_count("bing_forced_ax")
    finally:
        store["cleanup_forced"] = r.close()

    with open(os.path.join(HERE, "r07_realsite.json"), "w",
                  encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    print("SAVED r07_realsite.json")


if __name__ == "__main__":
    main()
