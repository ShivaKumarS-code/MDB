import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect

load_dotenv()

_engine = None


def get_engine():
    """Create and cache a SQLAlchemy engine from DATABASE_URL."""
    global _engine

    if _engine is None:
        url = os.getenv("DATABASE_URL")

        if not url:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Set it in .env, e.g.: "
                "DATABASE_URL=postgresql://user:pass@host:5432/dbname"
            )

        _engine = create_engine(url)

    return _engine


def get_schema() -> dict:
    """Introspect the PostgreSQL database and return the full schema.

    Returns a dict keyed by table name, each containing:
        - columns: list of column dicts (name, type, nullable, default, primary_key)
        - relationships: list of foreign-key dicts (column, references_table, references_column)
    """
    engine = get_engine()
    inspector = inspect(engine)
    pg_schema = os.getenv("DATABASE_SCHEMA", "public")

    tables = inspector.get_table_names(schema=pg_schema)
    schema = {}

    for table_name in sorted(tables):
        columns = inspector.get_columns(table_name, schema=pg_schema)

        pk_constraint = inspector.get_pk_constraint(
            table_name, schema=pg_schema
        )
        pk_columns = set(pk_constraint.get("constrained_columns", []))

        foreign_keys = inspector.get_foreign_keys(
            table_name, schema=pg_schema
        )

        schema[table_name] = {
            "columns": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": (
                        str(col["default"]) if col.get("default") else None
                    ),
                    "primary_key": col["name"] in pk_columns,
                }
                for col in columns
            ],
            "relationships": [
                {
                    "column": fk["constrained_columns"][0],
                    "references_table": fk["referred_table"],
                    "references_column": fk["referred_columns"][0],
                }
                for fk in foreign_keys
                if fk.get("constrained_columns")
                and fk.get("referred_columns")
            ],
        }

    return schema