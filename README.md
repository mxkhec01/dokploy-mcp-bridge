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

## Quick Start

### 1. Add to your Docker Compose stack

```yaml
services:
  mcp-bridge:
    image: ghcr.io/mxkhec01/dokploy-mcp-bridge:latest
    environment:
      - DATABASE_URI=postgresql://user:pass@db:5432/mydb
      - ACCESS_MODE=restricted
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    cap_drop:
      - ALL
```

### 2. Configure Antigravity

Add to `~/.gemini/antigravity/mcp_config.json`:

```json
{
  "mcpServers": {
    "DokployBridge": {
      "transport": "streamable-http",
      "serverUrl": "https://mcp.yourdomain.com/mcp",
      "headers": {
        "Authorization": "Basic <base64>"
      }
    }
  }
}
```

### 3. Talk to your infrastructure

> "List all running containers and check the logs of the API service"

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
- `healthcheck()` — Quick health probe

## Security Model

```
    ┌──────────────────────────────────────────┐
    │  Traefik (TLS + BasicAuth)               │  ← perimeter
    │  ┌───────────────────────────────────┐    │
    │  │  MCP Bridge                       │    │
    │  │  ┌─────────────┐ ┌────────────┐   │    │
    │  │  │ SQL Guard   │ │ Docker :ro │   │    │  ← guardrails
    │  │  │ (regex +    │ │ (socket    │   │    │
    │  │  │  readonly)  │ │  read-only)│   │    │
    │  │  └─────────────┘ └────────────┘   │    │
    │  │  cap_drop: ALL                    │    │  ← capabilities
    │  └───────────────────────────────────┘    │
    └──────────────────────────────────────────┘
```

- **Restricted mode** (default): Only `SELECT` queries, passive Docker ops
- **Admin mode**: Write SQL (migrations), container restart
- **Docker socket**: Mounted read-only (`:ro`)
- **Linux capabilities**: All dropped (`cap_drop: ALL`)
- **Sensitive env vars**: Auto-masked in inspection output

## Multi-Database Support

Configure multiple databases with aliased env vars:

```env
DATABASE_URI=postgresql://admin:pass@main-db:5432/app
DATABASE_URI_PUI=postgresql://pui:pass@pui-db:5432/pui
DATABASE_URI_CEVI=mysql://cevi:pass@cevi-db:3306/cevi
```

Then query by alias:
```
query_database("SELECT * FROM users LIMIT 5", db="pui")
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URI` | — | Primary database connection |
| `DATABASE_URI_<ALIAS>` | — | Additional databases |
| `ACCESS_MODE` | `restricted` | `restricted` or `admin` |
| `MCP_TRANSPORT` | `streamable-http` | Transport protocol |
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8000` | Bind port |
| `MAX_QUERY_ROWS` | `100` | Max rows per query |

## Development

```powershell
# Install deps
pip install -r requirements.txt

# Run locally
$env:DATABASE_URI = "postgresql://admin:pass@localhost:5432/mydb"
python -m src.server --transport=streamable-http --access-mode=admin

# Build Docker image
docker build -t dokploy-mcp-bridge:dev .
```

## License

MIT
