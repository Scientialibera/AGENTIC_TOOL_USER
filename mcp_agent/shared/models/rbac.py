"""
RBAC (Role-Based Access Control) models for authorization.

This module defines models for user roles, permissions, and access control
contexts used throughout the application.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, Field


class Permission(str, Enum):
    """Permission enumeration."""
    
    # Account permissions
    READ_ACCOUNT = "read_account"
    WRITE_ACCOUNT = "write_account"
    DELETE_ACCOUNT = "delete_account"
    
    # Opportunity permissions
    READ_OPPORTUNITY = "read_opportunity"
    WRITE_OPPORTUNITY = "write_opportunity"
    DELETE_OPPORTUNITY = "delete_opportunity"
    
    # Task permissions
    READ_TASK = "read_task"
    WRITE_TASK = "write_task"
    DELETE_TASK = "delete_task"
    
    # Contract permissions
    READ_CONTRACT = "read_contract"
    WRITE_CONTRACT = "write_contract"
    DELETE_CONTRACT = "delete_contract"
    
    # System permissions
    ADMIN = "admin"
    MANAGE_USERS = "manage_users"
    VIEW_ANALYTICS = "view_analytics"
    EXPORT_DATA = "export_data"


class Role(BaseModel):
    """Role definition with permissions."""
    
    name: str = Field(..., description="Role name")
    display_name: str = Field(..., description="Display name for UI")
    description: str = Field(..., description="Role description")
    permissions: List[Permission] = Field(default_factory=list, description="Role permissions")
    is_active: bool = Field(default=True, description="Whether role is active")
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if role has a specific permission."""
        return permission in self.permissions or Permission.ADMIN in self.permissions


class AccessScope(BaseModel):
    """Access scope for data filtering."""
    
    # Account-level access
    account_ids: Set[str] = Field(default_factory=set, description="Accessible account IDs")
    all_accounts: bool = Field(default=False, description="Access to all accounts")
    
    # Owner-based access
    owned_only: bool = Field(default=False, description="Access only to owned records")
    team_access: bool = Field(default=False, description="Access to team records")
    
    # Time-based access
    date_range_start: Optional[datetime] = Field(default=None, description="Start date for access")
    date_range_end: Optional[datetime] = Field(default=None, description="End date for access")
    
    def can_access_account(self, account_id: str) -> bool:
        """Check if scope allows access to an account."""
        return self.all_accounts or account_id in self.account_ids
    
    def add_account(self, account_id: str) -> None:
        """Add an account to the access scope."""
        self.account_ids.add(account_id)
    
    def remove_account(self, account_id: str) -> None:
        """Remove an account from the access scope."""
        self.account_ids.discard(account_id)


class RBACContext(BaseModel):
    """Complete RBAC context for a user session."""
    
    # User identification
    user_id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    tenant_id: str = Field(..., description="Azure AD tenant ID")
    object_id: str = Field(..., description="Azure AD object ID")
    
    # Roles and permissions
    roles: List[str] = Field(default_factory=list, description="User role names")
    permissions: Set[Permission] = Field(default_factory=set, description="Effective permissions")
    
    # Access scope
    access_scope: AccessScope = Field(default_factory=AccessScope, description="Data access scope")
    
    # Administrative flags
    is_admin: bool = Field(default=False, description="Whether user is admin")
    is_active: bool = Field(default=True, description="Whether user is active")
    
    # Session metadata
    session_id: Optional[str] = Field(default=None, description="Session ID")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Context creation time")
    expires_at: Optional[datetime] = Field(default=None, description="Context expiration time")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions or self.is_admin
    
    def has_any_permission(self, permissions: List[Permission]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(self.has_permission(perm) for perm in permissions) or self.is_admin
    
    def has_all_permissions(self, permissions: List[Permission]) -> bool:
        """Check if user has all of the specified permissions."""
        return all(self.has_permission(perm) for perm in permissions) or self.is_admin
    
    def can_access_account(self, account_id: str, owner_email: Optional[str] = None) -> bool:
        """
        Check if user can access a specific account.
        
        Args:
            account_id: Account ID to check
            owner_email: Optional account owner email
            
        Returns:
            True if user can access the account
        """
        # Admin can access everything
        if self.is_admin:
            return True
        
        # Check account-level permissions
        if not self.has_permission(Permission.READ_ACCOUNT):
            return False
        
        # Check if account is in scope
        if not self.access_scope.can_access_account(account_id):
            return False
        
        # Check ownership if required
        if self.access_scope.owned_only and owner_email:
            return owner_email.lower() == self.email.lower()
        
        return True
    
    def get_account_filter_sql(self, table_alias: str = "") -> str:
        """
        Generate SQL filter for account access.
        
        Args:
            table_alias: Optional table alias
            
        Returns:
            SQL WHERE clause for account filtering
        """
        if self.is_admin or self.access_scope.all_accounts:
            return "1=1"  # No filtering needed
        
        table_prefix = f"{table_alias}." if table_alias else ""
        
        filters = []
        
        # Account ID filter
        if self.access_scope.account_ids:
            account_list = "','".join(self.access_scope.account_ids)
            filters.append(f"{table_prefix}account_id IN ('{account_list}')")
        
        # Owner filter
        if self.access_scope.owned_only:
            filters.append(f"{table_prefix}owner_email = '{self.email}'")
        
        return " AND ".join(filters) if filters else "1=0"  # No access if no filters
    
    def get_accessible_account_ids(self) -> List[str]:
        """Get list of account IDs user can access."""
        if self.is_admin or self.access_scope.all_accounts:
            return []  # Empty list means all accounts
        
        return list(self.access_scope.account_ids)


class RBACRule(BaseModel):
    """RBAC rule for fine-grained access control."""
    
    id: str = Field(..., description="Rule ID")
    name: str = Field(..., description="Rule name")
    description: str = Field(..., description="Rule description")
    
    # Conditions
    resource_type: str = Field(..., description="Resource type (account, opportunity, etc)")
    action: Permission = Field(..., description="Required permission")
    
    # Filters
    field_filters: Dict[str, Any] = Field(default_factory=dict, description="Field-based filters")
    custom_logic: Optional[str] = Field(default=None, description="Custom logic expression")
    
    # Metadata
    is_active: bool = Field(default=True, description="Whether rule is active")
    priority: int = Field(default=100, description="Rule priority (lower = higher priority)")
    
    def applies_to(self, resource_type: str, action: Permission) -> bool:
        """Check if rule applies to a resource type and action."""
        return (
            self.is_active
            and self.resource_type == resource_type
            and self.action == action
        )


# Predefined roles
PREDEFINED_ROLES = {
    "admin": Role(
        name="admin",
        display_name="Administrator",
        description="Full system access",
        permissions=[Permission.ADMIN],
    ),
    "sales_manager": Role(
        name="sales_manager",
        display_name="Sales Manager",
        description="Full access to sales data",
        permissions=[
            Permission.READ_ACCOUNT,
            Permission.WRITE_ACCOUNT,
            Permission.READ_OPPORTUNITY,
            Permission.WRITE_OPPORTUNITY,
            Permission.READ_TASK,
            Permission.WRITE_TASK,
            Permission.READ_CONTRACT,
            Permission.VIEW_ANALYTICS,
        ],
    ),
    "sales_rep": Role(
        name="sales_rep",
        display_name="Sales Representative",
        description="Access to owned accounts and opportunities",
        permissions=[
            Permission.READ_ACCOUNT,
            Permission.READ_OPPORTUNITY,
            Permission.WRITE_OPPORTUNITY,
            Permission.READ_TASK,
            Permission.WRITE_TASK,
            Permission.READ_CONTRACT,
        ],
    ),
    "readonly": Role(
        name="readonly",
        display_name="Read Only",
        description="Read-only access to data",
        permissions=[
            Permission.READ_ACCOUNT,
            Permission.READ_OPPORTUNITY,
            Permission.READ_TASK,
            Permission.READ_CONTRACT,
        ],
    ),
}
