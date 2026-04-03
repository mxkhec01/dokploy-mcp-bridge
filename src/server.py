"""
Dokploy MCP Bridge — Main Server Entry Point.

A sidecar container that exposes infrastructure tools (DB queries, Docker ops)
via the Model Context Protocol, designed to run alongside Dokploy deployments.

Usage:
    python -m src.server --transport=streamable-http --access-mode=restricted
"""

import sys
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from mcp.server.fastmcp import FastMCP

from src.config import load_config
from src.tools.db import register_db_tools
from src.tools.docker_ops import register_docker_tools
from src.tools.system import register_system_tools


def create_server():
    """Create and configure the MCP server with all tools."""
    config = load_config()

    # Initialize FastMCP with production-optimized settings
    mcp = FastMCP(
        "Dokploy-MCP-Bridge",
        host=config.host,
        port=config.port,
        stateless_http=True,
        json_response=True,
    )

    # Register all tool modules
    register_db_tools(mcp, config)
    register_docker_tools(mcp, config)
    register_system_tools(mcp, config)

    # Banner
    mode_icon = "🔓" if config.is_admin else "🔒"
    db_count = len(config.db_uris)
    print(
        f"\n{'=' * 50}\n"
        f"  Dokploy MCP Bridge v1.0.0\n"
        f"  Transport:  {config.transport}\n"
        f"  Mode:       {mode_icon} {config.access_mode}\n"
        f"  Databases:  {db_count} configured\n"
        f"  Listening:  {config.host}:{config.port}\n"
        f"{'=' * 50}\n",
        file=sys.stderr,
    )

    return mcp, config


def main():
    mcp, config = create_server()
    mcp.run(transport=config.transport)


if __name__ == "__main__":
    main()
