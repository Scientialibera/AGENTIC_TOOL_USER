"""
JWT authentication utilities for service-to-service communication.

This module provides utilities for creating and validating JWT tokens between
the orchestrator and MCP servers.
"""

import jwt
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from ..models.rbac import RBACContext, AccessScope


def create_service_token(
    service_name: str,
    secret_key: str,
    expires_in_minutes: int = 60
) -> str:
    """
    Create a JWT token for service-to-service communication.

    Args:
        service_name: Name of the service (e.g., "orchestrator")
        secret_key: Secret key for signing the token
        expires_in_minutes: Token expiration time in minutes

    Returns:
        Signed JWT token
    """
    payload = {
        "service": service_name,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=expires_in_minutes),
    }

    return jwt.encode(payload, secret_key, algorithm="HS256")


def validate_service_token(
    token: str,
    secret_key: str,
    expected_service: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate a service JWT token.

    Args:
        token: JWT token to validate
        secret_key: Secret key for validation
        expected_service: Optional service name to check

    Returns:
        Decoded token payload

    Raises:
        jwt.InvalidTokenError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])

        if expected_service and payload.get("service") != expected_service:
            raise jwt.InvalidTokenError(f"Invalid service: expected {expected_service}")

        return payload

    except jwt.ExpiredSignatureError:
        raise jwt.InvalidTokenError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise


def extract_rbac_from_user_token(token: str) -> RBACContext:
    """
    Extract RBAC context from user JWT token (without validation).

    This is used by the orchestrator to extract user information from
    the incoming user token. The token should already be validated by
    the calling service.

    Args:
        token: User JWT token

    Returns:
        RBACContext with user information
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        claims = {}

    return RBACContext(
        user_id=claims.get("email", "unknown@example.com"),
        email=claims.get("email", "unknown@example.com"),
        tenant_id=claims.get("tid", "unknown"),
        object_id=claims.get("oid", "unknown"),
        roles=claims.get("roles", []),
        access_scope=AccessScope(),
    )
