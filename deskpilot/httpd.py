"""常驻 HTTP 服务（ISS-0001 整改，详细设计 §2.1 内部 HTTP 的落地）。

基于 stdlib http.server（零新依赖）。持有唯一 ToolContext：
绑定表、审批令牌、SoM 缓存、急停状态跨调用常驻。
仅绑定 127.0.0.1（单用户本机语义）。工具调用全链路不变：
tools.call_tool → 强制层四道闸 → 审计 → 执行层。
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.request
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9420


class HttpDaemon:
    """常驻服务：start 后于后台线程服务 HTTP，持有共享 ctx。"""

    def __init__(self, ctx, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 estop=None):
        self._ctx = ctx
        self._estop = estop            # 急停复位端点用（ISS-0002，段3 接线）
        self._host = host
        self._port = port
        self._httpd = None
        self._thread = None
        self.port = port          # start() 后更新为实际绑定端口（port=0 时为临时端口）

    def start(self) -> None:
        from http.server import HTTPServer

        from .tools import call_tool

        ctx = self._ctx
        handler_cls = self._make_handler(ctx, call_tool, self._estop)
        try:
            self._httpd = HTTPServer((self._host, self._port), handler_cls)
        except OSError as e:
            raise RuntimeError(
                f"常驻服务端口 {self._host}:{self._port} 已被占用"
                f"（已有 daemon 在线？）: {e}") from e
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def _make_handler(self, ctx, call_tool, estop):
        from http.server import BaseHTTPRequestHandler

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):          # 静默访问日志
                pass

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False,
                                  default=str).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type",
                                 "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/health":
                    self._send(200, {"status": "ok"})
                else:
                    self._send(404, {"ok": False, "error_code": "NOT_FOUND",
                                     "message": "端点不存在"})

            def do_POST(self):
                if self.path == "/estop/reset" and estop is not None:
                    # 本地人类复位通道（详细设计 §11.8，ISS-0002）：
                    # 无论是否改变状态都返回 200 + was_frozen；审计由 estop 侧记录
                    was = estop.is_frozen()
                    estop.cli_reset()
                    self._send(200, {"ok": True, "error_code": "",
                                     "message": ("急停已复位" if was
                                                 else "复位请求已记录（当前未冻结）"),
                                     "data": {"was_frozen": was, "frozen": False}})
                    return
                if self.path != "/call":
                    self._send(404, {"ok": False, "error_code": "NOT_FOUND",
                                     "message": "端点不存在"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as e:
                    self._send(400, {"ok": False,
                                     "error_code": "INVALID_PARAMS",
                                     "message": f"请求体非法: {e}"})
                    return
                tool = body.get("tool")
                raw = body.get("params") or {}
                result = call_tool(ctx, tool, raw)
                self._send(200, {"ok": result.ok,
                                 "error_code": result.error_code,
                                 "message": result.message,
                                 "data": result.data})

        return Handler


def probe_daemon(host: str, port: int, timeout: float = 0.3) -> bool:
    """探测常驻服务是否在线（受控超时）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def remote_call(tool: str, raw: dict[str, Any], base_url: str,
                timeout: float = 90.0) -> dict:
    """向常驻服务发起一次工具调用，返回结构化结果字典。
    连接失败显式抛错（禁止静默成功）。
    超时默认 90s：须大于 approval_ttl——L3 同步审批阻塞人类裁决
    时长（ISS-0003 整改项 C）。"""
    payload = json.dumps({"tool": tool, "params": raw},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/call", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except OSError as e:
        raise RuntimeError(f"无法连接常驻服务 {base_url}: {e}") from e
