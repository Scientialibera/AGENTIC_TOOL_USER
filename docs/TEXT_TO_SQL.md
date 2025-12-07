# Text-to-SQL Enhancements

This document describes the advanced text-to-SQL capabilities added to the SQL MCP server, inspired by production semantic layer systems like Cube.dev and Wren AI.

## Overview

The enhanced text-to-SQL system goes beyond simple "schema in a prompt" approaches by:

1. **Schema Discovery & Metadata**: Introspects database schema including tables, columns, relationships, and descriptions
2. **Embedding-Based Table Selection**: Uses vector search to find relevant tables/columns for a question
3. **Structured Query Planning**: LLM generates a QueryPlan instead of raw SQL
4. **Low-Cardinality Value Matching**: Automatically normalizes filter values (e.g., "UK" → "United Kingdom")
5. **RBAC Integration**: Applies row-level security filters automatically

## Architecture

### Flow Diagram

```
User Question
    ↓
search_schema (vector search for relevant tables)
    ↓
plan_sql (LLM generates QueryPlan)
    ↓
query_sql_from_plan (normalize values + apply RBAC + execute)
    ↓
Results
```

### Components

1. **SqlClient** (`shared/sql_client.py`)
   - Unified client for Fabric SQL and Azure SQL
   - Schema introspection (tables, columns, foreign keys, extended properties)
   - Cardinality detection for dimension columns

2. **Schema Metadata** (Cosmos DB `schema_metadata` container)
   - Table metadata with descriptions and embeddings
   - Column metadata for low-cardinality columns with distinct values
   - Relationship information (foreign keys)

3. **MCP Tools** (`mcps/sql/server.py`)
   - `discover_schema`: Introspect database and store metadata
   - `search_schema`: Find relevant tables using embeddings
   - `plan_sql`: Generate structured QueryPlan
   - `query_sql_from_plan`: Execute plan with value normalization

## Configuration

### Environment Variables

```bash
# RBAC Configuration
RBAC_ENABLED=true
RBAC_MODE=cosmos  # cosmos, sql, or off

# Unified SQL Configuration
SQL_ENGINE_TYPE=fabric  # fabric or azure_sql
SQL_ENDPOINT=your-server.database.windows.net
SQL_DATABASE=your_database
SQL_CONNECTION_TIMEOUT=30

# Cosmos DB for schema metadata
COSMOS_SCHEMA_METADATA_CONTAINER=schema_metadata
```

### Backward Compatibility

The system maintains backward compatibility with existing `FABRIC_SQL_*` environment variables. If `SQL_*` variables are not set, the system will use `FABRIC_SQL_*` values.

## Usage

### 1. Initial Schema Discovery

Run once or whenever schema changes:

```python
# Via MCP tool
result = await sql_mcp.discover_schema()

# Returns:
{
  "success": true,
  "tables_discovered": 25,
  "columns_discovered": 450,
  "low_cardinality_columns": 15,
  "relationships": 30
}
```

This will:
- Query `INFORMATION_SCHEMA` for tables and columns
- Retrieve foreign key relationships from `sys.foreign_keys`
- Read extended properties (`MS_Description`) for descriptions
- Detect low-cardinality columns (<=200 distinct values)
- Store distinct values and embeddings for low-cardinality columns
- Generate and store embeddings for each table's schema

### 2. Schema Search (Optional)

Find relevant tables for a question:

```python
result = await sql_mcp.search_schema(
    question="Show me revenue by country for the last 3 months",
    top_k=3
)

# Returns:
{
  "success": true,
  "relevant_tables": ["dbo.sales", "dbo.customers", "dbo.countries"],
  "schema": "Table: dbo.sales\nColumns: id, customer_id, amount, date...",
  "top_k": 3
}
```

### 3. Query Planning

Generate a structured query plan:

```python
result = await sql_mcp.plan_sql(
    question="Show me revenue by country for UK and France",
    candidate_schema=search_result["schema"]  # Optional
)

# Returns:
{
  "success": true,
  "plan": {
    "tables": ["dbo.sales"],
    "select_fields": ["country", "SUM(amount)"],
    "filters": [
      {"table": "dbo.sales", "column": "country", "operator": "IN", "value": ["UK", "France"]}
    ],
    "group_by": ["country"],
    "order_by": [{"field": "SUM(amount)", "direction": "DESC"}],
    "limit": 100
  }
}
```

### 4. Query Execution with Value Normalization

Execute the plan with automatic value normalization:

```python
result = await sql_mcp.query_sql_from_plan(
    plan=plan_result["plan"],
    rbac_context={"email": "user@example.com", "roles": ["sales_rep"]}
)

# The system will:
# 1. Look up "UK" and "France" in low-cardinality metadata for "country" column
# 2. Normalize "UK" → "United Kingdom" using semantic matching
# 3. Apply RBAC filters (e.g., WHERE owner_email = 'user@example.com')
# 4. Generate safe parameterized SQL
# 5. Execute and return results

# Returns:
{
  "success": true,
  "query": "SELECT country, SUM(amount) FROM dbo.sales WHERE country IN (?, ?) AND owner_email = ? GROUP BY country",
  "row_count": 2,
  "data": [
    {"country": "United Kingdom", "total": 1500000},
    {"country": "France", "total": 1200000}
  ],
  "source": "sql_from_plan"
}
```

## Low-Cardinality Value Matching

The system uses a two-tier approach for normalizing filter values:

### 1. Exact Matching
- Case-insensitive string comparison
- Example: "united kingdom" matches "United Kingdom"

### 2. Semantic Matching (if no exact match)
- Generate embedding for user's input value
- Compare with embeddings of all distinct values
- Use best match if cosine similarity > 0.8
- Example: "UK" → "United Kingdom" (similarity: 0.92)

### Configuration

Low-cardinality threshold is set to 200 distinct values by default. Columns with more than 200 distinct values are not indexed for value matching.

To adjust:

```python
cardinality_info = await sql_client.get_column_cardinality(
    schema="dbo",
    table="customers",
    column="country",
    max_distinct=500  # Custom threshold
)
```

## RBAC Integration

When `RBAC_ENABLED=true`, the system automatically:

1. **Tool-Level Access Control**: Only expose tools to authorized roles
2. **Row-Level Security**: Inject WHERE clauses based on user context

Example:

```python
rbac_context = {
    "email": "john@example.com",
    "roles": ["sales_rep"],
    "access_scope": {
        "account_ids": ["acc_123", "acc_456"],
        "owned_only": true
    }
}

# Automatically adds to SQL:
# WHERE (owner_email = 'john@example.com' OR assigned_to = 'john@example.com')
```

## Schema Descriptions

### Storing Descriptions

Descriptions can be stored in two places:

#### 1. SQL Extended Properties (Recommended for technical descriptions)

```sql
-- Add table description
EXEC sp_addextendedproperty 
    @name = N'MS_Description',
    @value = N'Customer master data including company information',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE', @level1name = N'customers';

-- Add column description
EXEC sp_addextendedproperty 
    @name = N'MS_Description',
    @value = N'ISO 3166-1 alpha-2 country code',
    @level0type = N'SCHEMA', @level0name = N'dbo',
    @level1type = N'TABLE', @level1name = N'customers',
    @level2type = N'COLUMN', @level2name = N'country_code';
```

#### 2. Cosmos DB Metadata (Recommended for business semantics)

Manually add business context to schema metadata:

```json
{
  "id": "table:dbo.sales",
  "kind": "table",
  "schema_name": "dbo",
  "table_name": "sales",
  "description": "Sales transactions. Use this for revenue analysis.",
  "tags": ["revenue", "sales", "transactions", "ecommerce"],
  "metadata": {
    "business_owner": "Sales Team",
    "refresh_frequency": "daily",
    "data_classification": "confidential"
  }
}
```

## Models

### QueryPlan

```python
class QueryPlan(BaseModel):
    tables: List[str]
    select_fields: List[str]
    aggregations: List[Dict[str, str]]  # [{"function": "SUM", "field": "amount", "alias": "total"}]
    filters: List[FilterCondition]
    joins: List[Dict[str, str]]
    group_by: List[str]
    order_by: List[Dict[str, str]]  # [{"field": "amount", "direction": "DESC"}]
    limit: Optional[int]
```

### FilterCondition

```python
class FilterCondition(BaseModel):
    table: str
    column: str
    operator: str  # =, !=, >, <, >=, <=, IN, LIKE, etc.
    value: Any  # Will be normalized for low-cardinality columns
```

### SchemaMetadata

```python
class SchemaMetadata(BaseModel):
    id: str  # e.g., "table:dbo.sales" or "column:dbo.sales.country"
    kind: str  # "table", "column", or "relationship"
    schema_name: Optional[str]
    table_name: Optional[str]
    column_name: Optional[str]
    description: Optional[str]
    data_type: Optional[str]
    is_nullable: Optional[bool]
    is_low_cardinality: Optional[bool]
    distinct_values: List[str]
    relationships: List[Dict[str, str]]
    tags: List[str]
    embedding: Optional[List[float]]
    metadata: Dict[str, Any]
```

## Best Practices

### 1. Schema Discovery
- Run `discover_schema` during deployment or on a schedule (e.g., nightly)
- Re-run after schema changes
- Monitor execution time for large databases (may need incremental updates)

### 2. Embeddings
- Use consistent embedding model across all operations
- Store embeddings in Cosmos DB for fast retrieval
- For production, use Azure AI Search for vector search instead of in-memory

### 3. Value Normalization
- Only index low-cardinality columns (< 200 distinct values)
- Review normalized values in logs to ensure accuracy
- Add manual mappings for critical dimensions if needed

### 4. RBAC
- Always pass `rbac_context` when executing queries
- Test RBAC filters thoroughly
- Use `RBAC_MODE=off` for development, `cosmos` for production

### 5. Performance
- Cache schema metadata locally when possible
- Use `search_schema` with appropriate `top_k` values (3-5 tables)
- Set reasonable `limit` values in QueryPlan

## Troubleshooting

### No schema metadata found

**Problem**: `search_schema` returns "No schema metadata found"

**Solution**: Run `discover_schema` first to populate metadata

### Value normalization not working

**Problem**: Filter values not being normalized (e.g., "UK" stays as "UK")

**Solution**: 
1. Check if column is detected as low-cardinality
2. Verify embeddings were generated during `discover_schema`
3. Check similarity threshold (default 0.8)
4. Review logs for normalization attempts

### RBAC filters not applied

**Problem**: Users see data they shouldn't have access to

**Solution**:
1. Verify `RBAC_ENABLED=true`
2. Ensure `rbac_context` is passed to `query_sql_from_plan`
3. Check RBAC configuration in Cosmos DB
4. Review generated SQL in logs

### Slow query planning

**Problem**: `plan_sql` takes too long

**Solution**:
1. Use `search_schema` to pre-filter tables
2. Reduce `top_k` in schema search
3. Cache frequently used schema slices
4. Consider using smaller embedding model

## Comparison with Other Systems

### Cube.dev
- **Similar**: Semantic layer, metrics definitions, structured queries
- **Different**: We use MCP protocol, focus on Azure/Fabric

### Wren AI
- **Similar**: Natural language to SQL, semantic search over schema
- **Different**: We integrate with Microsoft Agent Framework

### MotherDuck/DuckDB
- **Similar**: Extended properties for descriptions, semantic metadata
- **Different**: We support Fabric SQL and Azure SQL

## Future Enhancements

1. **Incremental Schema Discovery**: Only update changed tables
2. **Azure AI Search Integration**: Replace in-memory vector search
3. **Metric Definitions**: Pre-defined business metrics (like Cube)
4. **Query Caching**: Cache common query patterns
5. **Multi-Table Joins**: Automatic join path discovery
6. **SQL Dialect Support**: Support more SQL engines (PostgreSQL, MySQL)
7. **Natural Language Explanations**: Generate explanations for results

## References

- [Cube.dev Semantic Layer](https://cube.dev/)
- [Wren AI Text-to-SQL](https://github.com/Canner/WrenAI)
- [MotherDuck Semantic Catalog](https://motherduck.com/blog/semantic-catalog-for-ai-agents/)
- [Microsoft Fabric SQL](https://learn.microsoft.com/en-us/fabric/data-warehouse/)
- [Azure SQL Extended Properties](https://learn.microsoft.com/en-us/sql/relational-databases/system-stored-procedures/sp-addextendedproperty-transact-sql)
