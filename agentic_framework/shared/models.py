"""
Data models for the agentic framework.

This module defines Pydantic models for RBAC, MCP definitions, and other
shared data structures.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, Field


class Permission(str, Enum):
    """Permission enumeration."""
    
    READ_ACCOUNT = "read_account"
    WRITE_ACCOUNT = "write_account"
    READ_OPPORTUNITY = "read_opportunity"
    WRITE_OPPORTUNITY = "write_opportunity"
    READ_CONTRACT = "read_contract"
    WRITE_CONTRACT = "write_contract"
    ADMIN = "admin"
    VIEW_ANALYTICS = "view_analytics"
    EXPORT_DATA = "export_data"


class AccessScope(BaseModel):
    """Access scope for data filtering."""
    
    account_ids: Set[str] = Field(default_factory=set, description="Accessible account IDs")
    all_accounts: bool = Field(default=False, description="Access to all accounts")
    owned_only: bool = Field(default=False, description="Access only to owned records")
    team_access: bool = Field(default=False, description="Access to team records")
    
    def can_access_account(self, account_id: str) -> bool:
        """Check if scope allows access to an account."""
        return self.all_accounts or account_id in self.account_ids


class RBACContext(BaseModel):
    """Complete RBAC context for a user session."""
    
    user_id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    tenant_id: str = Field(..., description="Azure AD tenant ID")
    object_id: str = Field(..., description="Azure AD object ID")
    roles: List[str] = Field(default_factory=list, description="User role names")
    permissions: Set[Permission] = Field(default_factory=set, description="Effective permissions")
    access_scope: AccessScope = Field(default_factory=AccessScope, description="Data access scope")
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if user has specific permission."""
        return permission in self.permissions or Permission.ADMIN in self.permissions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for passing to MCPs."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "tenant_id": self.tenant_id,
            "object_id": self.object_id,
            "roles": self.roles,
            "access_scope": {
                "account_ids": list(self.access_scope.account_ids),
                "all_accounts": self.access_scope.all_accounts,
                "owned_only": self.access_scope.owned_only,
                "team_access": self.access_scope.team_access,
            }
        }


class MCPDefinition(BaseModel):
    """MCP server definition loaded from Cosmos DB."""
    
    id: str = Field(..., description="Unique MCP identifier")
    name: str = Field(..., description="MCP display name")
    description: str = Field(..., description="MCP description")
    endpoint: str = Field(..., description="MCP endpoint URL")
    transport: str = Field(default="http", description="Transport type (http, stdio)")
    
    allowed_roles: List[str] = Field(default_factory=list, description="Roles that can access this MCP")
    allowed_groups: List[str] = Field(default_factory=list, description="Groups that can access this MCP")
    
    tools: List[str] = Field(default_factory=list, description="Tool names available in this MCP")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    enabled: bool = Field(default=True, description="Whether MCP is enabled")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ToolDefinition(BaseModel):
    """Tool definition with schema."""
    
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tool parameter schema")
    mcp_id: str = Field(..., description="MCP that provides this tool")
    
    allowed_roles: List[str] = Field(default_factory=list, description="Roles that can use this tool")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class RBACConfig(BaseModel):
    """RBAC configuration for a role/group."""
    
    id: str = Field(..., description="Config ID (usually role/group name)")
    role_name: str = Field(..., description="Role name")
    mcp_access: List[str] = Field(default_factory=list, description="List of MCP IDs this role can access")
    tool_access: List[str] = Field(default_factory=list, description="List of tool names this role can access")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class Account(BaseModel):
    """Account model."""
    
    id: str
    name: str
    industry: Optional[str] = None
    revenue: Optional[float] = None
    employee_count: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
