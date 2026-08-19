import hashlib
import json
import os

import chromadb
from dotenv import load_dotenv

from app.database import get_schema
from app.embeddings import embed_document, embed_query

load_dotenv()

DATA_DIR = os.getenv("CHROMA_DATA_DIR", "./chroma_data")
_chroma_client = None


def get_collection():
    global _chroma_client

    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=DATA_DIR)

    return _chroma_client.get_or_create_collection(
        name="mdb-schema",
        metadata={"hnsw:space": "cosine"},
    )


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
    the ChromaDB collection.
    """
    collection = get_collection()
    data = collection.get(include=["metadatas"])

    if not data or not data.get("ids"):
        return {}

    hashes = {}
    for vector_id, metadata in zip(data["ids"], data["metadatas"]):
        table_name = vector_id.removeprefix("table:")
        if metadata and "schema_hash" in metadata:
            hashes[table_name] = metadata["schema_hash"]
    return hashes


def sync_schema() -> dict:
    """Reconciles the ChromaDB collection with the live database schema.
    Only embeds new or changed tables; skips unchanged ones; removes
    vectors for tables that no longer exist in the database.
    """
    collection = get_collection()
    schema = get_schema()
    stored_hashes = get_indexed_table_hashes()

    live_table_names = set(schema.keys())
    stored_table_names = set(stored_hashes.keys())

    ids_to_upsert = []
    embeddings_to_upsert = []
    metadatas_to_upsert = []
    documents_to_upsert = []

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

        ids_to_upsert.append(f"table:{table_name}")
        embeddings_to_upsert.append(embedding)
        metadatas_to_upsert.append({
            "table": table_name,
            "schema_hash": current_hash,
        })
        documents_to_upsert.append(document)

    if ids_to_upsert:
        collection.upsert(
            ids=ids_to_upsert,
            embeddings=embeddings_to_upsert,
            metadatas=metadatas_to_upsert,
            documents=documents_to_upsert,
        )

    stale_tables = stored_table_names - live_table_names
    if stale_tables:
        collection.delete(ids=[f"table:{name}" for name in stale_tables])

    return {
        "added": added,
        "updated": updated,
        "removed": len(stale_tables),
        "unchanged": unchanged,
    }


def search_schema(query: str, top_k: int = 3):
    """Semantic search for relevant schema documents.

    Retrieves the top-k most relevant tables via ChromaDB,
    then expands through foreign-key relationships to include
    connected tables in the result.

    Returns a list of schema document strings.
    """
    collection = get_collection()
    query_embedding = embed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["metadatas"],
    )

    metadatas = results.get("metadatas", [[]])[0]

    # Tables found through semantic search
    selected_tables = {
        meta["table"]
        for meta in metadatas
        if meta and "table" in meta
    }

    # Expand through relationships
    schema = get_schema()

    for table_name in list(selected_tables):
        table = schema.get(table_name)

        if not table:
            continue

        for relationship in table["relationships"]:
            selected_tables.add(relationship["references_table"])

    # Build final context
    context = []

    for table_name in selected_tables:
        table_data = schema.get(table_name)

        if not table_data:
            continue

        context.append(build_document(table_name, table_data))

    return context