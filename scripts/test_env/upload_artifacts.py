import asyncio
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
AGENTIC_FRAMEWORK = ROOT / "agentic_framework"
if str(AGENTIC_FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(AGENTIC_FRAMEWORK))

from shared.config import get_settings
from shared.cosmos_client import CosmosDBClient

# Asset roots
ASSETS = ROOT / "scripts" / "assets"
PROMPTS_DIR = ASSETS / "prompts"
FUNCTIONS_DIRS: Iterable[Path] = [ASSETS / "functions" / "tools", ASSETS / "functions" / "agents"]
SCHEMA_DIR = ASSETS / "schema"


async def upload_prompts(cosmos: CosmosDBClient, prompts_container: str):
    if not PROMPTS_DIR.exists():
        print(f"Prompts directory not found: {PROMPTS_DIR}")
        return

    for path in PROMPTS_DIR.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        doc = {"id": path.stem, "content": content}
        await cosmos.upsert_item(container_name=prompts_container, item=doc)
        print(f"Uploaded prompt {path.stem}")


async def upload_functions(cosmos: CosmosDBClient, functions_container: str):
    for folder in FUNCTIONS_DIRS:
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            await cosmos.upsert_item(container_name=functions_container, item=data)
            print(f"Uploaded functions doc {path.name}")


async def upload_schema(cosmos: CosmosDBClient, schema_container: str):
    if not SCHEMA_DIR.exists():
        print(f"Schema directory not found: {SCHEMA_DIR}")
        return

    for path in SCHEMA_DIR.glob("*.json"):
        arr = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(arr, list):
            print(f"Skipping {path.name}: expected list")
            continue
        for item in arr:
            await cosmos.upsert_item(container_name=schema_container, item=item)
            print(f"Uploaded schema item {item.get('table_name') or item.get('id')}")


async def main():
    settings = get_settings()
    cosmos = CosmosDBClient(settings.cosmos)
    try:
        await upload_prompts(cosmos, settings.cosmos.prompts_container)
        await upload_functions(cosmos, settings.cosmos.agent_functions_container)
        await upload_schema(cosmos, settings.cosmos.sql_schema_container)
    finally:
        client = getattr(cosmos, "_client", None)
        if client:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
