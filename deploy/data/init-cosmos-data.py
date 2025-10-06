#!/usr/bin/env python3
"""
Cosmos DB Data Initialization Script for Agentic Framework.

This script initializes Cosmos DB with:
- System prompts from scripts/assets/prompts/
- Function/tool definitions from scripts/assets/functions/
- SQL schema metadata from scripts/assets/schema/
- Demo graph data (accounts, SOWs, offerings, tech stack)

Requirements:
- Azure CLI authenticated (az login)
- Managed Identity or user with data plane access to Cosmos DB
- Environment variables configured in .env file
"""

import asyncio
import json
import sys
import os
from pathlib import Path
from typing import List

# Add agentic_framework to path
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
agentic_framework_dir = project_root / "agentic_framework"
sys.path.insert(0, str(agentic_framework_dir))
os.chdir(project_root)

# Load .env
env_path = project_root / '.env'
if env_path.exists():
    with open(env_path, 'r', encoding='utf-8') as ef:
        for ln in ef:
            ln = ln.strip()
            if ln and '=' in ln and not ln.startswith('#'):
                k, v = ln.split('=', 1)
                if k and k not in os.environ:
                    os.environ[k] = v

from shared.config import get_settings
from shared.cosmos_client import CosmosDBClient
from shared.gremlin_client import GremlinClient

settings = get_settings()

# Asset paths
ASSETS_DIR = project_root / 'scripts' / 'assets'
PROMPTS_DIR = ASSETS_DIR / 'prompts'
FUNCTIONS_DIR = ASSETS_DIR / 'functions'
SCHEMA_DIR = ASSETS_DIR / 'schema'


class CosmosDataInitializer:
    """Handles Cosmos DB and Gremlin data initialization."""

    def __init__(self):
        self.cosmos_client = CosmosDBClient(settings.cosmos)
        self.gremlin_client = GremlinClient(settings.gremlin)

    async def initialize_all(self):
        """Run complete data initialization."""
        print("\n=== Cosmos DB Data Initialization ===\n")

        try:
            # Upload configuration data
            await self.upload_prompts()
            await self.upload_function_definitions()
            await self.upload_schema_metadata()

            # Upload demo graph data
            await self.upload_graph_data()

            print("\n✓ Data initialization completed successfully!")

        except Exception as e:
            print(f"\n✗ Data initialization failed: {e}")
            raise
        finally:
            if hasattr(self.cosmos_client, 'close'):
                await self.cosmos_client.close()
            if hasattr(self.gremlin_client, 'close'):
                await self.gremlin_client.close()

    async def upload_prompts(self):
        """Upload system prompts from assets directory."""
        print(">>> Uploading system prompts")

        if not PROMPTS_DIR.exists():
            print("  ⚠ Prompts directory not found, skipping")
            return

        count = 0
        for file_path in PROMPTS_DIR.glob("*"):
            if file_path.suffix not in ['.md', '.json']:
                continue

            try:
                content = file_path.read_text(encoding='utf-8')

                if file_path.suffix == '.json':
                    doc = json.loads(content)
                else:
                    # Markdown file - create prompt document
                    doc = {
                        'id': file_path.stem,
                        'agent_name': file_path.stem,
                        'type': 'system',
                        'content': content
                    }

                await self.cosmos_client.upsert_item(
                    container_name=settings.cosmos.prompts_container,
                    item=doc
                )
                print(f"  ✓ {file_path.name}")
                count += 1

            except Exception as e:
                print(f"  ✗ {file_path.name}: {e}")

        print(f"  Uploaded {count} prompts\n")

    async def upload_function_definitions(self):
        """Upload function/tool definitions from assets directory."""
        print(">>> Uploading function definitions")

        if not FUNCTIONS_DIR.exists():
            print("  ⚠ Functions directory not found, skipping")
            return

        count = 0

        # Upload tools
        tools_dir = FUNCTIONS_DIR / 'tools'
        if tools_dir.exists():
            for file_path in tools_dir.glob("*.json"):
                try:
                    data = json.loads(file_path.read_text())

                    # Ensure id field exists
                    if 'id' not in data and 'name' in data:
                        data['id'] = data['name']

                    if not data.get('id'):
                        print(f"  ✗ {file_path.name}: missing 'id' field")
                        continue

                    await self.cosmos_client.upsert_item(
                        container_name=settings.cosmos.agent_functions_container,
                        item=data
                    )
                    print(f"  ✓ Tool: {data['id']}")
                    count += 1

                except Exception as e:
                    print(f"  ✗ {file_path.name}: {e}")

        # Upload agents
        agents_dir = FUNCTIONS_DIR / 'agents'
        if agents_dir.exists():
            for file_path in agents_dir.glob("*.json"):
                try:
                    data = json.loads(file_path.read_text())

                    if 'id' not in data and 'name' in data:
                        data['id'] = data['name']

                    if not data.get('id'):
                        print(f"  ✗ {file_path.name}: missing 'id' field")
                        continue

                    await self.cosmos_client.upsert_item(
                        container_name=settings.cosmos.agent_functions_container,
                        item=data
                    )
                    print(f"  ✓ Agent: {data['id']}")
                    count += 1

                except Exception as e:
                    print(f"  ✗ {file_path.name}: {e}")

        print(f"  Uploaded {count} function definitions\n")

    async def upload_schema_metadata(self):
        """Upload SQL schema metadata from assets directory."""
        print(">>> Uploading SQL schema metadata")

        if not SCHEMA_DIR.exists():
            print("  ⚠ Schema directory not found, skipping")
            return

        count = 0
        for file_path in SCHEMA_DIR.glob("*.json"):
            try:
                schema_data = json.loads(file_path.read_text())

                if not isinstance(schema_data, list):
                    print(f"  ✗ {file_path.name}: not a JSON array")
                    continue

                # Upload each table definition
                for table_def in schema_data:
                    if not table_def.get('id'):
                        print(f"  ✗ Table in {file_path.name}: missing 'id' field")
                        continue

                    await self.cosmos_client.upsert_item(
                        container_name="sql_schema",
                        item=table_def
                    )
                    print(f"  ✓ Table: {table_def.get('table_name', table_def['id'])}")
                    count += 1

            except Exception as e:
                print(f"  ✗ {file_path.name}: {e}")

        print(f"  Uploaded {count} table schemas\n")

    async def upload_graph_data(self):
        """Upload demo graph data for testing."""
        print(">>> Uploading demo graph data")

        try:
            # Test Gremlin connectivity
            await self.gremlin_client.execute_query("g.V().limit(1)")
        except Exception as e:
            print(f"  ⚠ Gremlin not available: {e}")
            print("  Skipping graph data upload")
            return

        try:
            # Clear existing data (optional)
            clear = os.environ.get('INIT_DATA_CLEAR_GRAPH', 'true').lower() in ('1', 'true', 'yes')
            if clear:
                print("  Clearing existing graph data...")
                await self.gremlin_client.execute_query("g.E().drop()")
                await self.gremlin_client.execute_query("g.V().drop()")

            # Add accounts
            accounts = [
                {"id": "acc_microsoft", "name": "Microsoft Corporation", "tier": "Strategic", "industry": "Technology"},
                {"id": "acc_salesforce", "name": "Salesforce Inc", "tier": "Enterprise", "industry": "CRM Software"},
                {"id": "acc_google", "name": "Google LLC", "tier": "Strategic", "industry": "Technology"},
            ]

            for acc in accounts:
                query = f"""
                g.addV('account')
                .property('id','{acc["id"]}')
                .property('partitionKey','{acc["id"]}')
                .property('name','{acc["name"]}')
                .property('tier','{acc["tier"]}')
                .property('industry','{acc["industry"]}')
                """
                await self.gremlin_client.execute_query(query)
                print(f"  ✓ Account: {acc['name']}")

            print("  Uploaded demo graph data\n")

        except Exception as e:
            print(f"  ✗ Graph upload failed: {e}\n")


async def main():
    """Main entry point."""
    initializer = CosmosDataInitializer()
    await initializer.initialize_all()


if __name__ == "__main__":
    asyncio.run(main())
