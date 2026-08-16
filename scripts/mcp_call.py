"""DeskPilot MCP 通用调用客户端（开发/联调工具，非业务代码）。

用法：
  python scripts/mcp_call.py __list__
  python scripts/mcp_call.py <tool> '<json参数>'
环境变量 DESKPILOT_CMD / DESKPILOT_ARGS 指定服务端启动命令
（默认：当前虚拟环境 python -m deskpilot，工作目录为仓库根）。
所有桌面操作均经 DeskPilot MCP 协议与强制层，客户端只做协议收发。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CMD = str(REPO_ROOT / ".venv" / "Scripts" / "python.exe")


async def run(tool: str, args: dict) -> None:
    cmd = os.environ.get("DESKPILOT_CMD", DEFAULT_CMD)
    cmd_args = os.environ.get("DESKPILOT_ARGS", "-m deskpilot").split()
    params = StdioServerParameters(command=cmd, args=cmd_args, cwd=str(REPO_ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if tool == "__batch__":
                await run_batch(session, args)
                return
            if tool == "__list__":
                listed = await session.list_tools()
                for t in listed.tools:
                    print(t.name)
                return
            await call_and_print(session, tool, args)


async def run_batch(session: ClientSession, batch: dict) -> None:
    """单会话内顺序执行一批调用（绑定等会话状态在批内有效）。

    变量：步骤结果 data.token / data.hwnd 自动存为变量，
    后续步骤的参数值写 "$token" / "$hwnd" 即被替换。
    """
    variables: dict[str, Any] = {}
    for i, step in enumerate(batch["calls"]):
        tool = step["tool"]
        args = {k: variables.get(v[1:], v) if isinstance(v, str) and v.startswith("$") else v
                for k, v in step.get("args", {}).items()}
        print(f"=== [{i}] {tool} {json.dumps(args, ensure_ascii=False)}")
        try:
            texts = await call_and_print(session, tool, args)
            for t in texts:
                try:
                    data = json.loads(t).get("data") or {}
                except (ValueError, AttributeError):
                    continue
                for key in ("token", "hwnd"):
                    if isinstance(data, dict) and key in data:
                        variables[key] = data[key]
        except Exception as e:
            print(f"!! step {i} 异常: {e}")
            if batch.get("stop_on_error", True):
                raise
        delay = batch.get("step_delay_ms", 0)
        if delay:
            time.sleep(delay / 1000)


async def call_and_print(session: ClientSession, tool: str, args: dict) -> list[str]:
    result = await session.call_tool(tool, args)
    texts: list[str] = []
    for content in result.content:
        if content.type == "text":
            print(content.text)
            texts.append(content.text)
        elif content.type == "image":
            out = REPO_ROOT / f"mcp_shot_{int(time.time() * 1000)}.png"
            out.write_bytes(base64.b64decode(content.data))
            print(f"IMAGE_SAVED {out}")
    return texts


if __name__ == "__main__":
    tool_name = sys.argv[1] if len(sys.argv) > 1 else "__list__"
    if tool_name == "__batch__":
        batch_spec = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        asyncio.run(run("__batch__", batch_spec))
    else:
        arguments = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        asyncio.run(run(tool_name, arguments))
