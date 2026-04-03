"""
Dokploy MCP Bridge — Main Server Entry Point.

A sidecar container that exposes infrastructure tools (DB queries, Docker ops)
via the Model Context Protocol, designed to run alongside Dokploy deployments.

Usage:
    python -m src.server --transport=streamable-http --access-mode=restricted
"""

import sys
import base64
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.middleware.base import BaseHTTPMiddleware

from mcp.server.fastmcp import FastMCP

from src.config import load_config
from src.tools.db import register_db_tools
from src.tools.docker_ops import register_docker_tools
from src.tools.system import register_system_tools


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, expected_credentials: str):
        super().__init__(app)
        self.expected = expected_credentials
        
    async def dispatch(self, request, call_next):
        # Exclude internal healthcheck from auth requirement
        if request.url.path == "/health":
            return await call_next(request)

        if "authorization" not in request.headers:
            return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Basic"})
        
        auth = request.headers["authorization"]
        try:
            scheme, credentials = auth.split()
            if scheme.lower() == 'basic':
                decoded = base64.b64decode(credentials).decode("ascii")
                if decoded == self.expected:
                    return await call_next(request)
        except Exception:
            pass
            
        return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Basic"})


def health_endpoint(request):
    return PlainTextResponse("ok")


def create_server():
    """Create and configure the MCP server with all tools."""
    config = load_config()

    # Initialize FastMCP with production-optimized settings
    mcp = FastMCP(
        "Dokploy-MCP-Bridge",
        port=config.port,
        host=config.host,
        stateless_http=True,
        json_response=True,
    )

    # Register all tool modules
    register_db_tools(mcp, config)
    register_docker_tools(mcp, config)
    register_system_tools(mcp, config)

    # Wrap FastMCP internals inside a Starlette App to inject Application-Level HTTP BasicAuth
    # This allows it to run safely behind standard Dokploy URLs without Traefik middleware hassle.
    app = Starlette(
        routes=[
            Route("/health", health_endpoint, methods=["GET"]),
            # Expose standard SSE (for Cursor and older clients)
            # mcp.sse_app() internally configures routes for `/sse` and `/messages`
            Mount("/", app=mcp.sse_app()), 
            # Expose new Streamable HTTP fallback
            # Mount("/mcp", app=mcp.streamable_http_app()), 
        ]
    )

    if config.basic_auth:
        app.add_middleware(BasicAuthMiddleware, expected_credentials=config.basic_auth)
        auth_status = "🔒 BasicAuth Enabled (Application Level)"
    else:
        auth_status = "🔓 No Auth (Unsafe for Public Networks)"

    # Banner
    mode_icon = "🔓" if config.is_admin else "🔒"
    db_count = len(config.db_uris)
    print(
        f"\n{'=' * 50}\n"
        f"  Dokploy MCP Bridge v1.0.0\n"
        f"  Transport:  {config.transport} (SSE Available locally via /sse, MCP via /mcp)\n"
        f"  Mode:       {mode_icon} {config.access_mode}\n"
        f"  Security:   {auth_status}\n"
        f"  Databases:  {db_count} configured\n"
        f"  Listening:  {config.host}:{config.port}\n"
        f"{'=' * 50}\n",
        file=sys.stderr,
    )

    return app, config


def main():
    app, config = create_server()
    if config.transport in ["streamable-http", "sse"]:
        uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    else:
        # Fallback for stdio
        raise NotImplementedError("Only streamable-http/sse transports are currently supported with the custom Starlette runner.")


if __name__ == "__main__":
    main()
