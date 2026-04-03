"""
Dokploy MCP Bridge — Main Server Entry Point.
"""

import sys
import base64
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from mcp.server.fastmcp import FastMCP

from src.config import load_config
from src.tools.db import register_db_tools
from src.tools.docker_ops import register_docker_tools
from src.tools.system import register_system_tools

# ──────────────────────────────────────────────
# VERSION — se quema en build-time via Docker ARG
# Si no hay build arg, usa el fallback local.
# ──────────────────────────────────────────────
import os
BUILD_VERSION = os.environ.get("BUILD_VERSION", "local-dev")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, expected_credentials: str):
        super().__init__(app)
        self.expected = expected_credentials
        
    async def dispatch(self, request, call_next):
        # Excluir healthcheck, versión y peticiones OPTIONS (CORS pre-flight)
        if request.url.path in ("/health", "/version") or request.method == "OPTIONS":
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


def version_endpoint(request):
    """Endpoint público para verificar qué versión está corriendo."""
    return JSONResponse({
        "service": "Dokploy-MCP-Bridge",
        "version": BUILD_VERSION,
        "transport": "sse",
    })


def create_server():
    """Create and configure the MCP server with all tools."""
    config = load_config()

    mcp = FastMCP(
        "Dokploy-MCP-Bridge",
        port=config.port,
        host=config.host,
        stateless_http=True,
        json_response=True,
    )

    register_db_tools(mcp, config)
    register_docker_tools(mcp, config)
    register_system_tools(mcp, config)

    # ──────────────────────────────────────────────────────────────
    # ROUTING FIX:
    #
    # Dokploy (Traefik) está configurado con:
    #   Path: /mcp  |  Strip Path: NO
    #
    # Esto significa que el contenedor recibe las peticiones tal cual:
    #   GET  /mcp/sse          → handshake SSE
    #   POST /mcp/messages/xxx → mensajes MCP
    #
    # Por lo tanto, montamos el SSE app en "/mcp".
    # Esto hace que Starlette le quite el prefijo "/mcp" internamente
    # y SSE vea "/sse" y "/messages/" como espera.
    #
    # Además, como SSE está montado en "/mcp", automáticamente genera
    # las URLs de callback como "/mcp/messages/xxx" — ¡exactamente lo
    # que Traefik necesita recibir de vuelta! No se necesita ningún
    # middleware de reescritura.
    # ──────────────────────────────────────────────────────────────
    app = Starlette(
        routes=[
            Route("/health", health_endpoint, methods=["GET"]),
            Route("/version", version_endpoint, methods=["GET"]),
            Mount("/mcp", app=mcp.sse_app()),
        ]
    )

    # CORS para clientes basados en Web/Electron (Cursor)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if config.basic_auth:
        app.add_middleware(BasicAuthMiddleware, expected_credentials=config.basic_auth)
        auth_status = "🔒 BasicAuth Enabled"
    else:
        auth_status = "🔓 No Auth (Unsafe)"

    mode_icon = "🔓" if getattr(config, 'is_admin', False) else "🔒"
    db_count = len(getattr(config, 'db_uris', []))
    print(
        f"\n{'=' * 50}\n"
        f"  Dokploy MCP Bridge  [{BUILD_VERSION}]\n"
        f"  Transport:  {config.transport}\n"
        f"  Mode:       {mode_icon} {config.access_mode}\n"
        f"  Security:   {auth_status}\n"
        f"  Databases:  {db_count} configured\n"
        f"  Listening:  {config.host}:{config.port}\n"
        f"  SSE Mount:  /mcp/sse\n"
        f"{'=' * 50}\n",
        file=sys.stderr,
    )

    return app, config


def main():
    app, config = create_server()
    if config.transport in ["streamable-http", "sse"]:
        uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    else:
        raise NotImplementedError("Only streamable-http/sse transports are currently supported.")


if __name__ == "__main__":
    main()