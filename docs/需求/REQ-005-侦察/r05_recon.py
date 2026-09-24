# -*- coding: utf-8 -*-
"""REQ-005 侦察主脚本:目标 1-5 + 7(连通/AXTree/坐标链/截图/输入/性能基线)。

用法: .venv/Scripts/python.exe docs/需求/REQ-005-侦察/r05_recon.py
产物全部落盘到本目录;完事杀受管 Edge + 删临时 profile。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from r05_cdp_client import (CDP, launch_managed_edge,  # noqa: E402
                            read_devtools_active_port, kill_managed_edge)

OUT = HERE
TESTPAGE = "file:///" + os.path.join(HERE, "r05_testpage.html").replace("\\", "/")


def main() -> None:
    summary: dict = {"artifacts": []}
    tmp = tempfile.mkdtemp(prefix="req005-edge-")
    proc = None
    cdp = None
    try:
        # ---- 目标 1:连通与握手 ----
        proc = launch_managed_edge(tmp, url=TESTPAGE)
        port, ws_path = read_devtools_active_port(tmp)
        summary["devtools_active_port"] = {"port": port, "ws_path": ws_path}

        ver = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=10).read())
        summary["json_version"] = ver
        with open(os.path.join(OUT, "version.json"), "w", encoding="utf-8") as f:
            json.dump(ver, f, ensure_ascii=False, indent=2)
        summary["artifacts"].append("version.json")

        cdp = CDP(f"ws://127.0.0.1:{port}{ws_path}")
        targets = cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        attach = cdp.call("Target.attachToTarget",
                          {"targetId": page["targetId"], "flatten": True})
        sid = attach["sessionId"]
        summary["handshake"] = {
            "target_count": len(targets["targetInfos"]),
            "page_targetId": page["targetId"], "sessionId": sid,
            "page_url": page["url"],
        }

        # 等测试页加载完
        cdp.call("Runtime.enable", session_id=sid)
        for _ in range(50):
            r = cdp.call("Runtime.evaluate",
                         {"expression": "document.readyState", "returnByValue": True},
                         session_id=sid)
            if r.get("result", {}).get("value") == "complete":
                break
            time.sleep(0.2)

        # ---- 目标 2:AXTree ----
        cdp.call("Accessibility.enable", session_id=sid)
        t0 = time.perf_counter()
        tree = cdp.call("Accessibility.getFullAXTree", session_id=sid)
        t_axtree_first = (time.perf_counter() - t0) * 1000
        nodes = tree["nodes"]
        with open(os.path.join(OUT, "axtree-full.json"), "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=1)
        summary["artifacts"].append("axtree-full.json")

        interesting = {"button", "link", "textbox", "checkbox", "StaticText",
                       "heading", "LabelText", "slider", "RootWebArea", "form"}
        sample = [n for n in nodes
                  if n.get("role", {}).get("value") in interesting or not n.get("ignored")]
        sample = sample[:100]
        with open(os.path.join(OUT, "axtree-sample.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": sample}, f, ensure_ascii=False, indent=1)
        summary["artifacts"].append("axtree-sample.json")

        role_counts: dict[str, int] = {}
        for n in nodes:
            r = n.get("role", {}).get("value", "?")
            role_counts[r] = role_counts.get(r, 0) + 1
        summary["axtree"] = {
            "node_count": len(nodes),
            "first_call_ms": round(t_axtree_first, 2),
            "role_counts": role_counts,
        }
        # 摘录关键节点结构(role/name/state)
        excerpts = []
        for n in nodes:
            role = n.get("role", {}).get("value")
            if role in ("button", "textbox", "link", "checkbox", "slider"):
                excerpts.append({
                    "role": role,
                    "name": (n.get("name") or {}).get("value"),
                    "nameSources": [s.get("type") for s in (n.get("nameSources") or [])],
                    "properties": {p["name"]: p.get("value", {}).get("value")
                                   for p in (n.get("properties") or [])},
                })
        summary["axtree"]["node_excerpts"] = excerpts

        # ---- 目标 3:坐标链(getBoxModel → dispatchMouseEvent → evaluate 读回)----
        doc = cdp.call("DOM.getDocument", session_id=sid)
        q = cdp.call("DOM.querySelector",
                     {"nodeId": doc["root"]["nodeId"], "selector": "#btn"},
                     session_id=sid)
        t0 = time.perf_counter()
        box = cdp.call("DOM.getBoxModel", {"nodeId": q["nodeId"]}, session_id=sid)
        t_boxmodel_first = (time.perf_counter() - t0) * 1000
        content = box["model"]["content"]  # [x1,y1, x2,y2, x3,y3, x4,y4]
        cx = (content[0] + content[2] + content[4] + content[6]) / 4
        cy = (content[1] + content[3] + content[5] + content[7]) / 4
        for mtype in ("mousePressed", "mouseReleased"):
            cdp.call("Input.dispatchMouseEvent",
                     {"type": mtype, "x": cx, "y": cy, "button": "left",
                      "clickCount": 1}, session_id=sid)
        r = cdp.call("Runtime.evaluate",
                     {"expression": "document.getElementById('count').textContent",
                      "returnByValue": True}, session_id=sid)
        clicked = r["result"]["value"]
        summary["coord_chain"] = {
            "button_center_css_px": [round(cx, 2), round(cy, 2)],
            "boxmodel_first_call_ms": round(t_boxmodel_first, 2),
            "counter_after_click": clicked,
            "click_verified": clicked == "1",
        }

        # ---- 目标 4:截图 ----
        shot = cdp.call("Page.captureScreenshot", {"format": "png"}, session_id=sid)
        with open(os.path.join(OUT, "screenshot.png"), "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        summary["artifacts"].append("screenshot.png")

        # ---- 目标 5:输入(insertText 注入中文 → 读回)----
        cdp.call("Runtime.evaluate",
                 {"expression": "document.getElementById('name').focus()"},
                 session_id=sid)
        cdp.call("Input.insertText", {"text": "宋东方-REQ005侦察"}, session_id=sid)
        r = cdp.call("Runtime.evaluate",
                     {"expression": "document.getElementById('name').value",
                      "returnByValue": True}, session_id=sid)
        summary["insert_text"] = {
            "injected": "宋东方-REQ005侦察",
            "readback": r["result"]["value"],
            "verified": r["result"]["value"] == "宋东方-REQ005侦察",
        }

        # ---- 目标 7:性能基线 ----
        times_ax, times_box = [], []
        for _ in range(5):
            t0 = time.perf_counter()
            cdp.call("Accessibility.getFullAXTree", session_id=sid)
            times_ax.append((time.perf_counter() - t0) * 1000)
        for _ in range(10):
            t0 = time.perf_counter()
            cdp.call("DOM.getBoxModel", {"nodeId": q["nodeId"]}, session_id=sid)
            times_box.append((time.perf_counter() - t0) * 1000)
        summary["perf_baseline"] = {
            "getFullAXTree_ms_5runs": [round(t, 2) for t in times_ax],
            "getBoxModel_ms_10runs": [round(t, 2) for t in times_box],
        }
    finally:
        if cdp:
            cdp.close()
        if proc:
            kill_managed_edge(tmp, proc.pid)
        for _ in range(10):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.8)
        summary["cleanup"] = {
            "killed_pid": proc.pid if proc else None,
            "temp_profile_removed": not os.path.exists(tmp),
            "temp_profile": tmp,
        }

    with open(os.path.join(OUT, "recon-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    summary["artifacts"].append("recon-summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
