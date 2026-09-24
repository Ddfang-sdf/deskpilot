# -*- coding: utf-8 -*-
"""REQ-005 侦察:硬约束 1 实测——默认 profile 带 --remote-debugging-port 的行为。

只观测端口是否监听(netstat,不发起任何 TCP/CDP 连接、不读用户 profile 数据),
观测完立即杀掉本次拉起的进程(按 PID 树,精确匹配本次命令行)。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from r05_cdp_client import EDGE_EXE, kill_tree  # noqa: E402

OUT = HERE


def find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_listening(port: int) -> bool:
    """只查 netstat 监听表,不连接。"""
    out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3] == "LISTENING":
            if parts[1].endswith(f":{port}"):
                return True
    return False


def main() -> None:
    result: dict = {}
    # 先记录当前是否已有日常 Edge 进程在跑(影响「新进程是否只是移交既有实例」)
    pre = subprocess.run(["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/FO", "CSV"],
                         capture_output=True, text=True).stdout
    pre_count = max(0, pre.count("msedge.exe"))
    result["preexisting_msedge_processes"] = pre_count

    port = find_free_port()
    result["debug_port"] = port
    proc = subprocess.Popen(
        [EDGE_EXE, f"--remote-debugging-port={port}",
         "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result["spawned_pid"] = proc.pid
    try:
        time.sleep(6)  # 给足启动/移交时间
        proc.poll()
        result["spawned_process_alive"] = proc.returncode is None
        result["spawned_returncode"] = proc.returncode
        result["port_listening"] = port_listening(port)
        # 复查一次(防启动慢)
        if not result["port_listening"]:
            time.sleep(4)
            result["port_listening_recheck"] = port_listening(port)
    finally:
        kill_tree(proc.pid)
        time.sleep(1.5)
        result["killed"] = True
        result["port_listening_after_kill"] = port_listening(port)

    with open(os.path.join(OUT, "constraint1-default-profile.json"), "w",
              encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
