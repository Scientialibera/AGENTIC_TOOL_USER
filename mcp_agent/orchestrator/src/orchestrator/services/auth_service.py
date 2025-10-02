"""
Authentication service for JWT validation and RBAC context extraction.

Handles both user JWT tokens and service-to-service authentication.
"""

import structlog
from typing import Optional
from jose import jwt as jose_jwt

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.models.rbac import RBACContext, AccessScope

logger = structlog.get_logger(__name__)


class AuthService:
    """Service for handling authentication and authorization."""

    def __init__(self, dev_mode: bool = False):
        """
        Initialize auth service.

        Args:
            dev_mode: If True, bypass JWT validation and use dev user
        """
        self.dev_mode = dev_mode

    def extract_rbac_from_token(self, token: Optional[str]) -> RBACContext:
        """
        Extract RBAC context from user JWT token.

        In dev mode, returns a default dev user context.
        In production mode, extracts claims from the JWT token.

        Args:
            token: JWT token (optional in dev mode)

        Returns:
            RBACContext with user information and roles
        """
        if self.dev_mode:
            logger.info("Dev mode: using default dev user context")
            return RBACContext(
                user_id="dev@example.com",
                email="dev@example.com",
                tenant_id="dev-tenant",
                object_id="dev-object-id",
                roles=["admin"],  # Dev user has admin role
                access_scope=AccessScope(all_accounts=True),
                is_admin=True,
            )

        if not token:
            logger.warning("No token provided in production mode, using anonymous context")
            return RBACContext(
                user_id="anonymous@example.com",
                email="anonymous@example.com",
                tenant_id="unknown",
                object_id="unknown",
                roles=["readonly"],
                access_scope=AccessScope(),
            )

        try:
            claims = jose_jwt.get_unverified_claims(token)
            logger.debug("Extracted claims from JWT", claims=claims)

            roles = claims.get("roles", [])
            if isinstance(roles, str):
                roles = [roles]

            return RBACContext(
                user_id=claims.get("email", claims.get("upn", "unknown@example.com")),
                email=claims.get("email", claims.get("upn", "unknown@example.com")),
                tenant_id=claims.get("tid", "unknown"),
                object_id=claims.get("oid", "unknown"),
                roles=roles,
                access_scope=AccessScope(),
                is_admin="admin" in roles,
            )

        except Exception as e:
            logger.error("Failed to extract RBAC from token", error=str(e))
            return RBACContext(
                user_id="error@example.com",
                email="error@example.com",
                tenant_id="unknown",
                object_id="unknown",
                roles=[],
                access_scope=AccessScope(),
            )

    def get_accessible_mcps(self, roles: list, role_mcp_mapping: dict) -> list:
        """
        Get list of MCP names accessible to the given roles.

        Args:
            roles: List of user role names
            role_mcp_mapping: Mapping of roles to MCP names

        Returns:
            List of accessible MCP names
        """
        accessible_mcps = set()

        for role in roles:
            mcps = role_mcp_mapping.get(role, [])
            accessible_mcps.update(mcps)

        logger.info("Determined accessible MCPs", roles=roles, mcps=list(accessible_mcps))
        return list(accessible_mcps)
