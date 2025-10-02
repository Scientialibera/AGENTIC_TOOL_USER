"""
Minimal GraphService for agentic tests.

Provides a focused API:
 - `execute_query(query, rbac_context)` -> QueryResult (uses GremlinClient)
 - `extract_function_call(agent_message)` -> normalized function/tool call
 - `apply_rbac_where(query, rbac_context)` -> Gremlin filter string (or query unchanged)

This service intentionally avoids caching, enrichment, and dummy data.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog

from salesforce_mcp.clients.gremlin_client import GremlinClient
from shared.models.rbac import RBACContext
from shared.models.result import QueryResult, DataTable, DataColumn

logger = structlog.get_logger(__name__)


class GraphService:
    """Minimal graph service using GremlinClient for real queries."""

    def __init__(self, gremlin_client: GremlinClient, dev_mode: bool = False):
        self.gremlin_client = gremlin_client
        self.dev_mode = dev_mode

    def extract_function_call(self, agent_message: dict) -> Optional[Dict[str, Any]]:
        """
        Extract a function/tool call from agent message (new and legacy shapes).
        """
        if not isinstance(agent_message, dict):
            return None
        if agent_message.get("tool_calls"):
            calls = agent_message.get("tool_calls") or []
            return calls[0] if calls else None
        if agent_message.get("function_call"):
            return agent_message.get("function_call")
        if agent_message.get("choices"):
            try:
                msg = (agent_message.get("choices") or [{}])[0].get("message")
                if isinstance(msg, dict):
                    return self.extract_function_call(msg)
            except Exception:
                pass
        return None

    def apply_rbac_where(self, query: str, rbac_context: RBACContext) -> str:
        """
        For graph queries we translate RBAC to a vertex filter fragment.
        This is intentionally small: if permissions or roles exist we add a
        `.has('role', within([...]))` fragment to be inserted after a starting `g.V()`.
        If dev_mode is True we return the query unchanged.
        """
        if self.dev_mode or not rbac_context:
            return query

        perms = getattr(rbac_context, "permissions", None) or getattr(rbac_context, "roles", None) or []
        if isinstance(perms, (set, list, tuple)):
            perms_list = list(perms)
        else:
            perms_list = [str(perms)]

        if not perms_list:
            return query

        quoted = ", ".join(("'" + str(p).replace("'", "''") + "'") for p in perms_list)
        fragment = f".has('role', within({quoted}))"

        # Insert fragment after a leading g.V() if present
        if query.strip().startswith("g.V()"):
            return query.replace("g.V()", f"g.V(){fragment}", 1)
        # Otherwise, append fragment at the end (best-effort)
        return query + fragment

    async def execute_query(self, query: str, rbac_context: RBACContext, bindings: Optional[Dict[str, Any]] = None) -> QueryResult:
        """Execute a Gremlin query and return a QueryResult with a DataTable."""
        try:
            # Apply RBAC unless dev_mode
            gremlin = query
            if not self.dev_mode and rbac_context:
                try:
                    gremlin = self.apply_rbac_where(query, rbac_context)
                except Exception:
                    gremlin = query

            start = datetime.utcnow()
            raw = await self.gremlin_client.execute_query(gremlin, bindings)

            # Normalize raw results to rows (list[dict])
            rows: List[Dict[str, Any]] = []
            if raw:
                for r in raw:
                    if isinstance(r, dict):
                        rows.append(r)
                    else:
                        # Try to extract common attributes
                        row = {}
                        if hasattr(r, "id"):
                            row["id"] = getattr(r, "id")
                        if hasattr(r, "label"):
                            row["label"] = getattr(r, "label")
                        props = getattr(r, "properties", None)
                        if isinstance(props, dict):
                            # flatten first-level properties
                            for k, v in props.items():
                                row[k] = v
                        rows.append(row)

            # Build DataTable
            if rows:
                columns = list(rows[0].keys())
                table_columns = [DataColumn(name=c, data_type=("number" if isinstance(rows[0][c], (int, float)) else "string")) for c in columns]
            else:
                columns = []
                table_columns = []

            data_table = DataTable(
                name="graph_result",
                columns=table_columns,
                rows=rows,
                row_count=len(rows),
                source="gremlin",
                query=gremlin,
            )

            elapsed = int((datetime.utcnow() - start).total_seconds() * 1000)
            return QueryResult(success=True, data=data_table, error=None, query=gremlin, execution_time_ms=elapsed, row_count=len(rows))

        except Exception as e:
            logger.error("Graph execute failed", error=str(e), query=query)
            return QueryResult(success=False, data=None, error=str(e), query=query, execution_time_ms=0, row_count=0)
