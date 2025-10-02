"""
Chat router for orchestrator API.

Handles user chat requests, validates JWT tokens, loads accessible MCPs,
and routes tool calls to appropriate MCP servers.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4
import structlog
from fastapi import APIRouter, HTTPException, Depends, status, Request, Header
from pydantic import BaseModel, Field

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.models.rbac import RBACContext

logger = structlog.get_logger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    user_id: str
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    turn_id: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int] = Field(default_factory=dict)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: Optional[int] = Field(default=None, description="Total execution time")


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> RBACContext:
    """Extract RBAC context from Authorization header."""
    from orchestrator.app import app_state

    # Extract token from Bearer header
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

    # Use auth service to extract RBAC context
    rbac_context = app_state.auth_service.extract_rbac_from_token(token)

    logger.info("Authenticated user", user_id=rbac_context.user_id, roles=rbac_context.roles)
    return rbac_context


@router.post("/chat", response_model=ChatResponse)
async def send_message(
    request_data: ChatRequest,
    user_context: RBACContext = Depends(get_current_user),
) -> ChatResponse:
    """Process chat message using MCP-based orchestration."""
    start_time = datetime.utcnow()

    # Validate request
    user_messages = [m for m in request_data.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message provided")

    user_message = user_messages[-1].content
    session_id = request_data.session_id or str(uuid4())
    turn_id = str(uuid4())

    logger.info("Processing chat message", session_id=session_id, turn_id=turn_id, user_id=request_data.user_id)

    # Get services from app state
    from orchestrator.app import app_state

    # Determine accessible MCPs based on user roles
    accessible_mcps = app_state.auth_service.get_accessible_mcps(
        roles=user_context.roles,
        role_mcp_mapping=app_state.settings.role_mcp_mapping,
    )

    logger.info("User has access to MCPs", mcps=accessible_mcps, roles=user_context.roles)

    if not accessible_mcps:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have access to any MCP servers"
        )

    try:
        # Build conversation history for context
        conversation_history = []
        for msg in request_data.messages[:-1]:  # All except current message
            conversation_history.append({
                "role": msg.role,
                "content": msg.content,
            })

        # Execute orchestration
        result = await app_state.orchestrator_service.plan_and_execute(
            user_message=user_message,
            rbac_context=user_context,
            accessible_mcps=accessible_mcps,
            conversation_history=conversation_history if conversation_history else None,
            max_rounds=8,
        )

        assistant_response = result.get("assistant_message", "I'm sorry, I couldn't process your request.")
        execution_metadata = result.get("execution_metadata", {})

    except Exception as e:
        logger.error("Chat processing failed", error=str(e), session_id=session_id)
        assistant_response = "I apologize, but I encountered an error while processing your request."
        execution_metadata = {"error": str(e)}

    # Calculate execution time
    end_time = datetime.utcnow()
    execution_time_ms = int((end_time - start_time).total_seconds() * 1000)
    execution_metadata["execution_time_ms"] = execution_time_ms

    # Calculate token usage (rough estimate)
    prompt_tokens = len(user_message.split())
    completion_tokens = len(assistant_response.split())
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }

    choices = [
        {"index": 0, "message": {"role": "assistant", "content": assistant_response}, "finish_reason": "stop"}
    ]

    return ChatResponse(
        session_id=session_id,
        turn_id=turn_id,
        choices=choices,
        usage=usage,
        sources=[],
        metadata=execution_metadata,
        execution_time_ms=execution_time_ms,
    )
