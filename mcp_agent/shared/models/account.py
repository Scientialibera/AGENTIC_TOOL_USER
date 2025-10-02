"""
Account model for Salesforce account data and resolution.

This module defines the Account model and related structures for account
resolution, similarity matching, and RBAC.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AccountSimilarity(BaseModel):
    """Account similarity score for name resolution."""
    
    account_id: str = Field(..., description="Account ID")
    account_name: str = Field(..., description="Account name")
    similarity_score: float = Field(..., description="Cosine similarity score (0-1)")
    matched_aliases: List[str] = Field(default_factory=list, description="Matched alias names")
    
    class Config:
        """Pydantic configuration."""
        validate_assignment = True


class Account(BaseModel):
    """Salesforce account model with RBAC context."""
    
    # Core account data
    id: str = Field(..., description="Salesforce account ID")
    name: str = Field(..., description="Account name")
    display_name: str = Field(..., description="Display name for UI")
    
    # Account details
    account_type: Optional[str] = Field(default=None, description="Account type")
    industry: Optional[str] = Field(default=None, description="Industry")
    annual_revenue: Optional[float] = Field(default=None, description="Annual revenue")
    number_of_employees: Optional[int] = Field(default=None, description="Number of employees")
    
    # Contact information
    billing_address: Optional[str] = Field(default=None, description="Billing address")
    shipping_address: Optional[str] = Field(default=None, description="Shipping address")
    phone: Optional[str] = Field(default=None, description="Phone number")
    website: Optional[str] = Field(default=None, description="Website URL")
    
    # Ownership and access
    owner_user_id: str = Field(..., description="Account owner user ID")
    owner_email: str = Field(..., description="Account owner email")
    
    # Name resolution
    aliases: List[str] = Field(default_factory=list, description="Alternative names/aliases")
    name_embedding: Optional[List[float]] = Field(default=None, description="Name embedding vector")
    
    # Metadata
    is_active: bool = Field(default=True, description="Whether account is active")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    # Salesforce metadata
    sf_last_modified: Optional[datetime] = Field(default=None, description="Salesforce last modified date")
    sf_system_modstamp: Optional[datetime] = Field(default=None, description="Salesforce system modstamp")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    def add_alias(self, alias: str) -> None:
        """
        Add an alias to the account.
        
        Args:
            alias: Alias name to add
        """
        if alias not in self.aliases and alias != self.name:
            self.aliases.append(alias)
    
    def get_all_names(self) -> List[str]:
        """
        Get all names (primary name + aliases).
        
        Returns:
            List of all account names
        """
        names = [self.name, self.display_name]
        names.extend(self.aliases)
        return list(set(names))  # Remove duplicates
    
    def matches_name(self, search_name: str, threshold: float = 0.8) -> bool:
        """
        Check if account matches a search name.
        
        Args:
            search_name: Name to search for
            threshold: Similarity threshold
            
        Returns:
            True if name matches
        """
        search_lower = search_name.lower().strip()
        
        # Exact matches
        for name in self.get_all_names():
            if name.lower().strip() == search_lower:
                return True
        
        # Partial matches (contains)
        for name in self.get_all_names():
            name_lower = name.lower().strip()
            if search_lower in name_lower or name_lower in search_lower:
                return True
        
        return False


class AccountResolutionRequest(BaseModel):
    """Request for account name resolution."""
    
    query_text: str = Field(..., description="Original query text")
    extracted_name: str = Field(..., description="Extracted account name")
    user_email: str = Field(..., description="User email for RBAC")
    confidence_threshold: float = Field(default=0.7, description="Minimum confidence threshold")
    max_results: int = Field(default=10, description="Maximum number of results")


class AccountResolutionResult(BaseModel):
    """Result of account name resolution."""
    
    request: AccountResolutionRequest = Field(..., description="Original request")
    candidates: List[AccountSimilarity] = Field(default_factory=list, description="Candidate accounts")
    selected_account: Optional[Account] = Field(default=None, description="Selected account if confident")
    needs_disambiguation: bool = Field(default=False, description="Whether user needs to disambiguate")
    disambiguation_message: Optional[str] = Field(default=None, description="Message for disambiguation")
    
    @property
    def has_confident_match(self) -> bool:
        """Check if there's a confident match."""
        return (
            len(self.candidates) > 0 
            and self.candidates[0].similarity_score >= self.request.confidence_threshold
        )
    
    @property
    def best_match(self) -> Optional[AccountSimilarity]:
        """Get the best matching account."""
        return self.candidates[0] if self.candidates else None
