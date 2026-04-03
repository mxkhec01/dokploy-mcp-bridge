"""
Dokploy MCP Bridge — Main Server Entry Point.
"""

import sys
import base64
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware  # <-- IMPORTANTE NUEVO IMPORT

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
        # FIX 1: Excluir el healthcheck y las peticiones de CORS (OPTIONS) del chequeo de Auth
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


class TraefikSSEFixMiddleware(BaseHTTPMiddleware):
    """
    Sustituye a TraefikRootPathMiddleware.
    Intercepta el flujo SSE en tiempo real y reescribe el endpoint para que el 
    cliente sepa que debe inyectar el prefijo /mcp en sus peticiones POST.
    """
    def __init__(self, app, public_prefix: str = "/mcp"):
        super().__init__(app)
        self.public_prefix = public_prefix
        
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        
        # Si la respuesta es un flujo SSE, lo modificamos al vuelo
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            original_iterator = getattr(response, "body_iterator", None)
            if original_iterator:
                async def rewrite_generator():
                    async for chunk in original_iterator:
                        # Remplazamos la orden que FastMCP le da al cliente
                        if isinstance(chunk, bytes):
                            chunk = chunk.replace(b"data: /messages", f"data: {self.public_prefix}/messages".encode("utf-8"))
                        elif isinstance(chunk, str):
                            chunk = chunk.replace("data: /messages", f"data: {self.public_prefix}/messages")
                        yield chunk
                        
                headers = dict(response.headers)
                headers.pop("content-length", None)
                return StreamingResponse(
                    rewrite_generator(),
                    status_code=response.status_code,
                    headers=headers
                )
                
        return response


def health_endpoint(request):
    return PlainTextResponse("ok")


def create_server():
    """Create and configure the MCP server with all tools."""
    config = load_config()

    mcp = FastMCP(
        "Dokploy-MCP-Bridge",
        port=config.port,
        host=config.host,
        json_response=True,
    )

    # Register all tool modules
    register_db_tools(mcp, config)
    register_docker_tools(mcp, config)
    register_system_tools(mcp, config)

    app = Starlette(
        routes=[
            Route("/health", health_endpoint, methods=["GET"]),
            Mount("/", app=mcp.sse_app()), 
        ]
    )

    # FIX 2: Añadimos CORS nativo para clientes basados en Web/Electron
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # FIX 3: Inyectamos el middleware que corrige el bug de la ruta de Traefik
    import os
    public_prefix = os.environ.get("MCP_PUBLIC_PREFIX", "/mcp")
    app.add_middleware(TraefikSSEFixMiddleware, public_prefix=public_prefix)

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
        raise NotImplementedError("Only streamable-http/sse transports are currently supported with the custom Starlette runner.")


if __name__ == "__main__":
    main()