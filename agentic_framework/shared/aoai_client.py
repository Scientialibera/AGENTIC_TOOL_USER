"""
Azure OpenAI client with DefaultAzureCredential authentication.
"""

import asyncio
from typing import Optional, Dict, Any, List
from azure.identity.aio import DefaultAzureCredential
from openai import AsyncAzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from shared.config import AzureOpenAISettings

logger = structlog.get_logger(__name__)


class AzureOpenAIClient:
    """Azure OpenAI client with managed identity authentication."""
    
    def __init__(self, settings: AzureOpenAISettings):
        """Initialize the Azure OpenAI client."""
        endpoint = settings.endpoint
        if endpoint and ".cognitiveservices.azure.com" in endpoint:
            endpoint = endpoint.replace(".cognitiveservices.azure.com", ".openai.azure.com")
            logger.warning("Corrected AOAI endpoint domain", original=settings.endpoint, corrected=endpoint)
            settings.endpoint = endpoint
        
        self.settings = settings
        self._credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._token_cache: Optional[str] = None
        
        logger.info(
            "Initialized Azure OpenAI client",
            endpoint=settings.endpoint,
            chat_deployment=settings.chat_deployment,
        )
    
    async def _get_token(self) -> str:
        """Get Azure AD token for Azure OpenAI service."""
        try:
            token = await self._credential.get_token("https://cognitiveservices.azure.com/.default")
            return token.token
        except Exception as e:
            logger.error("Failed to get Azure AD token", error=str(e))
            raise
    
    async def _get_client(self) -> AsyncAzureOpenAI:
        """Get or create Azure OpenAI client with current token."""
        if self._client is None:
            token = await self._get_token()
            self._client = AsyncAzureOpenAI(
                azure_endpoint=self.settings.endpoint.rstrip("/"),
                api_version=self.settings.api_version,
                azure_ad_token=token,
            )
            self._token_cache = token
            logger.info("Created Azure OpenAI client with managed identity")
        return self._client
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,)),
    )
    async def create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a chat completion."""
        try:
            client = await self._get_client()
            
            completion_params = {
                "model": self.settings.chat_deployment,
                "messages": messages,
                "temperature": temperature or self.settings.temperature,
                "max_tokens": max_tokens or self.settings.max_tokens,
                **kwargs
            }
            
            if tools:
                completion_params["tools"] = tools
            if tool_choice:
                completion_params["tool_choice"] = tool_choice
            
            logger.debug(
                "Creating chat completion",
                deployment=self.settings.chat_deployment,
                message_count=len(messages),
                has_tools=bool(tools),
            )
            
            response = await client.chat.completions.create(**completion_params)
            
            result = {
                "id": response.id,
                "model": response.model,
                "created": response.created,
                "choices": [
                    {
                        "index": choice.index,
                        "message": {
                            "role": choice.message.role,
                            "content": choice.message.content,
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    }
                                }
                                for tc in (choice.message.tool_calls or [])
                            ] if choice.message.tool_calls else None,
                        },
                        "finish_reason": choice.finish_reason,
                    }
                    for choice in response.choices
                ],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                } if response.usage else {},
            }
            
            logger.debug("Chat completion created", response_id=response.id)
            return result
            
        except Exception as e:
            logger.error("Failed to create chat completion", error=str(e))
            raise
    
    async def close(self):
        """Close the client and cleanup resources."""
        if self._client:
            await self._client.close()
            self._client = None
        if self._credential:
            await self._credential.close()
