# SQL MCP Server (caller-provided T-SQL)

Executes caller-supplied SELECT T-SQL against Azure SQL (or Fabric SQL when configured). No internal SQL agent or LLM generation is used.

## What it does
- Tools exposed: `sql_query`, `list_tables`, `list_columns`, `get_schema`.
- Safety: SELECT-only; injects `TOP <limit>` when a limit is provided and query lacks TOP.
- Embedding warmup: preloads schema/value metadata from Cosmos and backfills embeddings via Azure OpenAI when enabled.
- Account resolver/value matching: uses cached Cosmos metadata; does not rewrite SQL.

## Run locally
```pwsh
cd agentic_framework
pip install -r requirements.txt
python mcps/sql/server.py    # http://localhost:8003/mcp
```
Dev mode: set `[framework].dev_mode = true` in `config.toml` to return dummy rows.

## Config highlights
- `config.toml` is the single config source (no .env needed).
- Azure SQL token auth via DefaultAzureCredential; scope `https://database.windows.net/.default`.
- Cosmos containers required: `prompts`, `agent_functions`, `sql_schema`, `table_metadata`, `value_mappings`.
- Embeddings: enabled/disabled via `[text_to_sql]` flags.

## Tool shapes (also in `scripts/assets/functions/tools/`)
- `sql_query`: `{ query (string, SELECT T-SQL), limit (int, optional), accounts_mentioned (array, optional), rbac_context (object, optional) }`
- `list_tables`: no parameters
- `list_columns`: `{ table: string }`
- `get_schema`: no parameters

## Cosmos sync
Upload prompts, tools, and schema JSON to Cosmos:
```pwsh
python scripts/test_env/upload_artifacts.py
```

## Quick smoke
```pwsh
python agentic_framework/mcp_test.py
```

## Troubleshooting
- If `sql_query` fails while `sys.tables` works: verify table/column names and Azure SQL permissions; errors surface retry root cause.
- Port busy: `Get-NetTCPConnection -LocalPort 8003 | Select OwningProcess` then `Stop-Process -Id <pid>`.
