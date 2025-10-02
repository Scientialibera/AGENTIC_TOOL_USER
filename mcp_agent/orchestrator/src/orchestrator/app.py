"""
FastAPI application for MCP Orchestrator.

This module creates and configures the orchestrator FastAPI application with:
- Azure OpenAI and Cosmos DB clients
- MCP loader service for dynamic MCP management
- Authentication and authorization
- Chat routing to MCP servers
"""

import asyncio
import logging
from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from orchestrator.config.settings import settings
from orchestrator.clients import AzureOpenAIClient, CosmosDBClient
from orchestrator.services import AuthService, MCPLoaderService, OrchestratorService
from orchestrator.routes import chat_router

# Configure structured logging
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        min_level=getattr(logging, settings.log_level.upper(), logging.INFO)
    ),
    logger_factory=structlog.WriteLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class ApplicationState:
    """Application state container for shared resources."""

    def __init__(self):
        # Settings
        self.settings = settings

        # Clients
        self.aoai_client: AzureOpenAIClient = None
        self.cosmos_client: CosmosDBClient = None

        # Services
        self.auth_service: AuthService = None
        self.mcp_loader: MCPLoaderService = None
        self.orchestrator_service: OrchestratorService = None


# Global application state
app_state = ApplicationState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    # Startup
    logger.info("Starting MCP Orchestrator", version=settings.version, dev_mode=settings.dev_mode)

    try:
        # Initialize Azure clients
        logger.info("Initializing Azure service clients")
        app_state.aoai_client = AzureOpenAIClient(settings.azure_openai)
        logger.info("Azure OpenAI client initialized")

        app_state.cosmos_client = CosmosDBClient(settings.cosmos_db)
        logger.info("Cosmos DB client initialized")

        # Initialize services
        logger.info("Initializing orchestrator services")

        app_state.auth_service = AuthService(dev_mode=settings.dev_mode)
        logger.info("Auth service initialized", dev_mode=settings.dev_mode)

        app_state.mcp_loader = MCPLoaderService(
            mcp_servers=settings.mcp_servers,
            service_jwt_secret=settings.service_jwt_secret,
            service_jwt_expiry_minutes=settings.service_jwt_expiry_minutes,
            dev_mode=settings.dev_mode,
        )
        logger.info("MCP loader service initialized", mcp_count=len(settings.mcp_servers))

        app_state.orchestrator_service = OrchestratorService(
            aoai_client=app_state.aoai_client,
            mcp_loader=app_state.mcp_loader,
        )
        logger.info("Orchestrator service initialized")

        logger.info("Application startup completed successfully")

        yield

    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise

    finally:
        # Shutdown
        logger.info("Shutting down application")

        try:
            if app_state.mcp_loader:
                await app_state.mcp_loader.close_all()
                logger.info("MCP clients closed")

            if app_state.aoai_client:
                await app_state.aoai_client.close()
                logger.info("Azure OpenAI client closed")

            if app_state.cosmos_client:
                await app_state.cosmos_client.close()
                logger.info("Cosmos DB client closed")

            logger.info("Application shutdown completed")

        except Exception as e:
            logger.error("Error during application shutdown", error=str(e))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="MCP Orchestrator for dynamic tool routing",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # Add middleware
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
        logger.info("Configured CORS middleware", origins=settings.cors_origins)

    # Add routes
    app.include_router(
        chat_router,
        prefix=settings.api_prefix,
        tags=["chat"],
    )

    logger.info(
        "Created FastAPI application",
        app_name=settings.app_name,
        version=settings.version,
        debug=settings.debug,
        dev_mode=settings.dev_mode,
    )

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "orchestrator.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
