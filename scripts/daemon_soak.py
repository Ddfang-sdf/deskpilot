"""DeskPilot 常驻服务长驻巡检脚本（ISS-0009 方案 F）。

用途：验证 daemon 长驻稳定性（临时目录/内存/响应无劣化）。
每小时探测一次 /health、/version 与一次 L0 调用，结果追加到 soak-report.jsonl。
默认运行 72 小时；Ctrl+C 结束。退出码：0=全程无失败，1=存在失败记录。

用法：
  python scripts/daemon_soak.py [--hours 72] [--interval 3600] [--url http://127.0.0.1:9420]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT = REPO_ROOT / "soak-report.jsonl"


def probe(url: str, path: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(f"{url}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=72.0)
    ap.add_argument("--interval", type=float, default=3600.0)
    ap.add_argument("--url", default="http://127.0.0.1:9420")
    args = ap.parse_args()

    deadline = time.monotonic() + args.hours * 3600
    failures = 0
    rounds = 0
    print(f"soak: 目标 {args.url},每 {args.interval}s 一轮,共 {args.hours}h")
    while time.monotonic() < deadline:
        rounds += 1
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "round": rounds}
        try:
            rec["health"] = probe(args.url, "/health")
            rec["version"] = probe(args.url, "/version")
            req = urllib.request.Request(
                f"{args.url}/call",
                data=json.dumps({"tool": "get_cursor", "params": {}}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                rec["call_ok"] = json.loads(resp.read().decode("utf-8")).get("ok")
        except Exception as e:
            rec["error"] = str(e)
            failures += 1
        with REPORT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{rec['ts']}] round {rounds}: {'FAIL ' + rec.get('error', '') if 'error' in rec else 'ok'}")
        time.sleep(args.interval)
    print(f"soak 结束: {rounds} 轮, {failures} 失败 → 报告 {REPORT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
