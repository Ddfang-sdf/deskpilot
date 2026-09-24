# -*- coding: utf-8 -*-
"""REQ-005 侦察:最小 CDP 客户端(websocket-client + JSON,零框架)。

复用于 r05_recon.py / r05_constraint1.py。
仅依赖 websocket-client(侦察专用,已获批准装入 venv)。
"""
from __future__ import annotations

import json
import os
import subprocess
import time

import websocket

EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def launch_managed_edge(user_data_dir: str, extra_args: list[str] | None = None,
                        url: str = "about:blank") -> subprocess.Popen:
    """以独立临时 user-data-dir 拉起受管 Edge,调试端口由系统分配(=0)。"""
    args = [
        EDGE_EXE,
        f"--user-data-dir={user_data_dir}",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-features=msEdgeSidebarV2",
    ]
    if extra_args:
        args.extend(extra_args)
    args.append(url)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_devtools_active_port(user_data_dir: str, timeout: float = 15.0) -> tuple[int, str]:
    """读受管实例 profile 下的 DevToolsActivePort 文件,返回 (port, ws_path)。"""
    path = os.path.join(user_data_dir, "DevToolsActivePort")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(path, "r", encoding="ascii") as f:
                lines = f.read().splitlines()
            if len(lines) >= 2:
                return int(lines[0]), lines[1]
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"DevToolsActivePort 未出现: {path}")


class CDPError(RuntimeError):
    pass


class CDP:
    """极简 CDP over WebSocket 客户端:同步 JSON-RPC,支持 flatten session。"""

    def __init__(self, ws_url: str, timeout: float = 20.0):
        # 坑:Chromium 111+ 拒绝带 Origin 头的 ws 握手,必须 suppress_origin
        self.ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self._next_id = 0

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None) -> dict:
        self._next_id += 1
        msg: dict = {"id": self._next_id, "method": method}
        if params:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        while True:
            resp = json.loads(self.ws.recv())
            if resp.get("id") == self._next_id:
                if "error" in resp:
                    raise CDPError(f"{method}: {resp['error']}")
                return resp.get("result", {})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def kill_tree(pid: int) -> None:
    """Windows:整棵进程树杀掉受管实例。"""
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_managed_edge(user_data_dir: str, launcher_pid: int) -> None:
    """杀受管实例全树。

    坑:Popen 拿到的 launcher PID 只是壳——真正 browser 进程是它再拉起的
    子进程并重挂父,taskkill /T 打 launcher 不一定级联。须先 /T 再按
    user-data-dir 命令行匹配补刀。
    """
    kill_tree(launcher_pid)
    time.sleep(0.8)
    ps = (
        "Get-CimInstance Win32_Process -Filter "
        "\"Name='msedge.exe' or Name='chrome.exe'\" "
        f"| Where-Object {{ $_.CommandLine -like '*{user_data_dir}*' }} "
        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
