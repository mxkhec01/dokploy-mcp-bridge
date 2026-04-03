"""
System and utility tools for the Dokploy MCP Bridge.
"""

import time

from src.config import BridgeConfig

_start_time = time.time()


def register_system_tools(mcp, config: BridgeConfig):
    """Register system/utility tools onto the MCP server."""

    @mcp.tool()
    def server_info() -> str:
        """
        Get information about the MCP Bridge server.
        Returns version, access mode, uptime, configured databases, and Docker status.
        """
        uptime_s = int(time.time() - _start_time)
        hours, remainder = divmod(uptime_s, 3600)
        minutes, seconds = divmod(remainder, 60)

        # Check Docker connectivity
        try:
            import docker as _docker

            client = _docker.from_env()
            client.ping()
            docker_status = "✅ Connected"
            docker_version = client.version().get("Version", "unknown")
        except Exception:
            docker_status = "❌ Unavailable"
            docker_version = "N/A"

        # DB summary
        db_count = len(config.db_uris)
        db_aliases = ", ".join(config.db_uris.keys()) if config.db_uris else "none"

        return (
            "=== Dokploy MCP Bridge ===\n"
            f"  Version:      1.0.0\n"
            f"  Access Mode:  {config.access_mode}\n"
            f"  Transport:    {config.transport}\n"
            f"  Uptime:       {hours}h {minutes}m {seconds}s\n"
            f"  Docker:       {docker_status} (v{docker_version})\n"
            f"  Databases:    {db_count} configured ({db_aliases})\n"
            f"  Max Rows:     {config.max_query_rows}"
        )

    @mcp.tool()
    def healthcheck() -> str:
        """
        Quick health check — returns 'ok' if the server is responsive.
        Useful for monitoring and Traefik health probes.
        """
        return "ok"

    return [server_info, healthcheck]
