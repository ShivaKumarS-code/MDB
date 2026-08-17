from app.database import get_schema
from app.vector_store import index_schema


schema = get_schema()

count = index_schema(schema)

print(f"Indexed {count} tables.")