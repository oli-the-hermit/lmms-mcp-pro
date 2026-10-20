"""Smoke test: start the server exactly the way Claude does (stdio) and talk to it.

Usage:  .venv\\Scripts\\python scripts\\smoke_test.py      (Windows)
        .venv/bin/python scripts/smoke_test.py          (Linux/macOS)

Passes if the server starts, completes the MCP handshake, lists its tools and
answers one harmless tool call. Uses the same Python that runs this script.
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "lmms_mcp"],
        env={**os.environ},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"server: {init.server_info.name} {init.server_info.version}")
            tools = (await session.list_tools()).tools
            print(f"tools:  {len(tools)}")
            result = await session.call_tool("note_name_to_key", {"name": "A4"})
            text = " ".join(getattr(c, "text", "") for c in result.content)
            print(f"note_name_to_key('A4') -> {text.strip()[:80]}")
            info = await session.call_tool("get_lmms_info", {})
            text = " ".join(getattr(c, "text", "") for c in info.content)
            print(f"get_lmms_info -> {text.strip()[:300]}")
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
