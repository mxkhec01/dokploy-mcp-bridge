"""
Database tools for the Dokploy MCP Bridge.
Supports PostgreSQL and MySQL with multi-URI connections.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

from src.config import BridgeConfig

# Lazy-loaded MySQL support
_pymysql = None


def _get_pymysql():
    global _pymysql
    if _pymysql is None:
        import pymysql as _mod

        _pymysql = _mod
    return _pymysql


def _detect_driver(uri: str) -> str:
    """Detect database type from URI scheme."""
    if uri.startswith("mysql"):
        return "mysql"
    return "postgres"


def _parse_mysql_uri(uri: str) -> dict:
    """
    Parse a MySQL URI into pymysql connection kwargs.
    Supports: mysql://user:pass@host:port/dbname
    """
    import re

    pattern = r"mysql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(\w+)"
    m = re.match(pattern, uri)
    if not m:
        raise ValueError(f"Cannot parse MySQL URI: {uri}")
    return {
        "host": m.group(3),
        "port": int(m.group(4) or 3306),
        "user": m.group(1),
        "password": m.group(2),
        "database": m.group(5),
    }


def register_db_tools(mcp, config: BridgeConfig):
    """Register all database tools onto the MCP server."""

    @mcp.tool()
    def list_databases() -> str:
        """List all configured database connections and their aliases."""
        if not config.db_uris:
            return "No databases configured. Set DATABASE_URI or DATABASE_URI_<alias> environment variables."

        lines = []
        for alias, uri in config.db_uris.items():
            driver = _detect_driver(uri)
            # Mask password in display
            masked = uri
            if "@" in uri:
                pre, post = uri.split("@", 1)
                if ":" in pre:
                    scheme_user = pre.rsplit(":", 1)[0]
                    masked = f"{scheme_user}:****@{post}"
            lines.append(f"  [{alias}] ({driver}) -> {masked}")

        return "Configured databases:\n" + "\n".join(lines)

    @mcp.tool()
    def query_database(query: str, db: str = "default") -> str:
        """
        Execute a SQL query against a configured database.

        Args:
            query: SQL query to execute.
            db: Database alias (default: 'default'). Use list_databases() to see available aliases.

        In restricted mode, only SELECT queries are allowed.
        In admin mode, all queries are allowed (use with caution).
        Results are limited to prevent context window overflow.
        """
        if db not in config.db_uris:
            available = ", ".join(config.db_uris.keys()) if config.db_uris else "none"
            return f"Error: Database alias '{db}' not found. Available: {available}"

        uri = config.db_uris[db]

        # GUARDRAIL: Block destructive operations in restricted mode
        if config.is_restricted and config.FORBIDDEN_SQL.search(query):
            return (
                "🛑 SECURITY: Operation blocked. Only SELECT queries are allowed "
                "in restricted mode. Switch to --access-mode=admin for write operations."
            )

        driver = _detect_driver(uri)

        try:
            if driver == "postgres":
                return _exec_postgres(uri, query, config)
            else:
                return _exec_mysql(uri, query, config)
        except Exception as e:
            return f"Database error [{db}]: {type(e).__name__}: {str(e)}"

    return [list_databases, query_database]


def _exec_postgres(uri: str, query: str, config: BridgeConfig) -> str:
    """Execute query on PostgreSQL."""
    with psycopg2.connect(uri) as conn:
        # Extra safety: enforce readonly at connection level in restricted mode
        if config.is_restricted:
            conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            if cur.description:
                rows = cur.fetchmany(config.max_query_rows)
                total = cur.rowcount
                result = str(rows)
                if total > config.max_query_rows:
                    result += f"\n... ({total} total rows, showing first {config.max_query_rows})"
                return result
            else:
                # Non-SELECT (in admin mode)
                conn.commit()
                return f"OK. Rows affected: {cur.rowcount}"


def _exec_mysql(uri: str, query: str, config: BridgeConfig) -> str:
    """Execute query on MySQL."""
    pymysql = _get_pymysql()
    params = _parse_mysql_uri(uri)

    conn = pymysql.connect(
        **params,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=config.is_admin,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            if cur.description:
                rows = cur.fetchmany(config.max_query_rows)
                total = cur.rowcount
                result = str(rows)
                if total > config.max_query_rows:
                    result += f"\n... ({total} total rows, showing first {config.max_query_rows})"
                return result
            else:
                conn.commit()
                return f"OK. Rows affected: {cur.rowcount}"
    finally:
        conn.close()
