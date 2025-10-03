"""UnifiedDataService

This version of the unified service speaks directly to the Cosmos DB client and
provides a single facade for per-user chat sessions, cache entries, embeddings
and feedback items. Legacy services and repositories were removed; this class
implements the minimal functionality required by the rest of the application.
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
        self.timestamp = timestamp or datetime.utcnow()
        self.user_id = user_id
        self.citations = citations or []
    
    def add_citation(self, citation: Any):
        """Add a citation to the message."""
        self.citations.append(citation)
    
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


class ConversationTurn:
    """Conversation turn model."""
    
    def __init__(
        self,
        id: str,
        user_message: Message,
        assistant_message: Message,
        turn_number: int,
        planning_time_ms: Optional[int] = None,
        total_time_ms: Optional[int] = None,
        execution_metadata: Optional[Dict[str, Any]] = None
    ):
        self.id = id
        self.user_message = user_message
        self.assistant_message = assistant_message
        self.turn_number = turn_number
        self.planning_time_ms = planning_time_ms
        self.total_time_ms = total_time_ms
        self.execution_metadata = execution_metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_message": self.user_message.to_dict(),
            "assistant_message": self.assistant_message.to_dict(),
            "turn_number": self.turn_number,
            "planning_time_ms": self.planning_time_ms,
            "total_time_ms": self.total_time_ms,
            "execution_metadata": self.execution_metadata
        }


class ChatHistory:
    """Chat history model."""
    
    def __init__(
        self,
        chat_id: str,
        user_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        turns: Optional[List[ConversationTurn]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        total_turns: Optional[int] = None
    ):
        self.chat_id = chat_id
        self.user_id = user_id
        self.title = title or "New Conversation"
        self.metadata = metadata or {}
        self.turns = turns or []
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.total_turns = total_turns or len(self.turns)
    
    def add_turn(self, turn: ConversationTurn):
        """Add a turn to the conversation."""
        self.turns.append(turn)
        self.total_turns = len(self.turns)
        self.updated_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "title": self.title,
            "metadata": self.metadata,
            "turns": [t.to_dict() for t in self.turns],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "total_turns": self.total_turns
        }


class FeedbackData:
    """Feedback data model."""
    
    def __init__(
        self,
        id: str,
        turn_id: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None
    ):
        self.id = id
        self.turn_id = turn_id
        self.user_id = user_id
        self.rating = rating
        self.comment = comment
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.utcnow()


class UnifiedDataService:
    """Facade that stores and retrieves per-user data in a single container.

    The implementation is intentionally conservative: documents are stored with
    a `doc_type` field to distinguish chat sessions, cache entries and
    feedback documents. The partition key used is `/user_id` so most operations
    require a user identifier (derived from RBACContext when available).
    """

    def __init__(self, cosmos_client: CosmosDBClient, settings: CosmosDBSettings):
        self._client = cosmos_client
        self._container = settings.chat_container
        self._settings = settings

    async def create_chat_session(
        self,
        rbac_context: RBACContext,
        chat_id: Optional[str] = None,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ChatHistory:
        """Create a new chat session."""
        user_id = rbac_context.user_id
        chat_id = chat_id or str(uuid4())
        chat_history = ChatHistory(
            chat_id=chat_id,
            user_id=user_id,
            title=title,
            metadata=metadata or {}
        )

        chat_doc = {
            "id": chat_id,
            "user_id": user_id,
            "doc_type": "chat_session",
            "chat_data": chat_history.to_dict(),
            "created_at": chat_history.created_at.isoformat(),
            "updated_at": chat_history.updated_at.isoformat(),
        }

        await self._client.create_item(self._container, chat_doc, partition_key="/user_id")
        logger.info("Created chat session", chat_id=chat_id, user_id=user_id)
        return chat_history

    async def add_conversation_turn(
        self,
        chat_id: str,
        user_message: Message,
        assistant_message: Message,
        rbac_context: RBACContext,
        plan=None,
        tool_calls=None,
        execution_metadata=None
    ) -> ConversationTurn:
        """Add a conversation turn to a chat session."""
        user_id = rbac_context.user_id
        
        doc = await self._client.read_item(
            container_name=self._container,
            item_id=chat_id,
            partition_key_value=user_id
        )
        if not doc:
            doc = await self._client.read_item(
                container_name=self._container,
                item_id=chat_id,
                partition_key_value=chat_id
            )
        if not doc:
            raise ValueError("Chat session not found")

        chat_data = doc.get("chat_data", {})
        if isinstance(chat_data, str):
            try:
                chat_dict = json.loads(chat_data)
            except Exception:
                chat_dict = chat_data
        else:
            chat_dict = chat_data

        turns_data = chat_dict.get("turns", [])
        turns = []
        for t in turns_data:
            user_msg = Message(**t["user_message"]) if isinstance(t["user_message"], dict) else t["user_message"]
            asst_msg = Message(**t["assistant_message"]) if isinstance(t["assistant_message"], dict) else t["assistant_message"]
            turns.append(ConversationTurn(
                id=t["id"],
                user_message=user_msg,
                assistant_message=asst_msg,
                turn_number=t["turn_number"],
                planning_time_ms=t.get("planning_time_ms"),
                total_time_ms=t.get("total_time_ms"),
                execution_metadata=t.get("execution_metadata", {})
            ))

        chat = ChatHistory(
            chat_id=chat_dict["chat_id"],
            user_id=chat_dict["user_id"],
            title=chat_dict.get("title"),
            metadata=chat_dict.get("metadata", {}),
            turns=turns,
            created_at=datetime.fromisoformat(chat_dict["created_at"]) if isinstance(chat_dict.get("created_at"), str) else chat_dict.get("created_at"),
            updated_at=datetime.fromisoformat(chat_dict["updated_at"]) if isinstance(chat_dict.get("updated_at"), str) else chat_dict.get("updated_at"),
            total_turns=chat_dict.get("total_turns")
        )

        turn = ConversationTurn(
            id=f"turn_{uuid4().hex[:8]}",
            user_message=user_message,
            assistant_message=assistant_message,
            turn_number=(chat.total_turns or 0) + 1,
            planning_time_ms=execution_metadata.get("planning_time_ms") if execution_metadata else None,
            total_time_ms=execution_metadata.get("total_time_ms") if execution_metadata else None,
            execution_metadata=execution_metadata,
        )

        chat.add_turn(turn)
        
        chat_doc = {
            "id": chat.chat_id,
            "user_id": chat.user_id,
            "doc_type": "chat_session",
            "chat_data": chat.to_dict(),
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat(),
        }

        await self._client.upsert_item(self._container, chat_doc, partition_key="/user_id")
        logger.info("Added conversation turn", chat_id=chat.chat_id, turn_id=turn.id)
        return turn

    async def get_chat_context(
        self,
        chat_id: str,
        rbac_context: RBACContext,
        max_turns: int = 10
    ) -> List[ConversationTurn]:
        """Get chat context with recent turns."""
        user_id = rbac_context.user_id
        doc = await self._client.read_item(
            container_name=self._container,
            item_id=chat_id,
            partition_key_value=user_id
        )
        if not doc:
            doc = await self._client.read_item(
                container_name=self._container,
                item_id=chat_id,
                partition_key_value=chat_id
            )
        if not doc:
            return []

        chat_data = doc.get("chat_data", {})
        if isinstance(chat_data, str):
            try:
                chat_dict = json.loads(chat_data)
            except Exception:
                chat_dict = chat_data
        else:
            chat_dict = chat_data

        turns_data = chat_dict.get("turns", [])
        turns = []
        for t in turns_data:
            user_msg = Message(**t["user_message"]) if isinstance(t["user_message"], dict) else t["user_message"]
            asst_msg = Message(**t["assistant_message"]) if isinstance(t["assistant_message"], dict) else t["assistant_message"]
            turns.append(ConversationTurn(
                id=t["id"],
                user_message=user_msg,
                assistant_message=asst_msg,
                turn_number=t["turn_number"],
                planning_time_ms=t.get("planning_time_ms"),
                total_time_ms=t.get("total_time_ms"),
                execution_metadata=t.get("execution_metadata", {})
            ))

        return turns[-max_turns:] if turns else []

    async def get_user_chat_sessions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[ChatHistory]:
        """Get all chat sessions for a user."""
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.doc_type = 'chat_session' ORDER BY c.created_at DESC OFFSET @offset LIMIT @limit"
        parameters = [
            {"name": "@user_id", "value": user_id},
            {"name": "@offset", "value": offset},
            {"name": "@limit", "value": limit},
        ]
        docs = await self._client.query_items(
            container_name=self._container,
            query=query,
            parameters=parameters,
            partition_key_value=user_id
        )
        
        sessions = []
        for doc in docs:
            chat_data = doc.get("chat_data", {})
            if isinstance(chat_data, str):
                try:
                    chat_dict = json.loads(chat_data)
                except Exception:
                    chat_dict = chat_data
            else:
                chat_dict = chat_data
            
            turns_data = chat_dict.get("turns", [])
            turns = []
            for t in turns_data:
                user_msg = Message(**t["user_message"]) if isinstance(t["user_message"], dict) else t["user_message"]
                asst_msg = Message(**t["assistant_message"]) if isinstance(t["assistant_message"], dict) else t["assistant_message"]
                turns.append(ConversationTurn(
                    id=t["id"],
                    user_message=user_msg,
                    assistant_message=asst_msg,
                    turn_number=t["turn_number"],
                    planning_time_ms=t.get("planning_time_ms"),
                    total_time_ms=t.get("total_time_ms"),
                    execution_metadata=t.get("execution_metadata", {})
                ))
            
            sessions.append(ChatHistory(
                chat_id=chat_dict["chat_id"],
                user_id=chat_dict["user_id"],
                title=chat_dict.get("title"),
                metadata=chat_dict.get("metadata", {}),
                turns=turns,
                created_at=datetime.fromisoformat(chat_dict["created_at"]) if isinstance(chat_dict.get("created_at"), str) else chat_dict.get("created_at"),
                updated_at=datetime.fromisoformat(chat_dict["updated_at"]) if isinstance(chat_dict.get("updated_at"), str) else chat_dict.get("updated_at"),
                total_turns=chat_dict.get("total_turns")
            ))
        
        return sessions

    async def delete_chat_session(self, chat_id: str, rbac_context: RBACContext) -> bool:
        """Delete a chat session."""
        user_id = rbac_context.user_id
        chat = await self._client.read_item(
            container_name=self._container,
            item_id=chat_id,
            partition_key_value=user_id
        )
        if not chat:
            return False
        return await self._client.delete_item(
            container_name=self._container,
            item_id=chat_id,
            partition_key_value=user_id
        )

    def _query_key(self, query: str, rbac_context: RBACContext, query_type: str) -> str:
        """Generate cache key for query."""
        key_data = {
            "query": query.strip().lower(),
            "user_id": rbac_context.user_id,
            "tenant_id": getattr(rbac_context, "tenant_id", None),
            "roles": sorted(getattr(rbac_context, "roles", [])),
            "query_type": query_type
        }
        key_string = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        return f"query:{query_type}:user:{rbac_context.user_id}:{key_hash}"

    def _embedding_key(self, text: str) -> str:
        """Generate cache key for embedding."""
        normalized_text = text.strip().lower()
        return f"embedding:{hashlib.md5(normalized_text.encode()).hexdigest()}"

    async def get_query_result(
        self,
        query: str,
        rbac_context: RBACContext,
        query_type: str = "sql"
    ):
        """Get cached query result."""
        key = self._query_key(query, rbac_context, query_type)
        doc = await self._client.read_item(
            container_name=self._container,
            item_id=key,
            partition_key_value=rbac_context.user_id
        )
        if not doc:
            return None
        return doc.get("value")

    async def set_query_result(
        self,
        query: str,
        result: Any,
        rbac_context: RBACContext,
        query_type: str = "sql",
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """Cache query result."""
        key = self._query_key(query, rbac_context, query_type)
        ttl = ttl_seconds or 1800
        doc = {
            "id": key,
            "user_id": rbac_context.user_id,
            "doc_type": "cache",
            "value": result,
            "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat()
        }
        await self._client.upsert_item(self._container, doc, partition_key="/user_id")
        return True

    async def get_embedding(self, text: str):
        """Get cached embedding."""
        key = self._embedding_key(text)
        doc = await self._client.read_item(
            container_name=self._container,
            item_id=key,
            partition_key_value=key
        )
        if not doc:
            doc = await self._client.read_item(
                container_name=self._container,
                item_id=key,
                partition_key_value=""
            )
        if not doc:
            return None
        return doc.get("embedding")

    async def set_embedding(
        self,
        text: str,
        embedding: List[float],
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """Cache embedding."""
        key = self._embedding_key(text)
        ttl = ttl_seconds or 86400
        doc = {
            "id": key,
            "user_id": "",
            "doc_type": "embedding",
            "embedding": embedding,
            "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat()
        }
        await self._client.upsert_item(self._container, doc, partition_key="/user_id")
        return True

    async def submit_feedback(
        self,
        turn_id: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Submit feedback for a turn."""
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")
        feedback_id = str(uuid4())
        doc = {
            "id": feedback_id,
            "user_id": user_id,
            "doc_type": "feedback",
            "turn_id": turn_id,
            "rating": rating,
            "comment": comment,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        await self._client.create_item(self._container, doc, partition_key="/user_id")
        logger.info("Feedback submitted", feedback_id=feedback_id, turn_id=turn_id, rating=rating)
        return feedback_id

    async def get_feedback_for_turn(self, turn_id: str) -> Optional[FeedbackData]:
        """Get feedback for a specific turn."""
        query = "SELECT * FROM c WHERE c.doc_type = 'feedback' AND c.turn_id = @turn_id"
        params = [{"name": "@turn_id", "value": turn_id}]
        docs = await self._client.query_items(
            container_name=self._container,
            query=query,
            parameters=params
        )
        for d in docs:
            try:
                return FeedbackData(**d)
            except Exception:
                return d
        return None

    async def get_user_feedback_history(
        self,
        rbac_context: RBACContext,
        limit: int = 50,
        offset: int = 0
    ):
        """Get feedback history for a user."""
        user_id = rbac_context.user_id
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.doc_type = 'feedback' ORDER BY c.created_at DESC OFFSET @offset LIMIT @limit"
        params = [
            {"name": "@user_id", "value": user_id},
            {"name": "@offset", "value": offset},
            {"name": "@limit", "value": limit}
        ]
        docs = await self._client.query_items(
            container_name=self._container,
            query=query,
            parameters=params,
            partition_key_value=user_id
        )
        out = []
        for d in docs:
            try:
                out.append(FeedbackData(**d))
            except Exception:
                out.append(d)
        return out
