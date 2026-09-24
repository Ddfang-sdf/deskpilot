# -*- coding: utf-8 -*-
"""REQ-005 二轮·旁证:CDP 子集对 Chrome(非 Edge)同源适用。

受管 Chrome(独立临时 profile)拉起 → DevToolsActivePort → AXTree 百度全量,
与 Edge 路径逐行同码(仅可执行文件不同)。
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
import r05_cdp_client  # noqa: E402
from r05_cdp_client import (CDP, read_devtools_active_port,  # noqa: E402
                            kill_managed_edge)

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main():
    r05_cdp_client.EDGE_EXE = CHROME
    tmp = tempfile.mkdtemp(prefix="req007-chrome-")
    proc = r05_cdp_client.launch_managed_edge(tmp, extra_args=[
        "--window-size=1280,900", "--window-position=60,40",
        "--lang=zh-CN"], url="https://www.baidu.com")
    out = {"chrome_exe": CHROME}
    try:
        port, ws = read_devtools_active_port(tmp)
        cdp = CDP(f"ws://127.0.0.1:{port}{ws}", timeout=40)
        import urllib.request
        ver = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=10).read())
        targets = cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        sid = cdp.call("Target.attachToTarget",
                       {"targetId": page["targetId"], "flatten": True})["sessionId"]
        cdp.call("Accessibility.enable", session_id=sid)
        time.sleep(6)
        t0 = time.perf_counter()
        tree = cdp.call("Accessibility.getFullAXTree", session_id=sid)
        ms = (time.perf_counter() - t0) * 1000
        roles: dict[str, int] = {}
        for n in tree["nodes"]:
            r = (n.get("role") or {}).get("value", "?")
            roles[r] = roles.get(r, 0) + 1
        out.update({"browser": ver.get("Browser"),
                    "node_count": len(tree["nodes"]),
                    "axtree_ms": round(ms, 1), "role_counts": roles})
        # 坐标链抽查:搜索框 getBoxModel
        doc = cdp.call("DOM.getDocument", session_id=sid)
        q = cdp.call("DOM.querySelector",
                     {"nodeId": doc["root"]["nodeId"],
                      "selector": "#chat-textarea, #kw"}, session_id=sid)
        box = cdp.call("DOM.getBoxModel", {"nodeId": q["nodeId"]},
                       session_id=sid)
        c = box["model"]["content"]
        out["searchbox_css_center"] = [
            round((c[0] + c[2] + c[4] + c[6]) / 4, 1),
            round((c[1] + c[3] + c[5] + c[7]) / 4, 1)]
        cdp.close()
        print(json.dumps(out, ensure_ascii=False)[:500])
    finally:
        kill_managed_edge(tmp, proc.pid)
        for _ in range(10):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.8)
        out["cleanup"] = not os.path.exists(tmp)
    with open(os.path.join(HERE, "r07_chrome_check.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("SAVED r07_chrome_check.json cleanup:", out["cleanup"])


if __name__ == "__main__":
    main()
