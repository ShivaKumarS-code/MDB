import os

from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from app.embeddings import embed_document, embed_query

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


def build_document(table_name, columns):
    column_text = "\n".join(
        f"- {column['name']}: {column['type']}"
        for column in columns
    )

    return f"""
Table: {table_name}

Columns:
{column_text}
""".strip()


def index_schema(schema):
    index = get_index()

    vectors = []

    for table_name, columns in schema.items():
        document = build_document(table_name, columns)

        embedding = embed_document(document)

        vectors.append({
            "id": f"table:{table_name}",
            "values": embedding,
            "metadata": {
                "table": table_name,
                "document": document
            }
        })

    if vectors:
        index.upsert(vectors=vectors)

    return len(vectors)

def search_schema(query: str, top_k: int = 3):
    index = get_index()

    query_embedding = embed_query(query)

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True
    )

    return results.matches