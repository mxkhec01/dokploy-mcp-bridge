"""
Centralized configuration for the Dokploy MCP Bridge.
Loads from CLI args + environment variables with sensible defaults.
"""

import argparse
import os
import re
from dataclasses import dataclass, field


@dataclass
class BridgeConfig:
    """Runtime configuration for the MCP Bridge."""

    transport: str = "streamable-http"
    access_mode: str = "restricted"  # "restricted" | "admin"
    host: str = "0.0.0.0"
    port: int = 8000
    db_uris: dict[str, str] = field(default_factory=dict)
    max_query_rows: int = 100

    # SQL guardrail pattern — blocks destructive ops in restricted mode
    FORBIDDEN_SQL: re.Pattern = field(
        default_factory=lambda: re.compile(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b",
            re.IGNORECASE,
        ),
        repr=False,
    )

    @property
    def is_admin(self) -> bool:
        return self.access_mode == "admin"

    @property
    def is_restricted(self) -> bool:
        return self.access_mode == "restricted"


def parse_db_uris() -> dict[str, str]:
    """
    Parse DATABASE_URI env vars.
    Supports:
      - DATABASE_URI          -> alias "default"
      - DATABASE_URI_<name>   -> alias "<name>" (lowercased)
    """
    uris: dict[str, str] = {}

    # Primary URI
    primary = os.getenv("DATABASE_URI")
    if primary:
        uris["default"] = primary

    # Numbered/named URIs: DATABASE_URI_PUI, DATABASE_URI_CEVI, etc.
    for key, value in os.environ.items():
        if key.startswith("DATABASE_URI_") and value:
            alias = key.replace("DATABASE_URI_", "").lower()
            uris[alias] = value

    return uris


def load_config() -> BridgeConfig:
    """Load config from CLI args with env var fallbacks."""
    parser = argparse.ArgumentParser(description="Dokploy MCP Bridge")
    parser.add_argument(
        "--transport",
        default=os.getenv("MCP_TRANSPORT", "streamable-http"),
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport mode",
    )
    parser.add_argument(
        "--access-mode",
        default=os.getenv("ACCESS_MODE", "restricted"),
        choices=["restricted", "admin"],
        help="Access control mode",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="Server bind host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Server bind port",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=int(os.getenv("MAX_QUERY_ROWS", "100")),
        help="Max rows returned per SQL query",
    )

    args = parser.parse_args()

    return BridgeConfig(
        transport=args.transport,
        access_mode=args.access_mode,
        host=args.host,
        port=args.port,
        db_uris=parse_db_uris(),
        max_query_rows=args.max_rows,
    )
