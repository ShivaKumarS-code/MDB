import hashlib
import json
import os

from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec

from app.embeddings import embed_document, embed_query
from app.database import get_schema

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "mdb-schema")
DIMENSION = 768


def get_index():
    if not pc.has_index(INDEX_NAME):
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud="aws",
                region="us-east-1"
            )
        )

    return pc.Index(INDEX_NAME)


def build_document(table_name, table_data):
    """Build a schema document for a single table.

    Uses structural metadata discovered from PostgreSQL:
    column names, types, primary keys, nullability, and foreign keys.
    """
    columns = table_data["columns"]
    relationships = table_data["relationships"]

    column_text = []

    for column in columns:
        pk_marker = " [PK]" if column.get("primary_key") else ""
        nullable_marker = " (nullable)" if column.get("nullable") else ""

        column_text.append(
            f"- {column['name']}: {column['type']}{pk_marker}{nullable_marker}"
        )

    relationship_text = "\n".join(
        f"- {relationship['column']} references "
        f"{relationship['references_table']}."
        f"{relationship['references_column']}"
        for relationship in relationships
    )

    if not relationship_text:
        relationship_text = "None"

    return f"""
Table: {table_name}

Columns:
{chr(10).join(column_text)}

Relationships:
{relationship_text}
""".strip()


def compute_table_hash(table_name: str, table_data: dict) -> str:
    """Deterministic hash of a table's structure, used to detect schema
    changes without re-embedding unchanged tables.
    """
    columns = sorted(
        (
            {
                "name": col["name"],
                "type": col["type"],
                "nullable": col.get("nullable"),
            }
            for col in table_data["columns"]
        ),
        key=lambda c: c["name"],
    )

    relationships = sorted(
        (
            {
                "column": rel["column"],
                "references_table": rel["references_table"],
                "references_column": rel["references_column"],
            }
            for rel in table_data.get("relationships", [])
        ),
        key=lambda r: r["column"],
    )

    canonical = json.dumps(
        {"table": table_name, "columns": columns, "relationships": relationships},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_indexed_table_hashes() -> dict[str, str]:
    """Returns {table_name: schema_hash} for every vector currently in
    the Pinecone index. index.list() is a paginated generator -- iterate
    it fully rather than assuming a single page.
    """
    index = get_index()

    ids = [
        item.id
        for page in index.list()
        for item in page.vectors
    ]
    if not ids:
        return {}

    fetch_result = index.fetch(ids=ids)

    hashes = {}
    for vector_id, vector in fetch_result.vectors.items():
        table_name = vector_id.removeprefix("table:")
        schema_hash = vector.metadata.get("schema_hash")
        if schema_hash:
            hashes[table_name] = schema_hash
    return hashes


def sync_schema() -> dict:
    """Reconciles the Pinecone index with the live database schema.
    Only embeds new or changed tables; skips unchanged ones; removes
    vectors for tables that no longer exist in the database.
    """
    index = get_index()
    schema = get_schema()
    stored_hashes = get_indexed_table_hashes()

    live_table_names = set(schema.keys())
    stored_table_names = set(stored_hashes.keys())

    to_upsert = []
    added = 0
    updated = 0
    unchanged = 0

    for table_name, table_data in schema.items():
        current_hash = compute_table_hash(table_name, table_data)
        stored_hash = stored_hashes.get(table_name)

        if stored_hash is None:
            added += 1
        elif stored_hash != current_hash:
            updated += 1
        else:
            unchanged += 1
            continue  # no change, skip embedding

        document = build_document(table_name, table_data)
        embedding = embed_document(document)
        to_upsert.append({
            "id": f"table:{table_name}",
            "values": embedding,
            "metadata": {
                "table": table_name,
                "document": document,
                "schema_hash": current_hash,
            },
        })

    if to_upsert:
        index.upsert(vectors=to_upsert)

    stale_tables = stored_table_names - live_table_names
    if stale_tables:
        index.delete(ids=[f"table:{name}" for name in stale_tables])

    return {
        "added": added,
        "updated": updated,
        "removed": len(stale_tables),
        "unchanged": unchanged,
    }


def search_schema(query: str, top_k: int = 3):
    """Semantic search for relevant schema documents.

    Retrieves the top-k most relevant tables via Pinecone,
    then expands through foreign-key relationships to include
    connected tables in the result.

    Returns a list of schema document strings.
    """
    index = get_index()

    query_embedding = embed_query(query)

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True
    )

    matches = results.matches

    # Tables found through semantic search
    selected_tables = {
        match["metadata"]["table"]
        for match in matches
    }

    # Expand through relationships
    schema = get_schema()

    for table_name in list(selected_tables):
        table = schema.get(table_name)

        if not table:
            continue

        for relationship in table["relationships"]:
            selected_tables.add(
                relationship["references_table"]
            )

    # Build final context
    context = []

    for table_name in selected_tables:
        table_data = schema.get(table_name)

        if not table_data:
            continue

        context.append(
            build_document(table_name, table_data)
        )

    return context