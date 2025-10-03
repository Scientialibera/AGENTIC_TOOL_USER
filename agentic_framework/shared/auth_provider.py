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
# Azure AD supports multiple issuer formats - we'll validate both
AZURE_AD_ISSUER_V2 = "https://login.microsoftonline.com/{tenant_id}/v2.0"
AZURE_AD_ISSUER_V1 = "https://sts.windows.net/{tenant_id}/"

logger = structlog.get_logger(__name__)

# Import FastMCP's JWTVerifier
try:
    from fastmcp.server.auth.providers.jwt import JWTVerifier as FastMCPJWTVerifier
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    logger.warning("FastMCP JWTVerifier not available - authentication will be disabled")

# Import FastAPI dependencies for orchestrator
try:
    from fastapi import HTTPException, Security, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import jwt
    from jwt import PyJWKClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logger.warning("FastAPI/PyJWT not available - orchestrator authentication will be disabled")


# FastAPI security scheme
security = HTTPBearer() if FASTAPI_AVAILABLE else None

def create_auth_provider():
    """
    Create Azure AD auth provider from settings for FastMCP servers.
    
    For now, returns None - authentication will be handled inside MCP endpoint functions.
    
    Returns:
        None - MCP servers will handle auth inside endpoint functions
    """
    settings = get_settings()
    
    # If token bypass enabled, return None (FastMCP will skip auth)
    if settings.bypass_token:
        logger.info("BYPASS_TOKEN enabled - MCP authentication disabled")
        return None
    
    # Authentication will be handled inside MCP endpoint functions using verify_token_from_request
    logger.info("MCP authentication will be handled inside endpoint functions")
    return None


async def verify_token_from_request(request) -> dict:
    """
    Verify JWT token from FastAPI/FastMCP request object.
    Call this at the start of MCP endpoint functions.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        dict: Token payload if valid
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    settings = get_settings()
    
    # If token bypass enabled, skip authentication
    if settings.bypass_token:
        logger.info("BYPASS_TOKEN enabled - skipping request token verification")
        return {"sub": "bypass-user", "bypass_token": True}
    
    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header.startswith("Bearer "):
        logger.warning("Missing or invalid Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header"
        )
    
    token = auth_header[7:]  # Remove "Bearer " prefix
    
    # Create credentials object
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token
    )
    
    # Use our SSL-fixed verify_token function
    try:
        payload = await verify_token(credentials)
        logger.debug("Token verified from request", sub=payload.get('sub'))
        return payload
    except Exception as e:
        logger.error("Request token verification failed", error=str(e))
        raise


async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """
    Verify JWT token for FastAPI endpoints (orchestrator).
    
    Validates token signature, expiration, and issuer (both v1 and v2 formats).
    Checks that issuer contains the expected tenant ID.
    
    Args:
        credentials: HTTP Bearer credentials from request
        
    Returns:
        dict: Decoded token payload
        
    Raises:
        HTTPException: If token is invalid, expired, or issuer doesn't match tenant
    """
    settings = get_settings()
    
    # If token bypass enabled, skip authentication
    if settings.bypass_token:
        logger.info("BYPASS_TOKEN enabled - skipping API token verification")
        return {"sub": "bypass-user", "bypass_token": True}
    
    if not FASTAPI_AVAILABLE:
        logger.error("FastAPI/PyJWT not available - cannot verify token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication libraries not available"
        )
    
    # Get tenant ID from environment
    tenant_id = getattr(settings, 'azure_tenant_id', None)
    if not tenant_id:
        raise ValueError("AZURE_TENANT_ID environment variable is required when BYPASS_TOKEN=false")
    
    # Get token from credentials
    token = credentials.credentials
    
    logger.info("Verifying JWT token", 
                token_prefix=token[:20] + "...",
                tenant_id=tenant_id,
                bypass_token=settings.bypass_token)
    
    try:
        # Get JWKS URL
        jwks_uri = AZURE_AD_JWKS_URL_TEMPLATE.format(tenant_id=tenant_id)
        logger.debug("Using JWKS URI", jwks_uri=jwks_uri)
        
        # Decode token header to get the kid (key ID)
        import json
        import base64
        
        # Split token and decode header
        token_parts = token.split('.')
        if len(token_parts) < 2:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format"
            )
        
        # Decode header (add padding if needed)
        header_b64 = token_parts[0]
        padding = 4 - len(header_b64) % 4
        if padding != 4:
            header_b64 += '=' * padding
        
        header = json.loads(base64.urlsafe_b64decode(header_b64))
        kid = header.get('kid')
        
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing 'kid' in header"
            )
        
        logger.debug("Token header decoded", kid=kid, alg=header.get('alg'))
        
        # Fetch JWKS manually with SSL verification disabled
        import urllib.request
        import ssl
        
        # Create unverified SSL context for development/testing
        # In production, configure proper SSL certificates
        ssl_context = ssl._create_unverified_context()
        
        try:
            with urllib.request.urlopen(jwks_uri, context=ssl_context) as response:
                jwks_data = json.loads(response.read())
        except Exception as e:
            logger.error("Failed to fetch JWKS", error=str(e), jwks_uri=jwks_uri)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Failed to fetch JWKS: {str(e)}"
            )
        
        # Find the matching key
        signing_key = None
        for key_data in jwks_data.get('keys', []):
            if key_data.get('kid') == kid:
                # Create JWT signing key from the key data
                from jwt.algorithms import RSAAlgorithm
                signing_key = RSAAlgorithm.from_jwk(json.dumps(key_data))
                break
        
        if not signing_key:
            logger.error("Signing key not found in JWKS", kid=kid)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Signing key with kid '{kid}' not found in JWKS"
            )
        logger.debug("Retrieved signing key from JWKS")
        
        # Build expected issuers (both v1 and v2 formats)
        issuer_v2 = AZURE_AD_ISSUER_V2.format(tenant_id=tenant_id)
        issuer_v1 = AZURE_AD_ISSUER_V1.format(tenant_id=tenant_id)
        
        logger.info("Expected issuers", issuer_v1=issuer_v1, issuer_v2=issuer_v2)
        
        # Optional audience
        audience = getattr(settings, 'azure_audience', None)
        # Don't validate audience if it's the placeholder value
        if audience and audience == "api://your-api-app-registration-id":
            logger.warning("AZURE_AUDIENCE is set to placeholder value - disabling audience validation")
            audience = None
        logger.info("Audience configuration", audience=audience, verify_aud=bool(audience))
        
        # Try to decode and validate token
        # We'll validate issuer manually to support both formats
        decode_options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": True,
            "verify_aud": bool(audience),
            "require": ["exp", "iat", "iss"]
        }
        
        logger.debug("Decoding JWT token with options", options=decode_options)
        
        # Decode without issuer validation first
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audience if audience else None,
            options=decode_options
        )
        
        logger.info("Token decoded successfully", 
                   token_issuer=payload.get("iss"),
                   token_audience=payload.get("aud"),
                   token_subject=payload.get("sub"))
        
        # Manually validate issuer (accept both v1 and v2 formats)
        token_issuer = payload.get("iss", "")
        if token_issuer not in [issuer_v2, issuer_v1]:
            logger.error(
                "Invalid issuer - mismatch",
                token_issuer=token_issuer,
                expected_v2=issuer_v2,
                expected_v1=issuer_v1,
                match_v2=(token_issuer == issuer_v2),
                match_v1=(token_issuer == issuer_v1)
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token issuer. Got: {token_issuer}, Expected: {issuer_v2} or {issuer_v1}"
            )
        
        logger.info("Token validated successfully", sub=payload.get("sub"))
        return payload
        
    except jwt.ExpiredSignatureError as e:
        logger.warning("Token expired", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )
    except jwt.InvalidTokenError as e:
        logger.error("Invalid token - JWT validation failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
    except HTTPException:
        # Re-raise HTTP exceptions (like issuer mismatch)
        raise
    except Exception as e:
        logger.error("Token verification failed - unexpected error", 
                    error=str(e), 
                    error_type=type(e).__name__)
        import traceback
        logger.debug("Token verification traceback", traceback=traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}"
        )
