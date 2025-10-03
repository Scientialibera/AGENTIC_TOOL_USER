# SQL Schema Definitions

This directory contains SQL schema metadata files that are uploaded to the `sql_schema` Cosmos DB container.

## Purpose

The SQL MCP server ([agentic_framework/mcps/sql/server.py](../../../agentic_framework/mcps/sql/server.py)) uses these schema definitions to:
- Generate accurate SQL queries from natural language
- Provide table and column information to the LLM
- Validate queries against the actual database structure

## File Format

Each JSON file should contain an array of table definitions:

```json
[
  {
    "id": "unique_table_id",
    "table_name": "ActualTableName",
    "description": "Description of what this table contains",
    "columns": [
      "Column1",
      "Column2",
      "Column3"
    ],
    "partition_key": "PartitionKeyColumn"
  }
]
```

## Usage

Schema files are automatically uploaded when running:

```bash
python scripts/test_env/init_data.py
```

The script will:
1. Create the `sql_schema` container in Cosmos DB (if it doesn't exist)
2. Upload all `.json` files from this directory
3. Each table definition becomes a separate document in the container

## Example Files

- **salesforce_schema.json** - Sample Salesforce object schemas (Account, Contact, Opportunity, Case, Lead)

## Adding New Schemas

To add new database schemas:

1. Create a new `.json` file in this directory
2. Follow the format above
3. Run `python scripts/test_env/init_data.py` to upload

The SQL MCP server will automatically load all schema definitions from the `sql_schema` container when generating queries.
