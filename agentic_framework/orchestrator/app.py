"""
FastAPI application for the Orchestrator Agent.

This module creates the web API that receives chat requests and coordinates
the orchestrator agent with MCP discovery and execution.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import structlog

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import get_settings
from shared.models import RBACContext, AccessScope
from shared.aoai_client import AzureOpenAIClient
from shared.cosmos_client import CosmosDBClient
from shared.unified_service import UnifiedDataService
from shared.auth_provider import verify_token
from discovery_service import MCPDiscoveryService
from orchestrator import OrchestratorAgent

# ============================================================================
# CONSTANTS
# ============================================================================
API_HOST = "0.0.0.0"
API_PORT = 8000
API_VERSION = "1.0.0"

structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.WriteLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

settings = get_settings()


class AppState:
    """Application state container."""
    
    def __init__(self):
        self.aoai_client: Optional[AzureOpenAIClient] = None
        self.cosmos_client: Optional[CosmosDBClient] = None
        self.unified_service: Optional[UnifiedDataService] = None
        self.discovery_service: Optional[MCPDiscoveryService] = None
        self.orchestrator: Optional[OrchestratorAgent] = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the application."""
    logger.info("Starting Orchestrator Agent API")
    
    app_state.aoai_client = AzureOpenAIClient(settings.aoai)
    app_state.cosmos_client = CosmosDBClient(settings.cosmos)
    app_state.unified_service = UnifiedDataService(app_state.cosmos_client, settings.cosmos)
    app_state.discovery_service = MCPDiscoveryService(app_state.cosmos_client, settings)
    app_state.orchestrator = OrchestratorAgent(
        app_state.aoai_client,
        app_state.cosmos_client,
        app_state.discovery_service,
        app_state.unified_service,
        settings
    )
    
    logger.info("All services initialized")
    
    yield
    
    logger.info("Shutting down Orchestrator Agent API")
    
    if app_state.orchestrator:
        await app_state.orchestrator.close()
    if app_state.discovery_service:
        await app_state.discovery_service.close()
    if app_state.aoai_client:
        await app_state.aoai_client.close()
    if app_state.cosmos_client:
        await app_state.cosmos_client.close()


app = FastAPI(
    title="Orchestrator Agent API",
    version="1.0.0",
    description="Agentic Framework Orchestrator with FastMCP",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    user_id: str
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    response: str
    success: bool
    rounds: Optional[int] = None
    mcps_used: List[str] = Field(default_factory=list)
    execution_records: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


async def get_rbac_context() -> RBACContext:
    """Get RBAC context for the current request."""
    if settings.dev_mode:
        return RBACContext(
            user_id="dev@example.com",
            email="dev@example.com",
            tenant_id="dev-tenant",
            object_id="dev-object",
            roles=["admin"],
            access_scope=AccessScope(all_accounts=True),
        )
    
    return RBACContext(
        user_id="user@example.com",
        email="user@example.com",
        tenant_id="tenant123",
        object_id="user123",
        roles=["sales_rep"],
        access_scope=AccessScope(),
    )


@app.get("/health")
async def health_check(token_payload: dict = Depends(verify_token)):
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": API_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    token_payload: dict = Depends(verify_token),
    rbac_context: RBACContext = Depends(get_rbac_context),
) -> ChatResponse:
    """
    Process a chat request using the orchestrator.
    
    The orchestrator will:
    1. Discover available MCPs based on RBAC
    2. Load tool definitions
    3. Plan and execute using Azure OpenAI
    4. Return aggregated response
    5. Persist conversation to Cosmos DB
    """
    from uuid import uuid4
    from shared.unified_service import Message
    
    start_time = datetime.now(timezone.utc)
    
    try:
        logger.info(
            "Received chat request",
            user_id=request.user_id,
            message_count=len(request.messages),
            session_id=request.session_id,
        )
        
        if not request.messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No messages provided"
            )
        
        user_query = request.messages[-1].content if request.messages else ""
        session_id = request.session_id or str(uuid4())
        turn_id = str(uuid4())

        # Handle different request types based on session-centric logic
        conversation_history_from_db = None

        if session_id and request.session_id:
            # Try to get existing session
            try:
                chat_session = await app_state.unified_service.get_session_history(
                    session_id=session_id,
                    user_id=request.user_id
                )

                if chat_session and chat_session.turns:
                    # Convert session turns to conversation history (last 3 turns)
                    conversation_history_from_db = []
                    for turn in chat_session.turns[-3:]:
                        if turn.user_message and turn.assistant_message:
                            conversation_history_from_db.append({
                                "role": "user",
                                "content": turn.user_message.content
                            })
                            conversation_history_from_db.append({
                                "role": "assistant",
                                "content": turn.assistant_message.content
                            })

                    logger.debug("Retrieved session history", session_id=session_id, turn_count=len(chat_session.turns))

                    # If no new messages provided, return history
                    if not request.messages:
                        return ChatResponse(
                            session_id=session_id,
                            response=f"Session history retrieved ({len(chat_session.turns)} turns)",
                            success=True,
                            metadata={"history_turns": len(chat_session.turns)}
                        )

                elif not request.messages:
                    # No history and no messages - error
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No history for this session and no further instructions"
                    )

            except HTTPException:
                raise
            except Exception as e:
                logger.warning("Failed to retrieve conversation history", error=str(e))

        # Build conversation history for the orchestrator
        conversation_history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages[:-1]
        ] if request.messages and len(request.messages) > 1 else []
        
        result = await app_state.orchestrator.process_request(
            user_query=user_query,
            rbac_context=rbac_context,
            conversation_history=conversation_history if conversation_history else conversation_history_from_db,
            session_id=session_id,
        )
        
        assistant_response = result.get("response", "An error occurred")
        
        end_time = datetime.now(timezone.utc)
        execution_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        execution_metadata = {
            "turn_id": turn_id,
            "rounds": result.get("rounds"),
            "mcps_used": result.get("mcps_used", []),
            "execution_records": result.get("execution_records", []),
            "execution_time_ms": execution_time_ms,
            "success": result.get("success"),
            "timestamp": end_time.isoformat(),
        }
        
        await _persist_conversation_turn(
            unified_service=app_state.unified_service,
            session_id=session_id,
            turn_id=turn_id,
            user_message=user_query,
            assistant_response=assistant_response,
            rbac_context=rbac_context,
            execution_metadata=execution_metadata,
        )
        
        if not result.get("success"):
            return ChatResponse(
                session_id=session_id,
                response=assistant_response,
                success=False,
                metadata=execution_metadata,
            )
        
        return ChatResponse(
            session_id=session_id,
            response=assistant_response,
            success=True,
            rounds=result.get("rounds"),
            mcps_used=result.get("mcps_used", []),
            execution_records=result.get("execution_records", []),
            metadata=execution_metadata,
        )
        
    except Exception as e:
        logger.error("Chat request failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


async def _persist_conversation_turn(
    unified_service,
    session_id: str,
    turn_id: str,
    user_message: str,
    assistant_response: str,
    rbac_context: RBACContext,
    execution_metadata: Dict[str, Any],
) -> None:
    """Persist conversation turn to Cosmos DB using new session-centric model."""
    try:
        # Extract MCP and tool calls from execution_records
        execution_records = execution_metadata.get("execution_records", [])

        mcp_calls = []
        tool_calls = []

        for idx, record in enumerate(execution_records):
            # Each execution record represents a complete MCP execution flow
            mcp_id = record.get("mcp_id")
            tool_name = record.get("tool_name")
            tool_call_id = record.get("tool_call_id")
            result = record.get("result", {})

            # Extract LLM arguments if available from the record
            llm_arguments = record.get("arguments", {})

            # Determine execution order: sequential index
            execution_sequence = idx + 1

            # MCP call: What the LLM requested + what MCP returned
            # This captures any transformations the MCP made
            mcp_call = {
                "id": tool_call_id,
                "sequence": execution_sequence,  # Order of execution (1, 2, 3...)
                "mcp_name": mcp_id,
                "tool_name": tool_name,
                "llm_request": {
                    "tool_call_id": tool_call_id,
                    "function_name": tool_name,
                    "arguments": llm_arguments  # What the LLM sent to the MCP
                },
                "mcp_response": result,  # What the MCP returned (may be transformed from tool output)
                "timestamp": execution_metadata.get("timestamp")
            }
            mcp_calls.append(mcp_call)

            # Tool call: What the tool actually executed
            # This is what the MCP sent to the underlying tool
            tool_call = {
                "id": f"{tool_call_id}_tool",
                "sequence": execution_sequence,  # Same sequence as MCP call
                "name": tool_name,
                "mcp_id": mcp_id,
                "tool_request": {
                    # What the MCP sent to the tool (extracted from result if available)
                    "query": result.get("query") if isinstance(result, dict) else None,
                    "accounts_mentioned": result.get("resolved_accounts") if isinstance(result, dict) else None,
                },
                "tool_response": {
                    # What the tool actually returned
                    "success": result.get("success") if isinstance(result, dict) else None,
                    "data": result.get("data") if isinstance(result, dict) else None,
                    "row_count": result.get("row_count") if isinstance(result, dict) else None,
                    "source": result.get("source") if isinstance(result, dict) else None,
                }
            }
            tool_calls.append(tool_call)

        logger.debug(
            "Extracted calls from execution records",
            mcp_call_count=len(mcp_calls),
            tool_call_count=len(tool_calls)
        )

        # Clean up metadata - remove execution_records since it's now in tool_calls
        clean_metadata = {
            "turn_id": execution_metadata.get("turn_id"),
            "rounds": execution_metadata.get("rounds"),
            "mcps_used": execution_metadata.get("mcps_used", []),
            "execution_time_ms": execution_metadata.get("execution_time_ms"),
            "success": execution_metadata.get("success"),
            "timestamp": execution_metadata.get("timestamp")
        }

        # Add conversation turn (auto-creates session if doesn't exist)
        await unified_service.add_conversation_turn(
            session_id=session_id,
            user_id=rbac_context.user_id,
            user_message_content=user_message,
            assistant_message_content=assistant_response,
            mcp_calls=mcp_calls,
            tool_calls=tool_calls,
            metadata=clean_metadata,
        )

        logger.info(
            "Persisted conversation turn",
            session_id=session_id,
            turn_id=turn_id,
            mcp_calls=len(mcp_calls),
            tool_calls=len(tool_calls)
        )

    except Exception as e:
        logger.error("Failed to persist conversation turn", error=str(e))


@app.get("/mcps")
async def list_mcps(
    token_payload: dict = Depends(verify_token),
    rbac_context: RBACContext = Depends(get_rbac_context),
):
    """List available MCPs for the current user."""
    try:
        mcps = await app_state.discovery_service.discover_mcps(rbac_context)
        
        return {
            "mcps": mcps,
            "count": len(mcps),
        }
    except Exception as e:
        logger.error("Failed to list MCPs", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/tools")
async def list_tools(
    mcp_id: Optional[str] = None,
    token_payload: dict = Depends(verify_token),
    rbac_context: RBACContext = Depends(get_rbac_context),
):
    """List available tools, optionally filtered by MCP."""
    try:
        tools = await app_state.discovery_service.get_all_available_tools()
        
        if mcp_id:
            tools = [t for t in tools if t.get("mcp_id") == mcp_id]
        
        return {
            "tools": tools,
            "count": len(tools),
        }
    except Exception as e:
        logger.error("Failed to list tools", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/sessions")
async def list_sessions(
    token_payload: dict = Depends(verify_token),
    rbac_context: RBACContext = Depends(get_rbac_context),
    limit: int = 50,
    offset: int = 0,
):
    """List all chat sessions for the current user."""
    try:
        sessions = await app_state.unified_service.get_user_chat_sessions(
            user_id=rbac_context.user_id,
            limit=limit,
            offset=offset
        )
        
        return {
            "sessions": [
                {
                    "chat_id": s.chat_id,
                    "title": s.title,
                    "total_turns": s.total_turns,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                for s in sessions
            ],
            "count": len(sessions),
        }
    except Exception as e:
        logger.error("Failed to list sessions", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    token_payload: dict = Depends(verify_token),
    rbac_context: RBACContext = Depends(get_rbac_context),
    max_turns: int = 50,
):
    """Get a specific chat session with its history."""
    try:
        turns = await app_state.unified_service.get_chat_context(
            session_id,
            rbac_context,
            max_turns=max_turns
        )
        
        conversation_turns = []
        for t in turns:
            feedback = None
            try:
                feedback_data = await app_state.unified_service.get_feedback_for_turn(t.id)
                if feedback_data:
                    feedback = {
                        "rating": feedback_data.rating if hasattr(feedback_data, 'rating') else feedback_data.get('rating'),
                        "comment": feedback_data.comment if hasattr(feedback_data, 'comment') else feedback_data.get('comment'),
                        "created_at": feedback_data.created_at if hasattr(feedback_data, 'created_at') else feedback_data.get('created_at'),
                    }
            except Exception as e:
                logger.debug("No feedback found for turn", turn_id=t.id, error=str(e))

            turn_data = {
                "turn_id": t.id,
                "turn_number": t.turn_number,
                "user_message": t.user_message.to_dict() if hasattr(t.user_message, 'to_dict') else {
                    "id": t.user_message.id,
                    "role": t.user_message.role,
                    "content": t.user_message.content,
                    "timestamp": t.user_message.timestamp.isoformat() if t.user_message.timestamp else None,
                },
                "assistant_message": t.assistant_message.to_dict() if hasattr(t.assistant_message, 'to_dict') else {
                    "id": t.assistant_message.id if t.assistant_message else None,
                    "role": t.assistant_message.role if t.assistant_message else "assistant",
                    "content": t.assistant_message.content if t.assistant_message else "",
                    "timestamp": t.assistant_message.timestamp.isoformat() if t.assistant_message and t.assistant_message.timestamp else None,
                } if t.assistant_message else None,
                "planning_time_ms": t.planning_time_ms,
                "total_time_ms": t.total_time_ms,
                "execution_metadata": t.execution_metadata,
                "feedback": feedback,
            }
            conversation_turns.append(turn_data)

        return {
            "session_id": session_id,
            "turns": conversation_turns,
            "total_turns": len(conversation_turns)
        }
    except Exception as e:
        logger.error("Failed to get session", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


class FeedbackRequest(BaseModel):
    turn_id: str
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")
    comment: Optional[str] = None


@app.post("/feedback")
async def submit_feedback(
    feedback: FeedbackRequest,
    token_payload: dict = Depends(verify_token),
    rbac_context: RBACContext = Depends(get_rbac_context),
):
    """Submit feedback for a conversation turn."""
    try:
        feedback_id = await app_state.unified_service.submit_feedback(
            turn_id=feedback.turn_id,
            user_id=rbac_context.user_id,
            rating=feedback.rating,
            comment=feedback.comment,
        )
        
        return {
            "success": True,
            "feedback_id": feedback_id,
            "turn_id": feedback.turn_id,
        }
    except Exception as e:
        logger.error("Failed to submit feedback", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
