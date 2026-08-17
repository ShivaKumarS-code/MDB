from mcp.server import MCPServer

from app.database import get_schema as fetch_schema
from app.vector_store import search_schema as semantic_search


mcp = MCPServer("MDB")


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

    for table_name, columns in schema.items():
        output.append(f"Table: {table_name}")

        for column in columns:
            output.append(
                f"  - {column['name']} ({column['type']})"
            )

        output.append("")

    return "\n".join(output)


@mcp.tool()
def search_schema(query: str) -> str:
    """Find database tables and columns relevant to a natural-language query."""

    results = semantic_search(query)

    if not results:
        return "No relevant schema found."

    output = []

    for result in results:
        output.append(
            f"Relevance: {result['score']:.4f}\n"
            f"{result['metadata']['document']}"
        )

    return "\n\n".join(output)


if __name__ == "__main__":
    mcp.run()