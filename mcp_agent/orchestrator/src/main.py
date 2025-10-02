"""Main entry point for the MCP Orchestrator."""

import uvicorn
from orchestrator.config.settings import settings

if __name__ == "__main__":
    uvicorn.run(
        "orchestrator.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
