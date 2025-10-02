"""
Message and conversation models for chat interactions.

This module defines models for chat messages, tool calls, citations,
and conversation history management.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Message role enumeration."""
    
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class CitationSource(BaseModel):
    """Citation source information."""
    
    source_type: str = Field(..., description="Type of source (sql, graph, document)")
    title: str = Field(..., description="Source title or table name")
    url: Optional[str] = Field(default=None, description="Source URL if available")
    snippet: str = Field(..., description="Relevant text snippet")
    confidence: Optional[float] = Field(default=None, description="Confidence score")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class Citation(BaseModel):
    """Citation with sources and relevance information."""
    
    id: str = Field(..., description="Citation ID")
    sources: List[CitationSource] = Field(default_factory=list, description="Citation sources")
    relevance_score: Optional[float] = Field(default=None, description="Relevance to query")
    
    def add_source(self, source: CitationSource) -> None:
        """Add a source to this citation."""
        self.sources.append(source)


class ToolCall(BaseModel):
    """Tool/function call information."""
    
    id: str = Field(..., description="Tool call ID")
    name: str = Field(..., description="Tool/function name")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Tool execution result")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    duration_ms: Optional[int] = Field(default=None, description="Execution duration in milliseconds")


class Message(BaseModel):
    """Chat message with metadata and tool information."""
    
    id: str = Field(..., description="Message ID")
    role: MessageRole = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    
    # Tool and function calls
    tool_calls: List[ToolCall] = Field(default_factory=list, description="Tool calls made")
    
    # Citations and sources
    citations: List[Citation] = Field(default_factory=list, description="Citations in the message")
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")
    tokens_used: Optional[int] = Field(default=None, description="Tokens used for this message")
    model_used: Optional[str] = Field(default=None, description="Model used for generation")
    
    # User context
    user_id: Optional[str] = Field(default=None, description="User ID who sent the message")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    def add_citation(self, citation: Citation) -> None:
        """Add a citation to this message."""
        self.citations.append(citation)
    
    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to this message."""
        self.tool_calls.append(tool_call)
    
    @property
    def has_tool_calls(self) -> bool:
        """Check if message has tool calls."""
        return len(self.tool_calls) > 0
    
    @property
    def has_citations(self) -> bool:
        """Check if message has citations."""
        return len(self.citations) > 0


class ConversationTurn(BaseModel):
    """A conversation turn with user message and assistant response."""

    id: str = Field(..., description="Turn ID")
    user_message: Message = Field(..., description="User message")
    assistant_message: Optional[Message] = Field(default=None, description="Assistant response")

    # Turn metadata
    turn_number: int = Field(..., description="Turn number in conversation")
    planning_time_ms: Optional[int] = Field(default=None, description="Planning time in milliseconds")
    total_time_ms: Optional[int] = Field(default=None, description="Total turn time in milliseconds")

    # Execution lineage - stores all agent calls, tool calls, and intermediate results
    execution_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Complete execution metadata including rounds, agent calls, tool calls, and results"
    )

    @property
    def is_complete(self) -> bool:
        """Check if turn is complete (has assistant response)."""
        return self.assistant_message is not None


class ChatHistory(BaseModel):
    """Chat conversation history."""
    
    chat_id: str = Field(..., description="Chat session ID")
    user_id: str = Field(..., description="User ID")
    
    # Conversation data
    turns: List[ConversationTurn] = Field(default_factory=list, description="Conversation turns")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Chat creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")
    title: Optional[str] = Field(default=None, description="Chat title")
    
    # Statistics
    total_tokens: int = Field(default=0, description="Total tokens used")
    total_turns: int = Field(default=0, description="Total number of turns")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    def add_turn(self, turn: ConversationTurn) -> None:
        """Add a turn to the conversation."""
        self.turns.append(turn)
        self.total_turns = len(self.turns)
        self.updated_at = datetime.utcnow()
        
        # Update token count
        if turn.user_message.tokens_used:
            self.total_tokens += turn.user_message.tokens_used
        if turn.assistant_message and turn.assistant_message.tokens_used:
            self.total_tokens += turn.assistant_message.tokens_used
    
    def get_recent_turns(self, count: int = 5) -> List[ConversationTurn]:
        """Get recent conversation turns."""
        return self.turns[-count:] if count > 0 else self.turns
    
    def get_messages_for_llm(self, max_turns: int = 10) -> List[Dict[str, str]]:
        """
        Get messages formatted for LLM context.
        
        Args:
            max_turns: Maximum number of turns to include
            
        Returns:
            List of message dictionaries for LLM
        """
        messages = []
        recent_turns = self.get_recent_turns(max_turns)
        
        for turn in recent_turns:
            # Add user message
            messages.append({
                "role": turn.user_message.role.value,
                "content": turn.user_message.content,
            })
            
            # Add assistant message if available
            if turn.assistant_message:
                messages.append({
                    "role": turn.assistant_message.role.value,
                    "content": turn.assistant_message.content,
                })
        
        return messages
