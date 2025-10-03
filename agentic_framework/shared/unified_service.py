"""UnifiedDataService - Session-centric storage model

This service implements session-centric storage where:
- Each session document contains all turns (messages, MCP calls, tool calls, feedback)
- Partition key is session_id
- All related data for a turn is nested within that turn
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from uuid import uuid4
import hashlib
import json
import structlog

from shared.cosmos_client import CosmosDBClient
from shared.config import CosmosDBSettings
from shared.models import RBACContext

logger = structlog.get_logger(__name__)


class Message:
    """Message model for conversation turns."""

    def __init__(
        self,
        id: str,
        role: str,
        content: str,
        timestamp: Optional[datetime] = None,
        user_id: Optional[str] = None,
        citations: Optional[List[Any]] = None
    ):
        self.id = id
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None)
        self.user_id = user_id
        self.citations = citations or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_id": self.user_id,
            "citations": [c.to_dict() if hasattr(c, 'to_dict') else c for c in self.citations]
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Message':
        """Create from dictionary."""
        return Message(
            id=data["id"],
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else None,
            user_id=data.get("user_id"),
            citations=data.get("citations", [])
        )


class ConversationTurn:
    """Conversation turn with all associated data."""

    def __init__(
        self,
        turn_id: str,
        turn_number: int,
        timestamp: Optional[datetime] = None,
        user_message: Optional[Message] = None,
        assistant_message: Optional[Message] = None,
        mcp_calls: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        feedback: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.turn_id = turn_id
        self.turn_number = turn_number
        self.timestamp = timestamp or datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None)
        self.user_message = user_message
        self.assistant_message = assistant_message
        self.mcp_calls = mcp_calls or []
        self.tool_calls = tool_calls or []
        self.feedback = feedback or []
        self.metadata = metadata or {}

    def add_feedback(self, feedback_type: str, comment: Optional[str] = None):
        """Add feedback to this turn."""
        feedback_entry = {
            "id": f"feedback_{uuid4().hex[:8]}",
            "type": feedback_type,
            "comment": comment,
            "timestamp": datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).isoformat()
        }
        self.feedback.append(feedback_entry)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "turn_id": self.turn_id,
            "turn_number": self.turn_number,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_message": self.user_message.to_dict() if self.user_message else None,
            "assistant_message": self.assistant_message.to_dict() if self.assistant_message else None,
            "mcp_calls": self.mcp_calls,
            "tool_calls": self.tool_calls,
            "feedback": self.feedback,
            "metadata": self.metadata
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'ConversationTurn':
        """Create from dictionary."""
        return ConversationTurn(
            turn_id=data["turn_id"],
            turn_number=data["turn_number"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else None,
            user_message=Message.from_dict(data["user_message"]) if data.get("user_message") else None,
            assistant_message=Message.from_dict(data["assistant_message"]) if data.get("assistant_message") else None,
            mcp_calls=data.get("mcp_calls", []),
            tool_calls=data.get("tool_calls", []),
            feedback=data.get("feedback", []),
            metadata=data.get("metadata", {})
        )


class ChatSession:
    """Chat session with all turns."""

    def __init__(
        self,
        session_id: str,
        user_id: str,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        turns: Optional[List[ConversationTurn]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.created_at = created_at or datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None)
        self.updated_at = updated_at or datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None)
        self.turns = turns or []
        self.metadata = metadata or {}

    def add_turn(self, turn: ConversationTurn):
        """Add a turn to the session."""
        self.turns.append(turn)
        self.updated_at = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None)

    def get_latest_turn(self) -> Optional[ConversationTurn]:
        """Get the most recent turn."""
        return self.turns[-1] if self.turns else None

    def get_turn_count(self) -> int:
        """Get total number of turns."""
        return len(self.turns)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Cosmos DB storage."""
        return {
            "id": self.session_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "doc_type": "chat_session",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "turns": [turn.to_dict() for turn in self.turns],
            "metadata": self.metadata
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'ChatSession':
        """Create from dictionary."""
        return ChatSession(
            session_id=data["session_id"],
            user_id=data["user_id"],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            turns=[ConversationTurn.from_dict(t) for t in data.get("turns", [])],
            metadata=data.get("metadata", {})
        )


class UnifiedDataService:
    """Unified data service for session-centric storage."""

    def __init__(self, cosmos_client: CosmosDBClient, settings: CosmosDBSettings):
        """Initialize the unified data service."""
        self._client = cosmos_client
        self._settings = settings
        self._container = settings.chat_container
        logger.info("UnifiedDataService initialized", container=self._container)

    async def get_or_create_session(
        self,
        session_id: str,
        user_id: str
    ) -> ChatSession:
        """Get existing session or create new one."""
        try:
            # Try to read existing session (partition key is session_id)
            doc = await self._client.read_item(
                container_name=self._container,
                item_id=session_id,
                partition_key_value=session_id
            )

            if doc:
                logger.debug("Retrieved existing session", session_id=session_id, turn_count=len(doc.get("turns", [])))
                return ChatSession.from_dict(doc)

        except Exception as e:
            logger.warning("Error reading session", session_id=session_id, error=str(e))

        # Create new session
        logger.info("Creating new session", session_id=session_id, user_id=user_id)
        return ChatSession(session_id=session_id, user_id=user_id)

    async def save_session(self, session: ChatSession) -> None:
        """Save session to Cosmos DB."""
        try:
            doc = session.to_dict()
            await self._client.upsert_item(
                container_name=self._container,
                item=doc
            )
            logger.info("Session saved", session_id=session.session_id, turn_count=len(session.turns))
        except Exception as e:
            logger.error("Failed to save session", session_id=session.session_id, error=str(e))
            raise

    async def add_conversation_turn(
        self,
        session_id: str,
        user_id: str,
        user_message_content: str,
        assistant_message_content: str,
        mcp_calls: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ChatSession:
        """Add a conversation turn to a session."""
        # Get or create session
        session = await self.get_or_create_session(session_id, user_id)

        # Create turn
        turn_number = session.get_turn_count() + 1
        turn_id = f"turn_{uuid4().hex[:8]}"

        user_message = Message(
            id=f"msg_user_{uuid4().hex[:8]}",
            role="user",
            content=user_message_content,
            user_id=user_id
        )

        assistant_message = Message(
            id=f"msg_asst_{uuid4().hex[:8]}",
            role="assistant",
            content=assistant_message_content
        )

        turn = ConversationTurn(
            turn_id=turn_id,
            turn_number=turn_number,
            user_message=user_message,
            assistant_message=assistant_message,
            mcp_calls=mcp_calls or [],
            tool_calls=tool_calls or [],
            metadata=metadata or {}
        )

        # Add turn to session
        session.add_turn(turn)

        # Save session
        await self.save_session(session)

        logger.info("Added conversation turn", session_id=session_id, turn_id=turn_id, turn_number=turn_number)
        return session

    async def add_feedback_to_latest_turn(
        self,
        session_id: str,
        user_id: str,
        feedback_type: str,
        comment: Optional[str] = None
    ) -> ChatSession:
        """Add feedback to the most recent turn in a session."""
        # Get session
        session = await self.get_or_create_session(session_id, user_id)

        if not session.turns:
            raise ValueError(f"No turns in session {session_id} to add feedback to")

        # Add feedback to latest turn
        latest_turn = session.get_latest_turn()
        latest_turn.add_feedback(feedback_type, comment)

        # Save session
        await self.save_session(session)

        logger.info("Added feedback to turn", session_id=session_id, turn_id=latest_turn.turn_id, feedback_type=feedback_type)
        return session

    async def get_session_history(
        self,
        session_id: str,
        user_id: str
    ) -> Optional[ChatSession]:
        """Get full session history."""
        try:
            doc = await self._client.read_item(
                container_name=self._container,
                item_id=session_id,
                partition_key_value=session_id
            )

            if not doc:
                logger.debug("No history found for session", session_id=session_id)
                return None

            session = ChatSession.from_dict(doc)
            logger.debug("Retrieved session history", session_id=session_id, turn_count=len(session.turns))
            return session

        except Exception as e:
            logger.error("Error retrieving session history", session_id=session_id, error=str(e))
            return None

    async def delete_session(
        self,
        session_id: str,
        user_id: str
    ) -> bool:
        """Delete a session."""
        try:
            await self._client.delete_item(
                container_name=self._container,
                item_id=session_id,
                partition_key_value=session_id
            )
            logger.info("Deleted session", session_id=session_id)
            return True
        except Exception as e:
            logger.error("Failed to delete session", session_id=session_id, error=str(e))
            return False

    # ========================================================================
    # CACHE OPERATIONS (Query results, embeddings)
    # ========================================================================

    def _cache_key(self, query: str, rbac_context: RBACContext, query_type: str) -> str:
        """Generate cache key for query results."""
        key_data = {
            "query": query.strip().lower(),
            "user_id": rbac_context.user_id,
            "roles": sorted(rbac_context.roles),
            "query_type": query_type
        }
        key_string = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        return f"cache_{query_type}_{key_hash}"

    async def get_cached_query_result(
        self,
        query: str,
        rbac_context: RBACContext,
        query_type: str = "sql",
        ttl_hours: int = 24
    ) -> Optional[Any]:
        """Get cached query result if not expired."""
        try:
            cache_key = self._cache_key(query, rbac_context, query_type)

            doc = await self._client.read_item(
                container_name=self._container,
                item_id=cache_key,
                partition_key_value=cache_key
            )

            if not doc:
                return None

            # Check expiration
            cached_at = datetime.fromisoformat(doc["cached_at"])
            if datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None) - cached_at > timedelta(hours=ttl_hours):
                logger.debug("Cache expired", cache_key=cache_key)
                return None

            logger.debug("Cache hit", cache_key=cache_key)
            return doc.get("result")

        except Exception as e:
            logger.warning("Cache read error", error=str(e))
            return None

    async def set_cached_query_result(
        self,
        query: str,
        result: Any,
        rbac_context: RBACContext,
        query_type: str = "sql"
    ) -> None:
        """Cache query result."""
        try:
            cache_key = self._cache_key(query, rbac_context, query_type)

            doc = {
                "id": cache_key,
                "doc_type": "cache",
                "query_type": query_type,
                "query": query,
                "result": result,
                "user_id": rbac_context.user_id,
                "cached_at": datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).isoformat()
            }

            await self._client.upsert_item(
                container_name=self._container,
                item=doc
            )

            logger.debug("Cached query result", cache_key=cache_key)

        except Exception as e:
            logger.warning("Failed to cache result", error=str(e))

    async def close(self):
        """Close the service and cleanup resources."""
        if self._client:
            await self._client.close()
