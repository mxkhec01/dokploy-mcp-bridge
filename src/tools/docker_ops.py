"""
Docker operations tools for the Dokploy MCP Bridge.
Provides container observability and (in admin mode) restart capabilities.
Includes Stack Isolation to ensure the bridge only sees containers in its own compose project.
"""

import docker
import socket

from src.config import BridgeConfig

# Module-level client — initialized once
_docker_client = None
_docker_error = None
_compose_project_name = None
_compose_project_checked = False


def _get_client():
    """Lazy-initialize the Docker client."""
    global _docker_client, _docker_error
    if _docker_client is None and _docker_error is None:
        try:
            _docker_client = docker.from_env()
            # Quick ping to verify connectivity
            _docker_client.ping()
        except Exception as e:
            _docker_error = str(e)
            _docker_client = None
    return _docker_client, _docker_error


def _get_compose_project(client):
    """
    Auto-detect the Docker Compose project this bridge container belongs to.
    This effectively isolates the environment to its own Stack.
    """
    global _compose_project_name, _compose_project_checked
    if _compose_project_checked:
        return _compose_project_name
    
    _compose_project_checked = True
    
    def extract_from_container(cid):
        try:
            container = client.containers.get(cid)
            return container.labels.get("com.docker.compose.project")
        except docker.errors.NotFound:
            return None

    # 1. Try hostname (default is container short ID in Docker)
    hostname = socket.gethostname()
    proj = extract_from_container(hostname)
    if proj:
        _compose_project_name = proj
        return proj
        
    # 2. Advanced fallback: read from /proc/self/mountinfo
    try:
        with open("/proc/self/mountinfo", "r") as f:
            for line in f:
                if "/docker/containers/" in line:
                    cid = line.split("/docker/containers/")[1].split("/")[0]
                    proj = extract_from_container(cid)
                    if proj:
                        _compose_project_name = proj
                        return proj
    except Exception:
        pass

    return None

def _validate_container_isolation(client, container) -> str:
    """Returns an error string if the container is outside the current stack, else empty."""
    project_name = _get_compose_project(client)
    if project_name:
        container_project = container.labels.get("com.docker.compose.project")
        if container_project != project_name:
            return f"🛑 SECURITY: Container '{container.name}' belongs to stack '{container_project}', not the isolated stack '{project_name}'."
    return ""


def register_docker_tools(mcp, config: BridgeConfig):
    """Register all Docker tools onto the MCP server."""

    @mcp.tool()
    def docker_list_containers(all_containers: bool = False) -> str:
        """
        List Docker containers visible from the bridge.
        Automatically isolated to the current compose project/stack.

        Args:
            all_containers: If True, include stopped containers. Default: only running.
        """
        client, err = _get_client()
        if not client:
            return f"Docker API unavailable: {err}"

        try:
            filters = {}
            project_name = _get_compose_project(client)
            
            if project_name:
                filters["label"] = f"com.docker.compose.project={project_name}"
                
            containers = client.containers.list(all=all_containers, filters=filters)
            if not containers:
                return f"No containers found in stack {'(' + project_name + ')' if project_name else ''}."

            lines = []
            for c in containers:
                health = ""
                if c.attrs.get("State", {}).get("Health"):
                    health = f" | Health: {c.attrs['State']['Health']['Status']}"
                lines.append(
                    f"  {c.short_id} | {c.name:<30} | {c.status}{health}"
                )

            header = f"ID         | Name                           | Status     [Stack: {project_name or 'Global'}]"
            separator = "-" * 80
            return f"{header}\n{separator}\n" + "\n".join(lines)
        except Exception as e:
            return f"Docker error: {e}"

    @mcp.tool()
    def docker_get_logs(
        container_name: str, tail: int = 200, since: str = ""
    ) -> str:
        """
        Get logs from a specific container.

        Args:
            container_name: Container name or ID.
            tail: Number of lines from the end (default: 200).
            since: Optional timestamp filter, e.g. '2024-01-01T00:00:00' or '10m' for last 10 minutes.
        """
        client, err = _get_client()
        if not client:
            return f"Docker API unavailable: {err}"

        try:
            container = client.containers.get(container_name)
            
            isolation_err = _validate_container_isolation(client, container)
            if isolation_err: return isolation_err

            kwargs = {"tail": tail, "stdout": True, "stderr": True}
            if since:
                if since.endswith("m"):
                    import time
                    minutes = int(since.rstrip("m"))
                    kwargs["since"] = int(time.time()) - (minutes * 60)
                elif since.endswith("h"):
                    import time
                    hours = int(since.rstrip("h"))
                    kwargs["since"] = int(time.time()) - (hours * 3600)
                else:
                    kwargs["since"] = since

            logs = container.logs(**kwargs)
            decoded = logs.decode("utf-8", errors="replace")

            if not decoded.strip():
                return f"No logs available for container '{container_name}'."

            return f"=== Logs: {container_name} (tail={tail}) ===\n{decoded}"
        except docker.errors.NotFound:
            return f"Container '{container_name}' not found."
        except Exception as e:
            return f"Error reading logs: {e}"

    @mcp.tool()
    def docker_inspect(container_name: str) -> str:
        """
        Inspect a container — returns state, health, networks, ports, and environment.

        Args:
            container_name: Container name or ID.
        """
        client, err = _get_client()
        if not client:
            return f"Docker API unavailable: {err}"

        try:
            container = client.containers.get(container_name)
            
            isolation_err = _validate_container_isolation(client, container)
            if isolation_err: return isolation_err
            
            attrs = container.attrs
            state = attrs.get("State", {})
            net_settings = attrs.get("NetworkSettings", {})
            config_section = attrs.get("Config", {})

            # Build structured output
            lines = [
                f"=== Container: {container.name} ===",
                f"  ID:       {container.id[:12]}",
                f"  Image:    {config_section.get('Image', 'unknown')}",
                f"  Status:   {state.get('Status', 'unknown')}",
                f"  Running:  {state.get('Running', False)}",
                f"  Started:  {state.get('StartedAt', 'N/A')}",
                f"  Restarts: {attrs.get('RestartCount', 0)}",
            ]

            # Health check
            health = state.get("Health")
            if health:
                lines.append(f"  Health:   {health.get('Status', 'unknown')}")
                health_log = health.get("Log", [])
                if health_log:
                    last = health_log[-1]
                    lines.append(f"  Last Check: exit={last.get('ExitCode')} output={last.get('Output', '').strip()[:200]}")

            # Networks
            networks = net_settings.get("Networks", {})
            if networks:
                lines.append("  Networks:")
                for name, net_info in networks.items():
                    lines.append(f"    - {name}: IP={net_info.get('IPAddress', 'N/A')}")

            # Ports
            ports = net_settings.get("Ports", {})
            if ports:
                lines.append("  Ports:")
                for port, bindings in ports.items():
                    if bindings:
                        for b in bindings:
                            lines.append(f"    - {port} -> {b.get('HostIp', '')}:{b.get('HostPort', '')}")
                    else:
                        lines.append(f"    - {port} (not published)")

            # Environment (mask sensitive values)
            env_list = config_section.get("Env", [])
            if env_list:
                lines.append("  Environment:")
                sensitive_keys = {"password", "secret", "token", "key", "auth"}
                for env_entry in env_list:
                    if "=" in env_entry:
                        k, v = env_entry.split("=", 1)
                        if any(s in k.lower() for s in sensitive_keys):
                            v = "****"
                        lines.append(f"    {k}={v}")

            return "\n".join(lines)
        except docker.errors.NotFound:
            return f"Container '{container_name}' not found."
        except Exception as e:
            return f"Error inspecting container: {e}"

    @mcp.tool()
    def docker_stats(container_name: str) -> str:
        """
        Get real-time resource usage stats for a container (CPU, memory).

        Args:
            container_name: Container name or ID.
        """
        client, err = _get_client()
        if not client:
            return f"Docker API unavailable: {err}"

        try:
            container = client.containers.get(container_name)
            
            isolation_err = _validate_container_isolation(client, container)
            if isolation_err: return isolation_err
            
            stats = container.stats(stream=False)

            # CPU calculation
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"]
                - stats["precpu_stats"]["system_cpu_usage"]
            )
            num_cpus = stats["cpu_stats"].get("online_cpus", 1)
            cpu_percent = 0.0
            if system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0

            # Memory calculation
            mem_usage = stats["memory_stats"].get("usage", 0)
            mem_limit = stats["memory_stats"].get("limit", 1)
            mem_percent = (mem_usage / mem_limit) * 100.0

            def fmt_bytes(b):
                for unit in ["B", "KB", "MB", "GB"]:
                    if b < 1024:
                        return f"{b:.1f}{unit}"
                    b /= 1024
                return f"{b:.1f}TB"

            # Network I/O
            net_io = stats.get("networks", {})
            net_rx = sum(v.get("rx_bytes", 0) for v in net_io.values())
            net_tx = sum(v.get("tx_bytes", 0) for v in net_io.values())

            return (
                f"=== Stats: {container_name} ===\n"
                f"  CPU:     {cpu_percent:.2f}% ({num_cpus} cores)\n"
                f"  Memory:  {fmt_bytes(mem_usage)} / {fmt_bytes(mem_limit)} ({mem_percent:.1f}%)\n"
                f"  Net RX:  {fmt_bytes(net_rx)}\n"
                f"  Net TX:  {fmt_bytes(net_tx)}"
            )
        except docker.errors.NotFound:
            return f"Container '{container_name}' not found."
        except KeyError as e:
            return f"Stats parsing error (container may not be running): {e}"
        except Exception as e:
            return f"Error getting stats: {e}"

    @mcp.tool()
    def docker_restart(container_name: str, timeout: int = 10) -> str:
        """
        Restart a container. Only available in admin mode.

        Args:
            container_name: Container name or ID.
            timeout: Seconds to wait before killing the container (default: 10).
        """
        if config.is_restricted:
            return (
                "🛑 SECURITY: Container restart is blocked in restricted mode. "
                "Set --access-mode=admin to enable."
            )

        client, err = _get_client()
        if not client:
            return f"Docker API unavailable: {err}"

        try:
            container = client.containers.get(container_name)
            
            isolation_err = _validate_container_isolation(client, container)
            if isolation_err: return isolation_err
            
            container.restart(timeout=timeout)
            return f"✅ Container '{container_name}' restarted successfully."
        except docker.errors.NotFound:
            return f"Container '{container_name}' not found."
        except docker.errors.APIError as e:
            return f"Docker API error: {e}"
        except Exception as e:
            return f"Error restarting container: {e}"

    return [
        docker_list_containers,
        docker_get_logs,
        docker_inspect,
        docker_stats,
        docker_restart,
    ]
