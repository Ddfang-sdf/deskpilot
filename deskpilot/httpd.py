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
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

from . import errors
from .models import TOOL_TIME_BUDGETS

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9420
VERSION_FILE = "daemon.version"          # ISS-0009 §6：daemon 版本号文件


def check_daemon_version(host: str, port: int, expected: str,
                         timeout: float = 0.3) -> bool:
    """ISS-0009 §6：探测 daemon /version 并与期望版本比对；探测失败按不匹配。"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/version",
                                    timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return False
    return body.get("version") == expected


class HttpDaemon:
    """常驻服务：start 后于后台线程服务 HTTP，持有共享 ctx。"""

    def __init__(self, ctx, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 estop=None, idle_timeout_s: float = 0.0, whitelist_admin=None):
        self._ctx = ctx
        self._estop = estop            # 急停复位端点用（ISS-0002，段3 接线）
        self._whitelist_admin = whitelist_admin   # 白名单管理端点用（ISS-0012 E2）
        self._host = host
        self._port = port
        self._idle_timeout_s = idle_timeout_s   # ISS-0008 §6：>0 启用 idle 自停
        self._last_activity = time.monotonic()
        self.idle_stopped = False               # ISS-0008 §6 测试观测口
        self._httpd = None
        self._thread = None
        self.port = port          # start() 后更新为实际绑定端口（port=0 时为临时端口）

    @property
    def last_activity(self) -> float:
        """最近一次活动（/call 或急停动作）的时钟读数（ISS-0008 §6 观测口）。"""
        return self._last_activity

    def start(self) -> None:
        from http.server import ThreadingHTTPServer

        from .tools import call_tool

        self._write_lock = threading.Lock()       # ISS-0008 P1：写路径互斥
        self._inflight_writes = 0                 # ISS-0008 P8：写中计数（豁免用）
        handler_cls = self._make_handler()
        try:
            self._httpd = ThreadingHTTPServer((self._host, self._port),
                                              handler_cls)
        except OSError as e:
            raise RuntimeError(
                f"常驻服务端口 {self._host}:{self._port} 已被占用"
                f"（已有 daemon 在线？）: {e}") from e
        self.port = self._httpd.server_address[1]
        self._write_version_file()                # ISS-0009 H：版本握手文件
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()
        if self._idle_timeout_s > 0:              # ISS-0008 P8：idle 自停看门狗
            threading.Thread(target=self._idle_watchdog, daemon=True).start()

    def _write_version_file(self) -> None:
        """ISS-0009 H：在审计目录写 daemon.version（版本握手）。"""
        import deskpilot
        try:
            audit_dir = getattr(getattr(self._ctx, "policy", None),
                                "audit_dir", None)
            if audit_dir:
                from pathlib import Path
                Path(audit_dir).mkdir(parents=True, exist_ok=True)
                (Path(audit_dir) / VERSION_FILE).write_text(
                    json.dumps({"version": deskpilot.__version__}),
                    encoding="utf-8")
        except OSError:
            pass                                  # 握手文件失败不阻断启动

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # ---- idle 自停（ISS-0008 P8） ----

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    # ---- 预算执行与异常兜底（ISS-0009 §6 B/C） ----

    _BUDGET_EXCEEDED = object()

    def _call_with_budget(self, tool: str, raw: dict):
        """按级别预算执行一次工具调用（ISS-0009 §6 B）。

        超预算返回 _BUDGET_EXCEEDED（写路径持锁串行语义不变）；
        执行体异常原样上抛，由 handler 兜底为 500 结构化错误。
        """
        from .models import TOOL_LEVELS
        from .tools import call_tool

        level = TOOL_LEVELS.get(tool)
        if level == "L3":
            policy = getattr(self._ctx, "policy", None)
            budget = (policy.approval_ttl + 5.0) if policy else 65.0
        else:
            budget = TOOL_TIME_BUDGETS.get(level, TOOL_TIME_BUDGETS["L2"])

        def invoke():
            if level == "L0":
                return call_tool(self._ctx, tool, raw)   # 只读路径不入写锁
            self._inflight_writes += 1
            try:
                with self._write_lock:                   # 写路径严格串行
                    return call_tool(self._ctx, tool, raw)
            finally:
                self._inflight_writes -= 1

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(invoke)
            try:
                return future.result(timeout=budget)
            except FuturesTimeoutError:
                return self._BUDGET_EXCEEDED
        finally:
            pool.shutdown(wait=False)

    def _idle_exempt(self) -> bool:
        """人类仍在使用语义：冻结中 / 写调用在途（含同步审批）/ 有效绑定。"""
        if self._estop is not None and self._estop.is_frozen():
            return True
        if self._inflight_writes > 0:
            return True
        bindings = getattr(self._ctx, "bindings", None)
        return bindings is not None and bindings.count() > 0

    def _idle_watchdog(self) -> None:
        while self._httpd is not None and not self.idle_stopped:
            if (time.monotonic() - self._last_activity >= self._idle_timeout_s
                    and not self._idle_exempt()):
                self.idle_stopped = True
                self.stop()
                return
            time.sleep(min(0.1, max(self._idle_timeout_s / 4, 0.05)))

    def _make_handler(self):
        from http.server import BaseHTTPRequestHandler

        from .models import TOOL_LEVELS
        daemon = self

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
                elif self.path == "/version":
                    import deskpilot
                    self._send(200, {"version": deskpilot.__version__})
                elif self.path == "/whitelist" and \
                        daemon._whitelist_admin is not None:
                    # ISS-0012 E2：白名单管理窗口数据源（仅 127.0.0.1）；
                    # 附带 display/desc（daemon 内缓存解析，管理窗口零解析提速）
                    from .appnames import app_description, app_display_name
                    data = {}
                    for group, items in daemon._whitelist_admin.entries().items():
                        data[group] = [
                            {"process": p, "level": lv,
                             "display": app_display_name(p),
                             "desc": app_description(p)}
                            for p, lv in items.items()]
                    self._send(200, {"ok": True, "error_code": "",
                                     "message": "ok", "data": data})
                else:
                    self._send(404, {"ok": False, "error_code": "NOT_FOUND",
                                     "message": "端点不存在"})

            def do_POST(self):
                estop = daemon._estop
                if self.path == "/estop/reset" and estop is not None:
                    # 本地人类复位通道（详细设计 §11.8，ISS-0002）：
                    # 无论是否改变状态都返回 200 + was_frozen；审计由 estop 侧记录
                    was = estop.is_frozen()
                    estop.cli_reset()
                    daemon._touch()
                    self._send(200, {"ok": True, "error_code": "",
                                     "message": ("急停已复位" if was
                                                 else "复位请求已记录（当前未冻结）"),
                                     "data": {"was_frozen": was, "frozen": False}})
                    return
                admin = daemon._whitelist_admin
                if admin is not None and self.path in (
                        "/whitelist/remove", "/whitelist/clear_session"):
                    # ISS-0012 E2：白名单管理动作（仅 127.0.0.1；写盘由 admin 原子完成）
                    if self.path == "/whitelist/clear_session":
                        n = admin.clear_session()
                        self._send(200, {"ok": True, "error_code": "",
                                         "message": "ok", "data": {"cleared": n}})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", 0))
                        body = json.loads(self.rfile.read(length).decode("utf-8"))
                        proc = str(body.get("process", "")).strip().lower()
                    except (ValueError, UnicodeDecodeError) as e:
                        self._send(400, {"ok": False,
                                         "error_code": "INVALID_PARAMS",
                                         "message": f"请求体非法: {e}"})
                        return
                    if not proc:
                        self._send(400, {"ok": False,
                                         "error_code": "INVALID_PARAMS",
                                         "message": "缺少 process 参数"})
                        return
                    removed = admin.remove(proc)
                    self._send(200, {"ok": True, "error_code": "",
                                     "message": "ok",
                                     "data": {"removed": removed}})
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
                daemon._touch()
                try:
                    result = daemon._call_with_budget(tool, raw)
                except Exception as e:
                    # ISS-0009 §6 C：未知异常兜底 500 结构化错误，连接不断
                    self._send(500, {"ok": False,
                                     "error_code": errors.INTERNAL_ERROR,
                                     "message": f"服务内部异常: {e}",
                                     "data": None})
                    return
                if result is daemon._BUDGET_EXCEEDED:
                    # ISS-0009 §6 B：临期返回结构化"处理中"而非悬挂
                    self._send(200, {"ok": False,
                                     "error_code": errors.TOOL_TIMEOUT,
                                     "message": "处理中，请稍后重试",
                                     "data": None})
                    return
                daemon._touch()
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
