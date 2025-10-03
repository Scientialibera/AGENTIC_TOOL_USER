"""
Azure AD JWT Authentication Provider for FastMCP.

This module provides JWT token validation for MCP servers using Azure AD/Entra ID tokens.
Validates the token's issuer contains the expected tenant ID.

Uses FastMCP's built-in JWTVerifier.
"""

from typing import Optional
import structlog

from shared.config import get_settings

# ============================================================================
# CONSTANTS
# ============================================================================
AZURE_AD_JWKS_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
AZURE_AD_ISSUER_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/v2.0"

logger = structlog.get_logger(__name__)

# Import FastMCP's JWTVerifier
try:
    from fastmcp.server.auth.providers.jwt import JWTVerifier as FastMCPJWTVerifier
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    logger.warning("FastMCP JWTVerifier not available - authentication will be disabled")


def create_auth_provider():
    """
    Create Azure AD auth provider from settings.
    
    Returns None in dev mode (disables authentication).
    Returns FastMCP's JWTVerifier in production mode (enables JWT validation).
    
    Returns:
        Optional[FastMCPJWTVerifier]: Auth provider or None
        
    Raises:
        ValueError: If AZURE_TENANT_ID is missing in production mode
    """
    settings = get_settings()
    
    # In dev mode, return None (FastMCP will skip auth)
    if settings.dev_mode:
        logger.info("Dev mode enabled - authentication disabled")
        return None
    
    # Get tenant ID from environment
    tenant_id = getattr(settings, 'azure_tenant_id', None)
    if not tenant_id:
        raise ValueError("AZURE_TENANT_ID environment variable is required when DEV_MODE=false")
    
    # Optional audience (API app registration ID)
    audience = getattr(settings, 'azure_audience', None)
    
    # Build JWKS URL for Azure AD
    jwks_uri = AZURE_AD_JWKS_URL_TEMPLATE.format(tenant_id=tenant_id)
    issuer = AZURE_AD_ISSUER_TEMPLATE.format(tenant_id=tenant_id)
    
    if not FASTMCP_AVAILABLE:
        logger.error("FastMCP JWTVerifier not available - cannot enable authentication")
        raise ImportError("FastMCP with JWT support is required for authentication")
    
    # Use FastMCP's built-in JWTVerifier
    logger.info("Using FastMCP JWTVerifier", jwks_uri=jwks_uri, issuer=issuer)
    return FastMCPJWTVerifier(
        jwks_uri=jwks_uri,
        issuer=issuer,
        audience=audience
    )
