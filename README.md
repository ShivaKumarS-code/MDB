# MDB — Model Data Bridge

MDB is an MCP server that provides AI assistants with semantic access to your PostgreSQL database schema. It combines PostgreSQL introspection, Gemini embeddings, and ChromaDB vector search to enable natural-language schema discovery.

## Architecture

<img src="assets/mdb-architecture.png" width="600" alt="MDB Architecture" />



## Prerequisites

- Python 3.11+
- A PostgreSQL database
- A [Gemini API key](https://ai.google.dev/)

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd MDB

python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/your_database
GEMINI_API_KEY=your_gemini_api_key
```

Optional settings:

```env
# PostgreSQL schema to introspect (default: public)
DATABASE_SCHEMA=public

# ChromaDB data storage path (default: ./chroma_data)
CHROMA_DATA_DIR=./chroma_data

# MDB server host and port (defaults: 0.0.0.0 / 8000)
MDB_HOST=0.0.0.0
MDB_PORT=8000
```

### 3. Sync the schema into ChromaDB

Schema syncing is on-demand via the `resync_schema` MCP tool, not scheduled automatically. The first invocation indexes all tables into ChromaDB; subsequent calls only re-embed tables whose structure has changed since the last sync.

You can trigger it from any MCP client (e.g. MCP Inspector) or programmatically via the MCP endpoint.

### 4. Run the MCP server

```bash
python -m app.server
```

This starts the MCP server with Streamable HTTP transport:

```
Starting MDB on 0.0.0.0:8000
  MCP endpoint: http://0.0.0.0:8000/mcp
  Health check: http://0.0.0.0:8000/health
```

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | MCP Streamable HTTP endpoint (for MCP clients) |
| `/health` | GET | Health check — returns `{"status": "healthy", "service": "MDB"}` |

To change the port:

```bash
# Via environment variable
MDB_PORT=9000 python -m app.server

# Or set MDB_PORT=9000 in .env
```

### 5. Connect MCP Inspector

1. Open [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
2. Set the transport type to **Streamable HTTP**
3. Enter the URL: `http://localhost:8000/mcp`
4. Connect and verify all tools:
   - `ping()` → `"MDB is alive!"`
   - `get_schema()` → full database schema
   - `search_schema(query)` → semantically relevant tables
   - `get_table_context(table_name)` → detailed table context
   - `resync_schema()` → sync database schema with ChromaDB

## MCP Tools

| Tool | Description |
|------|-------------|
| `ping()` | Health check — returns `"MDB is alive!"` |
| `get_schema()` | Returns the complete database schema with columns, types, PKs, and FKs |
| `search_schema(query)` | Semantic search — finds tables relevant to a natural-language query, then expands through foreign-key relationships |
| `get_table_context(table_name)` | Returns detailed context for a specific table including columns, types, constraints, and relationships |
| `resync_schema()` | Incrementally syncs the local ChromaDB vector store with the current database schema — adds new tables, re-embeds changed tables, removes stale vectors |

## Project Structure

```
MDB/
├── app/
│   ├── database.py        # PostgreSQL introspection via SQLAlchemy
│   ├── embeddings.py      # Gemini embedding generation
│   ├── server.py          # MCP server (Streamable HTTP) with tool definitions
│   └── vector_store.py    # ChromaDB indexing and semantic search
├── assets/
│   └── mdb-architecture.png
├── .env.example           # Environment variable template
├── .gitignore
└── requirements.txt       # Python dependencies
```

## Deployment

MDB follows the standard MCP deployment model: **self-hosted, one instance per user**. Each user runs their own MDB server (locally, in Docker, or on their own infrastructure) with their own `.env` containing their database credentials and API keys.

This means:

- **Credentials stay on the user's machine** — no database URLs or API keys are sent to a third party.
- **Vectors stay local** — stored securely on disk via ChromaDB.
- **Each instance connects to one database** — configured via `DATABASE_URL` in `.env`.
- **The MCP client points to the user's server** — e.g. `http://localhost:8000/mcp` in Claude Desktop, Cursor, or any MCP-compatible client.
- **Schema syncing is on-demand** via the `resync_schema` MCP tool, not scheduled automatically.

### Docker (example)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "app.server"]
```

```bash
docker build -t mdb .
docker run -p 8000:8000 --env-file .env mdb
```
