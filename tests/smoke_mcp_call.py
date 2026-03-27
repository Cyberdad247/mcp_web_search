import asyncio
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_integration.server"], env=None)
    async with stdio_client(params) as transport:
        # transport should be (stdio, write)
        try:
            stdio, write = transport
        except Exception as e:
            print(f"Failed to unpack stdio transport: {e}")
            return

        async with ClientSession(stdio, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Available tools:", [t.name for t in tools.tools])
            res = await session.call_tool("google-search", {"query": "playwright smoke test", "limit": 1})
            print("Raw result:")
            print(res)

if __name__ == '__main__':
    asyncio.run(main())
