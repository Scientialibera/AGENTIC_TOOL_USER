"""
Result models for agent responses and data aggregation.

This module defines models for agent execution results, data tables,
and unified response structures.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

from .message import Citation


class ResultType(str, Enum):
    """Result type enumeration."""
    
    TEXT = "text"
    TABLE = "table"
    GRAPH = "graph"
    DOCUMENT = "document"
    ERROR = "error"


class DataColumn(BaseModel):
    """Column definition for tabular data."""
    
    name: str = Field(..., description="Column name")
    data_type: str = Field(..., description="Data type (string, number, date, boolean)")
    display_name: Optional[str] = Field(default=None, description="Display name for UI")
    description: Optional[str] = Field(default=None, description="Column description")
    is_nullable: bool = Field(default=True, description="Whether column can be null")


class DataTable(BaseModel):
    """Structured table data with metadata."""
    
    name: str = Field(..., description="Table name")
    columns: List[DataColumn] = Field(..., description="Column definitions")
    rows: List[Dict[str, Any]] = Field(..., description="Table rows")
    
    # Metadata
    row_count: int = Field(..., description="Number of rows")
    source: str = Field(..., description="Data source (sql, api, etc)")
    query: Optional[str] = Field(default=None, description="Source query if applicable")
    
    # Display preferences
    display_limit: int = Field(default=100, description="Display limit for UI")
    is_truncated: bool = Field(default=False, description="Whether data is truncated")
    
    @classmethod
    def from_sql_result(
        cls,
        name: str,
        columns: List[str],
        rows: List[tuple],
        query: Optional[str] = None,
    ) -> "DataTable":
        """
        Create DataTable from SQL result.
        
        Args:
            name: Table name
            columns: Column names
            rows: Row tuples
            query: Original SQL query
            
        Returns:
            DataTable instance
        """
        # Convert tuples to dictionaries
        dict_rows = []
        for row in rows:
            dict_row = {}
            for i, value in enumerate(row):
                if i < len(columns):
                    dict_row[columns[i]] = value
            dict_rows.append(dict_row)
        
        # Create column definitions (infer types from data)
        table_columns = []
        for col_name in columns:
            # Simple type inference from first non-null value
            data_type = "string"  # Default
            for row in dict_rows:
                value = row.get(col_name)
                if value is not None:
                    if isinstance(value, (int, float)):
                        data_type = "number"
                    elif isinstance(value, bool):
                        data_type = "boolean"
                    elif isinstance(value, datetime):
                        data_type = "date"
                    break
            
            table_columns.append(DataColumn(
                name=col_name,
                data_type=data_type,
                display_name=col_name.replace("_", " ").title(),
            ))
        
        return cls(
            name=name,
            columns=table_columns,
            rows=dict_rows,
            row_count=len(dict_rows),
            source="sql",
            query=query,
        )


class GraphNode(BaseModel):
    """Graph node representation."""
    
    id: str = Field(..., description="Node ID")
    label: str = Field(..., description="Node label/type")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Node properties")
    display_name: Optional[str] = Field(default=None, description="Display name")


class GraphEdge(BaseModel):
    """Graph edge representation."""
    
    id: str = Field(..., description="Edge ID")
    source_id: str = Field(..., description="Source node ID")
    target_id: str = Field(..., description="Target node ID")
    label: str = Field(..., description="Edge label/type")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Edge properties")


class GraphData(BaseModel):
    """Graph data structure."""
    
    name: str = Field(..., description="Graph name")
    nodes: List[GraphNode] = Field(default_factory=list, description="Graph nodes")
    edges: List[GraphEdge] = Field(default_factory=list, description="Graph edges")
    
    # Metadata
    node_count: int = Field(default=0, description="Number of nodes")
    edge_count: int = Field(default=0, description="Number of edges")
    source: str = Field(default="gremlin", description="Data source")
    query: Optional[str] = Field(default=None, description="Source query if applicable")
    
    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph."""
        self.nodes.append(node)
        self.node_count = len(self.nodes)
    
    def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge to the graph."""
        self.edges.append(edge)
        self.edge_count = len(self.edges)


class AgentResult(BaseModel):
    """Result from individual agent execution."""
    
    agent_name: str = Field(..., description="Name of the agent")
    result_type: ResultType = Field(..., description="Type of result")
    
    # Data payload
    text_content: Optional[str] = Field(default=None, description="Text content")
    table_data: Optional[DataTable] = Field(default=None, description="Table data")
    graph_data: Optional[GraphData] = Field(default=None, description="Graph data")
    documents: List[Dict[str, Any]] = Field(default_factory=list, description="Document results")
    
    # Citations and sources
    citations: List[Citation] = Field(default_factory=list, description="Result citations")
    
    # Execution metadata
    execution_time_ms: int = Field(..., description="Execution time in milliseconds")
    tokens_used: Optional[int] = Field(default=None, description="Tokens used")
    confidence: Optional[float] = Field(default=None, description="Confidence score")
    
    # Error handling
    success: bool = Field(default=True, description="Whether execution succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    
    def add_citation(self, citation: Citation) -> None:
        """Add a citation to the result."""
        self.citations.append(citation)


class AggregatedResult(BaseModel):
    """Aggregated result from multiple agents."""
    
    query: str = Field(..., description="Original user query")
    plan_id: str = Field(..., description="Plan ID that generated this result")
    
    # Agent results
    agent_results: List[AgentResult] = Field(default_factory=list, description="Individual agent results")
    
    # Synthesized response
    final_answer: str = Field(..., description="Final synthesized answer")
    summary: Optional[str] = Field(default=None, description="Result summary")
    
    # All data
    all_tables: List[DataTable] = Field(default_factory=list, description="All table results")
    all_graphs: List[GraphData] = Field(default_factory=list, description="All graph results")
    all_citations: List[Citation] = Field(default_factory=list, description="All citations")
    
    # Metadata
    total_execution_time_ms: int = Field(..., description="Total execution time")
    total_tokens_used: int = Field(default=0, description="Total tokens used")
    agents_used: List[str] = Field(default_factory=list, description="Names of agents used")
    
    # Quality metrics
    confidence: float = Field(..., description="Overall confidence score")
    completeness: float = Field(default=1.0, description="Completeness score")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Result creation time")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    def add_agent_result(self, result: AgentResult) -> None:
        """Add an agent result to the aggregation."""
        self.agent_results.append(result)
        self.agents_used.append(result.agent_name)
        
        # Aggregate data
        if result.table_data:
            self.all_tables.append(result.table_data)
        if result.graph_data:
            self.all_graphs.append(result.graph_data)
        self.all_citations.extend(result.citations)
        
        # Update totals
        self.total_execution_time_ms += result.execution_time_ms
        if result.tokens_used:
            self.total_tokens_used += result.tokens_used
    
    @property
    def has_data(self) -> bool:
        """Check if result has any data."""
        return len(self.all_tables) > 0 or len(self.all_graphs) > 0 or len(self.all_citations) > 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate of agent executions."""
        if not self.agent_results:
            return 0.0
        
        successful = sum(1 for result in self.agent_results if result.success)
        return successful / len(self.agent_results)


class ToolDefinition(BaseModel):
    """Tool/function definition for agent capabilities."""
    
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tool parameters schema")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class QueryResult(BaseModel):
    """Result from a database query execution."""
    
    success: bool = Field(..., description="Whether query executed successfully")
    data: Optional[DataTable] = Field(default=None, description="Query result data")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    query: str = Field(..., description="Original SQL query")
    execution_time_ms: Optional[int] = Field(default=None, description="Query execution time in milliseconds")
    row_count: int = Field(default=0, description="Number of rows returned")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class FeedbackData(BaseModel):
    """User feedback on results."""
    
    result_id: str = Field(..., description="Result ID being rated")
    user_id: str = Field(..., description="User providing feedback")
    chat_id: str = Field(..., description="Chat session ID")
    
    # Feedback
    rating: int = Field(..., description="Rating (1-5 or thumbs up/down)")
    comment: Optional[str] = Field(default=None, description="Optional feedback comment")
    
    # Context
    query: str = Field(..., description="Original query")
    response_summary: str = Field(..., description="Summary of the response")
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Feedback timestamp")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
