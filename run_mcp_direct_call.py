import argparse
import asyncio
import sys
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters


def _parse_args():
    p = argparse.ArgumentParser(
        description="Call google-search tool via MCP stdio server"
    )
    p.add_argument(
        "--basic", action="store_true", help="Request Basic View (gbv=1) for the search"
    )
    return p.parse_args()


async def main():
    args = _parse_args()

    server_params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_integration.server"], env=None
    )

    # start server subprocess and create session
    async with stdio_client(server_params) as transport:
        stdio, write = transport
        async with ClientSession(stdio, write) as session:
            await session.initialize()
            print("✅ Connected to MCP server, calling tool...")

            try:
                call_args = {"query": "mcp smoke test", "limit": 1, "timeout": 30000}
                if args.basic:
                    call_args["basic_view"] = True

                result = await session.call_tool("google-search", call_args)
                print("--- Tool result (repr) ---")
                print(repr(result))
                print("--- Tool result (text items) ---")
                # Support different return shapes:
                # - CallToolResult with .content (list of TextContent)
                # - direct iterable/list of TextContent
                # - fallback: print the object
                content_items = None
                if hasattr(result, "content") and result.content:
                    content_items = result.content
                elif isinstance(result, (list, tuple)):
                    content_items = result

                if content_items is not None:
                    for item in content_items:
                        try:
                            print(item.text)
                        except Exception:
                            print(item)
                else:
                    print(result)
            except Exception as e:
                print(f"Tool call failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
