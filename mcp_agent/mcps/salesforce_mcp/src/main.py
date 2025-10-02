"""Main entry point for the Salesforce MCP server."""

import structlog
import logging
from salesforce_mcp.config.settings import settings

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

if __name__ == "__main__":
    # Use FastMCP with proper MCP protocol
    from salesforce_mcp.server_fastmcp import mcp
    from salesforce_mcp.config.settings import settings
    mcp.run(transport="http", port=settings.api_port, host=settings.api_host)
