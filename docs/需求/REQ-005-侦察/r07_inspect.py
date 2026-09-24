# -*- coding: utf-8 -*-
"""REQ-005 二轮·阶段 A:真实站 AXTree 全量落盘 + 统计 + 候选元素清单 + 稳定性 diff。

站点:百度(搜索表单类)、cn.bing.com(富布局类)。受管 Edge 独立临时 profile。
"""
from __future__ import annotations

import hashlib
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

SITES = [
    ("baidu", "https://www.baidu.com"),
    ("bing", "https://cn.bing.com"),
]
INTERACTIVE = {"button", "link", "textbox", "searchbox", "checkbox", "radio",
               "combobox", "listbox", "menuitem", "tab", "slider", "switch",
               "image", "img"}


def snapshot(cdp, sid):
    t0 = time.perf_counter()
    tree = cdp.call("Accessibility.getFullAXTree", session_id=sid)
    ms = (time.perf_counter() - t0) * 1000
    return tree["nodes"], ms


def stats(nodes):
    roles: dict[str, int] = {}
    named = unnamed = 0
    for n in nodes:
        r = (n.get("role") or {}).get("value", "?")
        roles[r] = roles.get(r, 0) + 1
        if r in INTERACTIVE:
            if (n.get("name") or {}).get("value"):
                named += 1
            else:
                unnamed += 1
    return {"node_count": len(nodes), "role_counts": roles,
            "interactive_named": named, "interactive_unnamed": unnamed}


def tree_fingerprint(nodes):
    items = sorted(f"{(n.get('role') or {}).get('value','?')}|"
                   f"{(n.get('name') or {}).get('value','')}" for n in nodes)
    return items, hashlib.md5("|".join(items).encode("utf-8")).hexdigest()


def candidates(nodes, limit=40):
    """可点候选:interactive 角色 + 有 name,附 nodeId 供后续 DOM 解析。"""
    out = []
    for n in nodes:
        r = (n.get("role") or {}).get("value", "?")
        name = (n.get("name") or {}).get("value") or ""
        if r in INTERACTIVE and name.strip():
            out.append({"role": r, "name": name[:40],
                        "backendNodeId": n.get("backendNodeId")})
        if len(out) >= limit:
            break
    return out


def main():
    report: dict = {}
    tmp = tempfile.mkdtemp(prefix="req007-edge-")
    proc = launch_managed_edge(tmp, extra_args=[
        "--window-size=1280,900", "--window-position=60,40",
        "--lang=zh-CN", "--accept-lang=zh-CN"], url="about:blank")
    cdp = None
    try:
        port, ws_path = read_devtools_active_port(tmp)
        cdp = CDP(f"ws://127.0.0.1:{port}{ws_path}", timeout=40)
        targets = cdp.call("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        sid = cdp.call("Target.attachToTarget",
                       {"targetId": page["targetId"], "flatten": True})["sessionId"]
        cdp.call("Accessibility.enable", session_id=sid)
        cdp.call("Page.enable", session_id=sid)

        for tag, url in SITES:
            t0 = time.time()
            cdp.call("Page.navigate", {"url": url}, session_id=sid)
            # 等待策略:readyState complete + 2.5s 静态稳定
            waited = 0.0
            while waited < 25:
                rs = cdp.call("Runtime.evaluate",
                              {"expression": "document.readyState",
                               "returnByValue": True}, session_id=sid)
                if rs.get("result", {}).get("value") == "complete":
                    break
                time.sleep(0.5)
                waited += 0.5
            settle0 = time.time()
            time.sleep(2.5)
            nodes_a, ms_a = snapshot(cdp, sid)
            time.sleep(3.0)
            nodes_b, ms_b = snapshot(cdp, sid)

            items_a, fp_a = tree_fingerprint(nodes_a)
            items_b, fp_b = tree_fingerprint(nodes_b)
            churn = len([1 for a, b in zip(sorted(items_a), sorted(items_b))
                         ])  # 占位,下面用集合差
            set_a, set_b = set(items_a), set(items_b)
            diff = {"only_in_A": len(set_a - set_b),
                    "only_in_B": len(set_b - set_a),
                    "sample_churn": sorted(set_a ^ set_b)[:10]}

            with open(os.path.join(HERE, f"axtree-{tag}.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"nodes": nodes_b}, f, ensure_ascii=False, indent=1)

            final_url = cdp.call(
                "Runtime.evaluate", {"expression": "location.href",
                                     "returnByValue": True},
                session_id=sid)["result"]["value"]
            report[tag] = {
                "url": url, "final_url": final_url,
                "wait": {"readyState_wait_s": waited,
                         "settle_s": round(time.time() - settle0, 1)},
                "axtree_ms": [round(ms_a, 1), round(ms_b, 1)],
                "stats": stats(nodes_b),
                "stability": {"fp_equal": fp_a == fp_b, **diff},
                "candidates": candidates(nodes_b),
            }
            print(f"== {tag} ==", json.dumps(report[tag]["stats"],
                                             ensure_ascii=False))
            print("stability:", json.dumps(report[tag]["stability"],
                                           ensure_ascii=False)[:400])
            for c in report[tag]["candidates"]:
                print("  ", json.dumps(c, ensure_ascii=False))

        with open(os.path.join(HERE, "r07_inspect.json"), "w",
                  encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    finally:
        if cdp:
            cdp.close()
        kill_managed_edge(tmp, proc.pid)
        for _ in range(10):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.8)
        print("cleanup:", not os.path.exists(tmp))


if __name__ == "__main__":
    main()
