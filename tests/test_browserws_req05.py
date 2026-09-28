"""REQ-005 TC-BR-22(assembly):CDP 客户端全链(替身 ws 服务端)。

层级:assembly(含替身,不授 integration 标签;SDD §3 降级命名)。
真实部件清单:deskpilot.browser.cdp.CdpClient 协议客户端本体、
websocket-client 传输层(真 RFC6455 帧/握手)、真 TCP socket。
替身清单:_FakeWsServer(预录应答的假 WebSocket 服务端——按 CDP
方法名返回固定 result,逐条记录收到的命令)。
断层面:真 Chromium 浏览器(其 Target/Accessibility/DOM 域真实行为
由集成 TC-BR-26 覆盖)。

入口(设计):CdpClient(ws_url).attach()/snapshot()/box_model(node_id)
(详设 §3.5 命令面的方法落形;拟定缝,已列上报裁决点)。
断言:假服务端命令序列直出=Target.getTargets→Target.attachToTarget→
Accessibility.enable→Accessibility.getFullAXTree→DOM.getDocument→
DOM.querySelector→DOM.getBoxModel;attach 后各命令带 sessionId(T5-02)。

P1 红态预期:CdpClient 空壳 NotImplementedError——红在客户端未实现。
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading

import pytest

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# 预录应答(按方法名;result 形态对齐 CDP 文档最小面)
_CANNED = {
    "Target.getTargets": {"targetInfos": [{"targetId": "T1",
                                           "type": "page"}]},
    "Target.attachToTarget": {"sessionId": "S1"},
    "Accessibility.enable": {},
    "Accessibility.getFullAXTree": {"nodes": [
        {"nodeId": "1", "role": {"value": "button"},
         "name": {"value": "提交"}}]},
    "DOM.getDocument": {"root": {"nodeId": 1}},
    "DOM.querySelector": {"nodeId": 2},
    "DOM.getBoxModel": {"model": {"content": [0, 0, 10, 0, 10, 10, 0, 10]}},
}


class _FakeWsServer:
    """假 WebSocket 服务端:真 RFC6455 握手/帧,预录应答,命令记录直出。

    commands=[{"id","method","sessionId"(可缺)}…](断言观测口)。"""

    def __init__(self):
        self.commands: list[dict] = []
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        try:
            socket.create_connection(("127.0.0.1", self.port),
                                     timeout=0.3).close()
        except OSError:
            pass
        self._sock.close()
        self._thread.join(timeout=2.0)

    # ---- RFC6455 最小面 ----

    def _handshake(self, conn: socket.socket):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                raise ConnectionError("握手失败")
            buf += chunk
        key = ""
        for line in buf.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        conn.sendall(
            ("HTTP/1.1 101 Switching Protocols\r\n"
             "Upgrade: websocket\r\nConnection: Upgrade\r\n"
             f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode("latin-1"))

    @staticmethod
    def _recv_exact(conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise ConnectionError("连接中断")
            data += chunk
        return data

    def _recv_frame(self, conn) -> str | None:
        h = self._recv_exact(conn, 2)
        opcode = h[0] & 0x0F
        if opcode == 0x8:                     # close
            return None
        masked = h[1] & 0x80
        ln = h[1] & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._recv_exact(conn, 2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._recv_exact(conn, 8))[0]
        mask = self._recv_exact(conn, 4) if masked else b"\x00" * 4
        payload = bytearray(self._recv_exact(conn, ln))
        for i in range(ln):
            payload[i] ^= mask[i % 4]
        return payload.decode("utf-8")

    @staticmethod
    def _send_text(conn, text: str):
        payload = text.encode("utf-8")
        ln = len(payload)
        if ln < 126:
            head = struct.pack("BB", 0x81, ln)
        elif ln < 65536:
            head = struct.pack(">BH", 0x81, 126) + struct.pack(">H", ln)
        else:
            head = struct.pack(">BQ", 0x81, 127) + struct.pack(">Q", ln)
        conn.sendall(head + payload)

    def _serve(self):
        while not self._stop.is_set():
            try:
                self._sock.settimeout(0.5)
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                try:
                    self._handshake(conn)
                    while not self._stop.is_set():
                        text = self._recv_frame(conn)
                        if text is None:
                            return
                        msg = json.loads(text)
                        self.commands.append(
                            {"id": msg.get("id"), "method": msg.get("method"),
                             "sessionId": msg.get("sessionId")})
                        reply = {"id": msg.get("id"),
                                 "result": _CANNED.get(msg.get("method"), {})}
                        self._send_text(conn, json.dumps(reply))
                except (ConnectionError, OSError, ValueError):
                    return


class TestCdpClientChainAssembly:
    """TC-BR-22(assembly,三清单见模块 docstring):CDP 客户端全链——
    attach→snapshot→box_model,命令序与 sessionId 携带直出。"""

    def test_br22_command_sequence_with_session_id(self):
        """TC-BR-22(assembly):假 ws 服务端预录应答 → 命令序列直出=
        Target.getTargets→Target.attachToTarget→Accessibility.enable→
        Accessibility.getFullAXTree→DOM.getDocument→DOM.querySelector→
        DOM.getBoxModel;attach 后各命令带 sessionId(T5-02)。
        红态:CdpClient 空壳 NotImplementedError。"""
        from deskpilot.browser.cdp import CdpClient

        server = _FakeWsServer()
        try:
            client = CdpClient(f"ws://127.0.0.1:{server.port}/devtools/T1")
            client.attach()
            client.snapshot()
            client.box_model(2)
        finally:
            server.close()

        seq = [c["method"] for c in server.commands]
        assert seq == ["Target.getTargets", "Target.attachToTarget",
                       "Accessibility.enable", "Accessibility.getFullAXTree",
                       "DOM.getDocument", "DOM.querySelector",
                       "DOM.getBoxModel"], \
            f"命令序列(假服务端记录直出): {seq}"
        post_attach = [c for c in server.commands
                       if c["method"] not in ("Target.getTargets",
                                              "Target.attachToTarget")]
        assert post_attach and all(c["sessionId"] for c in post_attach), \
            f"attach 后各命令须带 sessionId(直出): {server.commands}"
