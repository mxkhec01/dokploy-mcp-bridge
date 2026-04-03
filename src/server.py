"""
Dokploy MCP Bridge — Main Server Entry Point.
"""

import sys
import base64
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

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
        # 🟢 FIX 1: Permitir peticiones "Pre-flight" (OPTIONS) para evitar bloqueos de CORS
        if request.url.path == "/health" or request.method == "OPTIONS":
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


class SSEPathRewriteMiddleware:
    """
    🟢 FIX 2: Middleware ASGI puro. 
    Intercepta el texto que FastMCP le devuelve al IDE y le inyecta
    el prefijo '/mcp' para engañar al StripPrefix de Traefik/Dokploy.
    """
    def __init__(self, app, prefix: str = "/mcp"):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.body":
                body = message.get("body", b"")
                # Si FastMCP instruye conectarse a "/messages", le agregamos "/mcp"
                if b"/messages" in body and b"/mcp/messages" not in body:
                    body = body.replace(b"/messages", f"{self.prefix}/messages".encode("utf-8"))
                message["body"] = body
            await send(message)

        return await self.app(scope, receive, send_wrapper)


def health_endpoint(request):
    return PlainTextResponse("ok")


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

    app = Starlette(
        routes=[
            Route("/health", health_endpoint, methods=["GET"]),
            Mount("/", app=mcp.sse_app()), 
        ]
    )

    # 🟢 FIX 3: El CORS DEBE ir al final para que Starlette lo envuelva como la 
    # capa más externa y atienda las peticiones OPTIONS antes que el Auth.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if config.basic_auth:
        app.add_middleware(BasicAuthMiddleware, expected_credentials=config.basic_auth)
        auth_status = "🔒 BasicAuth Enabled (Application Level)"
    else:
        auth_status = "🔓 No Auth (Unsafe for Public Networks)"

    # Aplicamos el parche de ruta ASGI como la capa más externa (después de Starlette middlewares)
    app = SSEPathRewriteMiddleware(app, prefix="/mcp")

    mode_icon = "🔓" if getattr(config, 'is_admin', False) else "🔒"
    db_count = len(getattr(config, 'db_uris', []))
    print(
        f"\n{'=' * 50}\n"
        f"  Dokploy MCP Bridge v1.0.2 (Traefik Fix Injected)\n"
        f"  Transport:  {config.transport}\n"
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
        raise NotImplementedError("Only streamable-http/sse transports are currently supported.")

if __name__ == "__main__":
    main()