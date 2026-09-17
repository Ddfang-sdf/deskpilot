"""ISS-0089 screenshot 内联图源头等比降采样测试(TC-DS-01~06,问题单 §6)。

层级:TC-DS-01~04 单元(纯函数 _downscale_inline,断言在返回值/PIL 解码
尺寸直出);TC-DS-05/06 装配集成(真实 MCP Server request_handlers 分发
→ tools 层 → 真实 Executor mss 截屏 → 真实落盘 PNG;http 腿再经真实
HttpDaemon HTTP 收发;禁桩——截图/落盘/内联全链路真实,断言在 ImageContent
解码像素尺寸与落盘文件像素尺寸=数据层直出)。

入口(设计,单据 §6.1):mcp_server._downscale_inline 纯函数;
build_server 的 screenshot 返回路径(http/local 两 backend)。

断言出处:PNG 尺寸=PIL.Image.open(...).size 直出;f=函数返回值直出;
scale_x/scale_y/virtual_rect/path=MCP TextContent JSON 载荷 data 段直出;
落盘图=path 文件 PIL 解码直出。
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.request
from io import BytesIO

import pytest
from PIL import Image

from deskpilot.approval import ApprovalManager
from deskpilot.audit import AuditLogger
from deskpilot.binding import BindingManager
from deskpilot.enforcement import Enforcement
from deskpilot.estop import EstopMonitor
from deskpilot.executor import DesktopProbe, Executor
from deskpilot.httpd import HttpDaemon
from deskpilot.mcp_server import INLINE_MAX_PX, _downscale_inline, build_server
from deskpilot.tools import ToolContext

from .conftest import FakeApprover, FakeClock

import mcp.types as types


def _png(w: int, h: int) -> bytes:
    """造指定尺寸的实测 PNG 字节(单元层输入材料)。"""
    img = Image.new("RGB", (w, h), (10, 20, 30))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _call_tool(server, name: str, arguments: dict):
    """经 MCP Server 真实 request_handlers 分发调用(CallToolRequest 协议面)。"""
    handler = server.request_handlers[types.CallToolRequest]
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=arguments))
    res = asyncio.run(handler(req))
    return res.root.content


class TestDownscalePure:
    """TC-DS-01~04:_downscale_inline 纯函数契约(单据 §6.2)。断言直出。"""

    def test_tc_ds_01_oversize_proportional_downscale(self):
        """TC-DS-01:3840×1081(本机 fullscreen 实测形态)长边>2000 →
        等比缩到长边=2000,f=2000/3840。
        红态(P1 空壳直通):尺寸仍 (3840,1081) 且 f=1.0 → 双断言红。"""
        b = _png(3840, 1081)
        out, f = _downscale_inline(b, INLINE_MAX_PX)
        assert Image.open(BytesIO(out)).size == (2000, round(1081 * 2000 / 3840))
        assert abs(f - 2000 / 3840) < 1e-6

    def test_tc_ds_02_within_limit_passthrough(self):
        """TC-DS-02:1920×1080 长边≤2000 → 原样返回(同一对象零重编码),
        f==1.0(零损失回归;本机单屏形态)。"""
        b = _png(1920, 1080)
        out, f = _downscale_inline(b, INLINE_MAX_PX)
        assert out is b                          # 同一对象=未重编码(直出)
        assert f == 1.0

    def test_tc_ds_03_aspect_ratio_preserved(self):
        """TC-DS-03:缩放后宽高比守恒(等比=整幅内容全保留,非裁剪)。"""
        b = _png(3840, 1081)
        out, _f = _downscale_inline(b, INLINE_MAX_PX)
        w, h = Image.open(BytesIO(out)).size
        assert abs(w / h - 3840 / 1081) < 0.02

    def test_tc_ds_04_exactly_at_limit_not_scaled(self):
        """TC-DS-04:2000×1500 长边恰=阈值 → 不缩(> 才缩,== 不缩)。"""
        b = _png(2000, 1500)
        out, f = _downscale_inline(b, INLINE_MAX_PX)
        assert out is b
        assert f == 1.0


class TestInlineAssembly:
    """TC-DS-05/06:screenshot 返回路径装配(内联降采样真接到 mcp_server,
    非只测纯函数——单据 §6.3 R1/R5)。禁桩:真 Executor 截屏+真落盘。"""

    def _local_server(self, policy, estop, audit_log, tmp_path, bindings,
                      approvals):
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      probe=DesktopProbe())
        enf = Enforcement(policy, bindings, approvals, estop, ex, audit_log)
        # L0 感知工具由 tools 层直调 ctx.executor(cg03 装配先例),必须显式传
        ctx = ToolContext(policy=policy, enforcement=enf, bindings=bindings,
                          executor=ex, audit=audit_log)
        return build_server(ctx, backend="local")

    def _assert_tc_ds_05_06(self, content):
        """TC-DS-05 内联≤2000 ∧ 落盘全分辨率 ∧ scale=f;TC-DS-06 坐标契约。"""
        text = next(c for c in content if c.type == "text")
        images = [c for c in content if c.type == "image"]
        payload = json.loads(text.text)
        assert payload["ok"] is True, payload
        data = payload["data"]
        orig_w, orig_h = data["width"], data["height"]
        if max(orig_w, orig_h) <= INLINE_MAX_PX:
            pytest.skip("环境守卫:虚拟桌面长边≤2000,无法复现超限形态")
        assert len(images) == 1                  # 内联图恰一张(直出)
        inline = Image.open(BytesIO(base64.b64decode(images[0].data)))
        assert max(inline.size) <= INLINE_MAX_PX     # 内联长边≤2000(解码直出)
        disk = Image.open(data["path"])
        assert disk.size == (orig_w, orig_h)     # 落盘=全分辨率(文件解码直出)
        assert max(disk.size) > INLINE_MAX_PX
        f = data["scale_x"]                      # scale 同步为缩放比(JSON 直出)
        assert data["scale_y"] == f
        assert f < 1.0
        assert abs(f - INLINE_MAX_PX / max(orig_w, orig_h)) < 1e-6
        # TC-DS-06:虚拟坐标 = virtual_rect 原点 + 内联像素 / scale——
        # 内联右缘映射回虚拟坐标右缘(换算精确,容差 2px 取整)
        vr = data["virtual_rect"]
        mapped_right = vr[0] + inline.size[0] / f
        assert abs(mapped_right - (vr[0] + orig_w)) < 2
        assert vr[2] - vr[0] == orig_w and vr[3] - vr[1] == orig_h

    def test_tc_ds_05_06_local_backend(self, policy, estop, audit_log,
                                       tmp_path, bindings, approvals):
        """TC-DS-05/06 local 腿:build_server backend=local 真实链路。
        红态(P1 空壳):内联仍原尺寸(长边 3840>2000)→ 内联断言红。"""
        server = self._local_server(policy, estop, audit_log, tmp_path,
                                    bindings, approvals)
        content = _call_tool(server, "screenshot", {"scope": "fullscreen"})
        self._assert_tc_ds_05_06(content)

    def test_tc_ds_05_06_http_backend(self, policy, tmp_path, bindings,
                                      approvals):
        """TC-DS-05/06 http 腿:真 HttpDaemon(cg03 装配先例)+
        build_server backend=http 经 remote_call 真实 HTTP 收发。
        红态(P1 空壳):内联仍原尺寸 → 内联断言红。"""
        audit_dir2 = tmp_path / "daemon_audit"
        audit_dir2.mkdir(parents=True, exist_ok=True)
        audit2 = AuditLogger(str(audit_dir2))
        estop2 = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit2)
        probe2 = DesktopProbe()
        ex2 = Executor(estop2, str(audit_dir2), probe=probe2)
        clock2 = FakeClock()
        bindings2 = BindingManager(probe2, policy.binding_ttl, clock2)
        approvals2 = ApprovalManager(FakeApprover(), policy.approval_ttl, clock2)
        enf2 = Enforcement(policy, bindings2, approvals2, estop2, ex2, audit2)
        ctx2 = ToolContext(policy=policy, enforcement=enf2, bindings=bindings2,
                           executor=ex2, audit=audit2)
        d = HttpDaemon(ctx2, port=0)
        d.start()
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{d.port}/health",
                            timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.1)
            # MCP 侧(瘦代理形态:本侧 ctx 仅供 policy/超时推导)
            audit1 = AuditLogger(str(tmp_path / "audit"))
            estop1 = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit1)
            ex1 = Executor(estop1, str(tmp_path / "audit"),
                           probe=DesktopProbe())
            enf1 = Enforcement(policy, bindings, approvals, estop1, ex1,
                               audit1)
            ctx1 = ToolContext(policy=policy, enforcement=enf1)
            server = build_server(ctx1, backend="http",
                                  daemon_url=f"http://127.0.0.1:{d.port}")
            content = _call_tool(server, "screenshot", {"scope": "fullscreen"})
            self._assert_tc_ds_05_06(content)
        finally:
            d.stop()
