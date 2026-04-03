# Dokploy MCP Bridge 🐳

A Docker sidecar container that exposes infrastructure tools via the **Model Context Protocol (MCP)**, designed to run alongside your Dokploy deployments.

## Why?

The Dokploy API and its MCP server handle the **control plane** (create projects, deploy apps, manage domains). But they **cannot**:

| Capability | Dokploy API | This Bridge |
|---|:---:|:---:|
| `docker exec` in containers | ❌ | ✅ |
| Runtime logs (`stdout/stderr`) | ❌ | ✅ |
| Direct SQL queries | ❌ | ✅ |
| Container health inspection | ❌ | ✅ |
| CPU/Memory stats | ❌ | ✅ |
| Container restart | Partial | ✅ |

## Quick Start (Dokploy Native Routing)

You don't need Traefik rules or proxies. The bridge handles its own security!

### 1. Add to your Docker Compose stack

Just add the `mcp-bridge` to the end of your stack.

```yaml
services:
  mcp-bridge:
    image: ghcr.io/mxkhec01/dokploy-mcp-bridge:latest
    environment:
      - DATABASE_URI=postgresql://user:pass@db-service:5432/mydb
      - ACCESS_MODE=restricted
      - MCP_BASIC_AUTH=antigravity:mi_contraseña_segura # User:Pass in plain text
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    cap_drop:
      - ALL
```

### 2. Add Domain in Dokploy
Go to your project in Dokploy > **Domains** > Add Domain:
- **Host:** `mcp.yourdomain.com`
- **Path:** `/` (or `/mcp` if you prefer) -> **Container Port:** `8000`
(*Dokploy automatically handles Let's Encrypt TLS for you!*)

### 3. Configure Antigravity

Add to `~/.gemini/antigravity/mcp_config.json`:

```json
{
  "mcpServers": {
    "DokployBridge": {
      "transport": "streamable-http",
      "serverUrl": "https://mcp.yourdomain.com/mcp", 
      "headers": {
        "Authorization": "Basic YW50aWdyYXZpdHk6bWlfY29udHJhc2XDsWFfc2VndXJh"
      }
    }
  }
}
```
*(The payload is `Basic <base64(user:pass)>`)*

> ✨ **Done!**
> Talk to your infrastructure: *"List all running containers and check the logs of the API service"*

---

## Security Model

```
    ┌──────────────────────────────────────────┐
    │  Dokploy Router (TLS / Let's Encrypt)    │  ← perimeter
    │  ┌───────────────────────────────────┐    │
    │  │  MCP Bridge [Port 8000]           │    │
    │  │  │ HTTP BasicAuth Middleware      │    │  ← app-level security
    │  │  ┌─────────────┐ ┌────────────┐   │    │
    │  │  │ SQL Guard   │ │ Docker :ro │   │    │  ← guardrails
    │  │  │ (regex +    │ │ (socket    │   │    │
    │  │  │  readonly)  │ │  read-only)│   │    │
    │  │  └─────────────┘ └────────────┘   │    │
    │  │  cap_drop: ALL                    │    │  ← capabilities
    │  └───────────────────────────────────┘    │
    └──────────────────────────────────────────┘
```

## Tools Available
### Database
- `list_databases()` — Show configured DB connections
- `query_database(query, db)` — Execute SQL (SELECT only in restricted mode)

### Docker
- `docker_list_containers()` — List containers with status and health
- `docker_get_logs(name, tail, since)` — Get container logs
- `docker_inspect(name)` — Full container inspection (state, networks, ports, env)
- `docker_stats(name)` — Real-time CPU/memory usage
- `docker_restart(name)` — Restart a container (admin mode only)

### System
- `server_info()` — Bridge version, mode, uptime, connectivity
- `healthcheck()` — Quick probe (`/health` bypasses auth for load balancers)
