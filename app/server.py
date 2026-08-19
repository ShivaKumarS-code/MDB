import os

from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server import MCPServer

from app.database import get_schema as fetch_schema
from app.vector_store import search_schema as semantic_search
from app.vector_store import sync_schema

load_dotenv()

mcp = MCPServer("MDB")


# ---------------------------------------------------------------------------
# Custom HTTP routes
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> Response:
    """Basic health check endpoint."""
    return JSONResponse({"status": "healthy", "service": "MDB"})


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def ping() -> str:
    """Check whether MDB is running."""
    return "MDB is alive!"


@mcp.tool()
def get_schema() -> str:
    """Return the complete database schema."""

    schema = fetch_schema()

    if not schema:
        return "No tables found."

    output = []

    for table_name, table_data in schema.items():
        output.append(f"Table: {table_name}")

        for column in table_data["columns"]:
            pk_marker = " [PK]" if column.get("primary_key") else ""
            nullable_marker = " (nullable)" if column.get("nullable") else ""
            output.append(
                f"  - {column['name']} ({column['type']})"
                f"{pk_marker}{nullable_marker}"
            )

        for relationship in table_data["relationships"]:
            output.append(
                f"  FK: {relationship['column']} → "
                f"{relationship['references_table']}."
                f"{relationship['references_column']}"
            )

        output.append("")

    return "\n".join(output)


@mcp.tool()
def search_schema(query: str) -> str:
    """Find database tables and columns relevant to a natural-language query."""

    results = semantic_search(query)

    if not results:
        return "No relevant schema found."

    return "\n\n".join(results)


@mcp.tool()
def resync_schema() -> str:
    """Re-synchronize the Pinecone vector index with the current database
    schema. Only re-embeds tables that are new or changed; removes vectors
    for tables that were dropped from the database.
    """
    summary = sync_schema()
    return (
        f"Schema sync complete: "
        f"{summary['added']} added, "
        f"{summary['updated']} updated, "
        f"{summary['removed']} removed, "
        f"{summary['unchanged']} unchanged."
    )


@mcp.tool()
def get_table_context(table_name: str) -> str:
    """Return detailed context for a specific database table."""

    schema = fetch_schema()

    if table_name not in schema:
        return f"Table '{table_name}' not found."

    table = schema[table_name]

    output = [f"Table: {table_name}", "", "Columns:"]

    for column in table["columns"]:
        pk_marker = " [PK]" if column.get("primary_key") else ""
        nullable_marker = " (nullable)" if column.get("nullable") else ""
        default_info = f" default={column['default']}" if column.get("default") else ""
        output.append(
            f"- {column['name']}: {column['type']}"
            f"{pk_marker}{nullable_marker}{default_info}"
        )

    output.append("")
    output.append("Relationships:")

    if table["relationships"]:
        for relationship in table["relationships"]:
            output.append(
                f"- {relationship['column']} → "
                f"{relationship['references_table']}."
                f"{relationship['references_column']}"
            )
    else:
        output.append("None")

    return "\n".join(output)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.getenv("MDB_HOST", "0.0.0.0")
    port = int(os.getenv("MDB_PORT", "8000"))

    print(f"Starting MDB on {host}:{port}")
    print(f"  MCP endpoint: http://{host}:{port}/mcp")
    print(f"  Health check: http://{host}:{port}/health")

    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
    )