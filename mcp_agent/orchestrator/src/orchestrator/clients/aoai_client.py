"""
Azure OpenAI client with Managed Identity authentication.

This module provides a client for Azure OpenAI services using DefaultAzureCredential
for authentication and proper error handling with retry logic.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from openai import AsyncAzureOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import structlog

from orchestrator.config.settings import AzureOpenAISettings

logger = structlog.get_logger(__name__)


class AzureOpenAIClient:
    """
    Azure OpenAI client with Managed Identity authentication and retry logic.
    
    This client handles:
    - Token-based authentication using DefaultAzureCredential
    - Automatic token renewal
    - Retry logic for transient failures
    - Proper error handling and logging
    """
    
    def __init__(self, settings: AzureOpenAISettings):
        """
        Initialize the Azure OpenAI client.
        Args:
            settings: Azure OpenAI configuration settings
        """
        # Force endpoint correction regardless of settings source
        endpoint = settings.endpoint
        if endpoint and ".cognitiveservices.azure.com" in endpoint:
            endpoint = endpoint.replace(".cognitiveservices.azure.com", ".openai.azure.com")
            logger.warning("Overriding AOAI endpoint to .openai.azure.com domain", original=settings.endpoint, corrected=endpoint)
            settings.endpoint = endpoint
        self.settings = settings
        self._credential = AsyncDefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._token_cache: Optional[str] = None
        logger.info(
            "Initializing Azure OpenAI client",
            endpoint=settings.endpoint,
            chat_deployment=settings.chat_deployment,
            embedding_deployment=settings.embedding_deployment,
        )
    
    async def _get_token(self) -> str:
        """Get Azure AD token for Azure OpenAI service."""
        try:
            # Use the correct resource for OpenAI endpoint
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
            logger.info("Created Azure OpenAI client with managed identity token", endpoint=self.settings.endpoint, deployment=self.settings.chat_deployment)
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
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a chat completion using the configured deployment.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            temperature: Optional temperature override
            max_tokens: Optional max tokens override
            **kwargs: Additional parameters for the completion
            
        Returns:
            Chat completion response
        """
        client = await self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.settings.chat_deployment,
                messages=messages,
                temperature=temperature or self.settings.temperature,
                max_tokens=max_tokens or self.settings.max_tokens,
                **kwargs
            )
            logger.debug(
                "Chat completion created",
                endpoint=self.settings.endpoint,
                deployment=self.settings.chat_deployment,
                message_count=len(messages),
                usage=response.usage.model_dump() if response.usage else None,
            )
            return response.model_dump()
        except Exception as e:
            logger.error(
                "Failed to create chat completion",
                error=str(e),
                endpoint=self.settings.endpoint,
                deployment=self.settings.chat_deployment,
                message_count=len(messages),
            )
            # Reset client to force token refresh on next call
            self._client = None
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,)),
    )
    async def create_embeddings(
        self,
        texts: List[str],
        **kwargs
    ) -> List[List[float]]:
        """
        Create embeddings for the given texts.
        
        Args:
            texts: List of texts to embed
            **kwargs: Additional parameters for the embedding
            
        Returns:
            List of embedding vectors
        """
        client = await self._get_client()
        
        try:
            response = await client.embeddings.create(
                model=self.settings.embedding_deployment,
                input=texts,
                **kwargs
            )
            
            embeddings = [item.embedding for item in response.data]
            
            logger.debug(
                "Embeddings created",
                deployment=self.settings.embedding_deployment,
                text_count=len(texts),
                embedding_dimension=len(embeddings[0]) if embeddings else 0,
            )
            
            return embeddings
            
        except Exception as e:
            logger.error(
                "Failed to create embeddings",
                error=str(e),
                deployment=self.settings.embedding_deployment,
                text_count=len(texts),
            )
            # Reset client to force token refresh on next call
            self._client = None
            raise
    
    async def close(self):
        """Close the client and clean up resources."""
        if self._client:
            await self._client.close()
            self._client = None
        
        if self._credential:
            await self._credential.close()
        
        logger.info("Azure OpenAI client closed")


# Alias for backward compatibility
AOAIClient = AzureOpenAIClient
