import sqlite3

DB_PATH = "data/demo.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_schema():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
    """)

    tables = cursor.fetchall()
    schema = {}

    for (table_name,) in tables:
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        columns = cursor.fetchall()

        schema[table_name] = [
            {
                "name": column[1],
                "type": column[2],
            }
            for column in columns
        ]

    conn.close()

    return schema