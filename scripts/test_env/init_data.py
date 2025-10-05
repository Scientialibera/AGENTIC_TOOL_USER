#!/usr/bin/env python3
"""
Data initialization script for Salesforce Q&A Bot.

This script uploads prompts, functions, and dummy data to prepare
the system for testing and development.
"""

import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Dict, List, Any
import shutil
# This initializer will use the `az` CLI exclusively for resource provisioning.
# Do NOT attempt to use management SDKs or any key-based fallbacks. The
# environment must have Azure CLI installed and the user must be authenticated
# (e.g. `az login`) with a principal that has permission to create Cosmos DB
# resources in the target subscription/resource group.

# Add the agentic_framework directory to Python path
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
agentic_framework_dir = project_root / "agentic_framework"
sys.path.insert(0, str(agentic_framework_dir))
# Ensure working directory is repository root so .env is discovered by pydantic
os.chdir(project_root)

# Load repo-root .env into environment to ensure CONTAINER_APP_RESOURCE_GROUP and other
# variables are available even when running this script from other shells.
env_path = project_root / '.env'
if env_path.exists():
    try:
        with open(env_path, 'r', encoding='utf-8') as ef:
            for ln in ef:
                ln = ln.strip()
                if not ln or ln.startswith('#'):
                    continue
                if '=' not in ln:
                    continue
                k, v = ln.split('=', 1)
                # Only set if not already in environment to allow overrides
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        # Non-fatal; settings will still try to read env via pydantic
        pass

# --- Debug: print key env settings (masked) to help diagnose credential issues ---
def _mask(val: str) -> str:
    if not val:
        return '<missing>'
    if len(val) <= 8:
        return val[0] + '***'
    return val[:4] + '...' + val[-4:]

print('\n[init_data] Effective environment:')
print('  CONTAINER_APP_RESOURCE_GROUP =', os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP'))
print('  COSMOS_ENDPOINT =', os.environ.get('COSMOS_ENDPOINT') or os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT'))
print('  AZURE_COSMOS_GREMLIN_ENDPOINT =', os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT'))
print('  AZURE_COSMOS_GREMLIN_DATABASE =', os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE'))
print('  AZURE_COSMOS_GREMLIN_GRAPH =', os.environ.get('AZURE_COSMOS_GREMLIN_GRAPH'))
print('  MOCK_EMBEDDINGS =', os.environ.get('MOCK_EMBEDDINGS'))
print()
# ---------------------------------------------------------------

from shared.config import get_settings
from shared.cosmos_client import CosmosDBClient
from shared.gremlin_client import GremlinClient
from gremlin_python.driver.protocol import GremlinServerError
from tenacity import RetryError
import subprocess
import platform
import json
import time

# Initialize settings
settings = get_settings()

# Asset paths used by the uploader logic (previously in upload_artifacts.py)
ASSETS_PROMPTS = project_root / 'scripts' / 'assets' / 'prompts'
ASSETS_FUNCTIONS = project_root / 'scripts' / 'assets' / 'functions'
ASSETS_FUNCTIONS_TOOLS = ASSETS_FUNCTIONS / 'tools'
ASSETS_FUNCTIONS_AGENTS = ASSETS_FUNCTIONS / 'agents'
ASSETS_SCHEMA = project_root / 'scripts' / 'assets' / 'schema'


class DataInitializer:
    """Handles initialization of all system data."""
    
    def __init__(self):
        """Initialize the data initializer with Azure clients."""
        self.cosmos_client = CosmosDBClient(settings.cosmos)
        self.gremlin_client = GremlinClient(settings.gremlin)
        
    async def initialize_all(self):
        """Run complete data initialization."""
        print(" Starting data initialization for Salesforce Q&A Bot...")
        
        try:
            # Ensure required Cosmos containers exist (best-effort via az CLI)
            await self.ensure_cosmos_containers()
            # Ensure Gremlin graph exists (best-effort via az CLI). This will
            # attempt to create the Gremlin database and graph when the
            # CONTAINER_APP_RESOURCE_GROUP env var is set and the caller has
            # sufficient rights.
            await self.ensure_gremlin_graph()
            # After confirming the SQL and Gremlin services (or attempting to
            # create them), try to grant the executing principal the common
            # management and native data-plane roles needed to perform the
            # remaining initialization steps. This is best-effort and will
            # print actionable guidance when az or permissions are missing.
            try:
                # Use asyncio.to_thread to run the blocking CLI work in a
                # thread so we don't block the event loop.
                sql_endpoint = getattr(settings.cosmos, 'endpoint', None)
                # Prefer explicit env var for gremlin endpoint; fall back to
                # settings.gremlin.endpoint when available (avoid passing the
                # settings.gremlin object itself).
                gremlin_endpoint = os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT') or (getattr(settings, 'gremlin', None) and getattr(settings.gremlin, 'endpoint', None))
                # Extract account/db names used elsewhere in the script
                sql_db = getattr(settings.cosmos, 'database_name', None)
                gremlin_db = os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE') or getattr(settings.gremlin, 'database', None) or getattr(settings.gremlin, 'database_name', None)
                from asyncio import to_thread
                await to_thread(self._ensure_role_assignments_sync, sql_endpoint, sql_db, gremlin_endpoint, gremlin_db)
            except Exception as e:
                print(f"   Role-assignment attempt failed (continuing): {e}")
            # Initialize prompts/functions/agents using the uploader helper
            # This will provision required Cosmos DB database/containers via the
            # Azure CLI (AAD) and upload prompts and function/agent definitions
            # from `scripts/assets` in the repository. If the uploader helper is
            # unavailable we fall back to the local upload implementations.
            await self.upload_artifacts()
            
            # Initialize dummy graph data
            await self.upload_dummy_graph_data()
            
            print(" Data initialization completed successfully!")
            
        except Exception as e:
            print(f" Data initialization failed: {e}")
            raise
        finally:
            # Cleanup connections
            if hasattr(self.cosmos_client, 'close'):
                await self.cosmos_client.close()
            if hasattr(self.gremlin_client, 'close'):
                await self.gremlin_client.close()

    def _ensure_role_assignments_sync(self, sql_endpoint: str | None, sql_db: str | None, gremlin_endpoint: str | None, gremlin_db: str | None):
        """Best-effort: attempt to grant the executing principal management
        and native data-plane roles required for provisioning and data
        operations. This uses the Azure CLI (`az`) and intentionally does not
        raise on failures  it prints helpful guidance instead.
        """
        import shutil
        import subprocess
        import base64
        import json

        def print_hdr(msg: str):
            print(f"   {msg}")

        if not shutil.which('az'):
            print_hdr("Azure CLI ('az') not found in PATH; skipping role assignment step. Install Azure CLI and re-run this script to enable auto-role assignment.")
            return

        az = shutil.which('az')

        def run(cmd: list, timeout: int = 30):
            cmd0 = list(cmd)
            cmd0[0] = az
            try:
                res = subprocess.run(cmd0, capture_output=True, text=True, timeout=timeout, check=False)
                return res.returncode, res.stdout.strip(), res.stderr.strip()
            except subprocess.TimeoutExpired as e:
                return -1, '', f'Timeout after {timeout}s: {e}'

        # Try to discover the current principal object id. Prefer interactive
        # user identity, fallback to decoding the access token for the 'oid'.
        principal_oid = None
        rc, out, err = run([az, 'ad', 'signed-in-user', 'show', '--query', 'objectId', '-o', 'tsv'])
        if rc == 0 and out:
            principal_oid = out.strip()
            print_hdr(f"Detected signed-in user objectId: {principal_oid}")
        else:
            # Fallback: get an access token and decode its payload to read 'oid'
            rc2, out2, err2 = run([az, 'account', 'get-access-token', '--resource', 'https://management.azure.com/', '-o', 'json'])
            if rc2 == 0 and out2:
                try:
                    tok = json.loads(out2).get('accessToken')
                    if tok:
                        parts = tok.split('.')
                        if len(parts) >= 2:
                            payload = parts[1]
                            # base64url decode with padding
                            padding = '=' * (-len(payload) % 4)
                            decoded = base64.urlsafe_b64decode(payload + padding)
                            claims = json.loads(decoded)
                            principal_oid = claims.get('oid') or claims.get('sub')
                            if principal_oid:
                                print_hdr(f"Discovered principal oid from access token: {principal_oid}")
                except Exception:
                    pass

        if not principal_oid:
            print_hdr("Could not determine the current principal object id automatically. To assign roles manually, run the recommended az role assignment commands as described below.")
            print_hdr("Hint: run 'az ad signed-in-user show --query objectId -o tsv' to see the object id for your user, or use a service principal's object id.")
            return

        # Subscription id (for management role scopes)
        sub_id = None
        rc, out, err = run([az, 'account', 'show', '--query', 'id', '-o', 'tsv'])
        if rc == 0 and out:
            sub_id = out.strip()

        # If resource group isn't provided via env, try to discover it using
        # the account name(s) we have. This helps when the caller didn't set
        # CONTAINER_APP_RESOURCE_GROUP.
        rg = os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
        if not rg:
            # try to resolve by listing databaseAccounts that match the account
            def discover_rg_for_account(account_name: str | None):
                if not account_name:
                    return None
                rc2, out2, err2 = run([az, 'resource', 'list', '--resource-type', 'Microsoft.DocumentDB/databaseAccounts', '--query', f"[?contains(name, '{account_name}')]", '-o', 'json'], timeout=30)
                if rc2 == 0 and out2:
                    try:
                        arr = json.loads(out2)
                        if isinstance(arr, list) and len(arr) > 0:
                            return arr[0].get('resourceGroup')
                    except Exception:
                        return None
                return None

            # attempt discovery for SQL and Gremlin accounts
            if sql_endpoint:
                try:
                    sql_account_guess = sql_endpoint.replace('https://', '').split('.')[0]
                    rg = discover_rg_for_account(sql_account_guess)
                except Exception:
                    rg = None
            if not rg and gremlin_endpoint:
                try:
                    gr_account_guess = gremlin_endpoint.replace('https://', '').split('.')[0]
                    rg = discover_rg_for_account(gr_account_guess)
                except Exception:
                    rg = None

        # Helper to create a native data-plane role assignment (Cosmos built-in data contributor)
        data_role_id = '00000000-0000-0000-0000-000000000002'

        # SQL account assignment
        if sql_endpoint and sql_db:
            try:
                sql_account = sql_endpoint.replace('https://', '').split('.')[0]
                print_hdr(f"Attempting native data-plane role assignment for SQL account '{sql_account}', DB '{sql_db}'")
                cmd = [az, 'cosmosdb', 'sql', 'role', 'assignment', 'create', '--account-name', sql_account, '--resource-group', rg or '', '--scope', f"/dbs/{sql_db}", '--principal-id', principal_oid, '--role-definition-id', data_role_id, '-o', 'json']
                rc, out, err = run(cmd, timeout=30)
                if rc == 0:
                    print_hdr(f"   Native data-plane role assigned for SQL DB '/dbs/{sql_db}' on account '{sql_account}'.")
                else:
                    print_hdr(f"   Native data-plane assignment for SQL DB failed (rc={rc}). stdout={out} stderr={err}")
                    print_hdr("    -> Manual command to try (fill <RG> if empty):")
                    print_hdr(f"az cosmosdb sql role assignment create --account-name {sql_account} --resource-group <RG> --scope /dbs/{sql_db} --principal-id {principal_oid} --role-definition-id {data_role_id}")
            except Exception as e:
                print_hdr(f"   Exception while assigning data-plane role for SQL account: {e}")

            # Attempt a management-plane role assignment (DocumentDB Account Contributor) scoped to the account
            if sub_id:
                try:
                    if rg:
                        scope = f"/subscriptions/{sub_id}/resourceGroups/{rg}/providers/Microsoft.DocumentDB/databaseAccounts/{sql_account}"
                        cmd2 = [az, 'role', 'assignment', 'create', '--assignee-object-id', principal_oid, '--role', 'DocumentDB Account Contributor', '--scope', scope, '-o', 'json']
                        rc2, out2, err2 = run(cmd2, timeout=30)
                        if rc2 == 0:
                            print_hdr(f"   Management role 'DocumentDB Account Contributor' assigned on account '{sql_account}'.")
                        else:
                            print_hdr(f"   Management role assignment for SQL account failed (rc={rc2}). stdout={out2} stderr={err2}")
                            print_hdr("    -> Manual command to try:")
                            print_hdr(f"az role assignment create --assignee-object-id {principal_oid} --role \"DocumentDB Account Contributor\" --scope {scope}")
                    else:
                        print_hdr("   Skipping management role assignment because resource group/subscription couldn't be determined. Set CONTAINER_APP_RESOURCE_GROUP and re-run, or run the shown manual command.")
                except Exception as e:
                    print_hdr(f"   Exception while creating management role assignment for SQL account: {e}")

        # Gremlin account assignment
        if gremlin_endpoint and gremlin_db:
            try:
                gremlin_account = gremlin_endpoint.replace('https://', '').split('.')[0]
                print_hdr(f"Attempting native data-plane role assignment for Gremlin account '{gremlin_account}', DB '{gremlin_db}'")
                cmdg = [az, 'cosmosdb', 'sql', 'role', 'assignment', 'create', '--account-name', gremlin_account, '--resource-group', rg or '', '--scope', f"/dbs/{gremlin_db}", '--principal-id', principal_oid, '--role-definition-id', data_role_id, '-o', 'json']
                rcg, outg, errg = run(cmdg, timeout=30)
                if rcg == 0:
                    print_hdr(f"   Native data-plane role assigned for Gremlin DB '/dbs/{gremlin_db}' on account '{gremlin_account}'.")
                else:
                    print_hdr(f"   Native data-plane assignment for Gremlin DB failed (rc={rcg}). stdout={outg} stderr={errg}")
                    print_hdr("    -> Manual command to try (fill <RG> if empty):")
                    print_hdr(f"az cosmosdb sql role assignment create --account-name {gremlin_account} --resource-group <RG> --scope /dbs/{gremlin_db} --principal-id {principal_oid} --role-definition-id {data_role_id}")
            except Exception as e:
                print_hdr(f"   Exception while assigning data-plane role for Gremlin account: {e}")

            # Management-plane assignment for gremlin account
            if sub_id:
                try:
                    if rg:
                        scopeg = f"/subscriptions/{sub_id}/resourceGroups/{rg}/providers/Microsoft.DocumentDB/databaseAccounts/{gremlin_account}"
                        cmd3 = [az, 'role', 'assignment', 'create', '--assignee-object-id', principal_oid, '--role', 'DocumentDB Account Contributor', '--scope', scopeg, '-o', 'json']
                        rc3, out3, err3 = run(cmd3, timeout=30)
                        if rc3 == 0:
                            print_hdr(f"   Management role 'DocumentDB Account Contributor' assigned on account '{gremlin_account}'.")
                        else:
                            print_hdr(f"   Management role assignment for Gremlin account failed (rc={rc3}). stdout={out3} stderr={err3}")
                            print_hdr("    -> Manual command to try:")
                            print_hdr(f"az role assignment create --assignee-object-id {principal_oid} --role \"DocumentDB Account Contributor\" --scope {scopeg}")
                    else:
                        print_hdr("   Skipping management role assignment because resource group/subscription couldn't be determined. Set CONTAINER_APP_RESOURCE_GROUP and re-run, or run the shown manual command.")
                except Exception as e:
                    print_hdr(f"   Exception while creating management role assignment for Gremlin account: {e}")

        print_hdr("Role-assignment best-effort step completed. If you still see permission errors, restart processes that cache AAD tokens and re-run this script. For manual remediation, see printed CLI failures above.")
    
    async def upload_prompts(self):
        """Upload system prompts to Cosmos DB."""
        print(" Uploading system prompts...")
        
        # Load prompts from prompts/ folder. Fallback to repository assets if present.
        prompts_dir = Path(__file__).parent / "prompts"
        if not prompts_dir.exists():
            # fallback to scripts/assets/prompts
            alt = project_root / "scripts" / "assets" / "prompts"
            if alt.exists():
                prompts_dir = alt
            else:
                print("  Prompts directory not found, skipping prompt upload")
                return
        
        for prompt_file in prompts_dir.glob("*.json"):
            try:
                with open(prompt_file, 'r') as f:
                    prompt_data = json.load(f)
                
                # Upload to prompts container
                await self.cosmos_client.upsert_item(
                    container_name=settings.cosmos_db.prompts_container,
                    item=prompt_data
                )
                
                print(f"   Uploaded prompt: {prompt_data['id']}")
                
            except Exception as e:
                print(f"   Failed to upload {prompt_file.name}: {e}")
    
    async def upload_functions(self):
        """Upload function definitions to Cosmos DB."""
        print(" Uploading function definitions...")
        
        # Load functions from functions/ folder. Fallback to repository assets if present.
        functions_dir = Path(__file__).parent / "functions"
        if not functions_dir.exists():
            alt = project_root / "scripts" / "assets" / "functions"
            if alt.exists():
                functions_dir = alt
            else:
                print("  Functions directory not found, skipping function upload")
                return
        
        for function_file in functions_dir.glob("*.json"):
            try:
                with open(function_file, 'r') as f:
                    function_data = json.load(f)
                
                # Upload to agent_functions container
                await self.cosmos_client.upsert_item(
                    container_name=settings.cosmos_db.agent_functions_container,
                    item=function_data
                )
                
                print(f"   Uploaded functions: {function_data['id']}")
                
            except Exception as e:
                print(f"   Failed to upload {function_file.name}: {e}")

    async def upload_artifacts(self):
        """Use the repository uploader script to provision Cosmos and upload artifacts.

        Consolidated uploader: previously this delegated to
        `scripts/test_env/upload_artifacts.py`. That module has been removed
        and its provisioning/upload logic is embedded here to ensure a single
        entrypoint and remove duplication.
        """
        print(" Uploading prompts and functions via repository uploader...")
        # Essential containers for simplified architecture
        containers = [
            settings.cosmos.chat_container,        # Unified session/message/feedback storage
            settings.cosmos.prompts_container,     # System prompts
            settings.cosmos.agent_functions_container,  # Function definitions
            "sql_schema",  # Schema metadata (hardcoded for now)
        ]

        # Provision Cosmos resources using az CLI (best-effort)
        try:
            self._provision_cosmos_via_az(settings.cosmos.endpoint, settings.cosmos.database_name, containers)
        except Exception as e:
            print(f"   Provisioning step failed or skipped: {e}")

        # Run uploader logic: upload prompts, functions, and schema from scripts/assets
        try:
            await self._uploader_upload_prompts()
            await self._uploader_upload_functions()
            await self._uploader_upload_schema()
            print("   Uploader completed prompts, functions, and schema upload.")
        except Exception as e:
            print(f"   Uploader failed during upload steps: {e}")
            raise

    def _provision_cosmos_via_az(self, endpoint: str, database: str, containers: list, resource_group: str | None = None):
        """Best-effort: use Azure CLI to create database and containers using AAD credentials.

        This mirrors the behavior previously implemented in
        `scripts/test_env/upload_artifacts.py`. It requires `az` in PATH and an
        authenticated principal. It will print actionable errors if CLI is
        missing or permissions are insufficient.
        """
        # endpoint looks like https://<account>.documents.azure.com
        try:
            account = endpoint.replace('https://', '').split('.')[0]
        except Exception:
            print('Could not parse Cosmos account name from endpoint', endpoint)
            return

        rg = resource_group or os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
        if not rg:
            # try to discover via az
            try:
                res = subprocess.run(['az','resource','list','--resource-type','Microsoft.DocumentDB/databaseAccounts','--query','[?contains(name, `'+account+'`)]','-o','json'], capture_output=True, text=True, check=False)
                if res.returncode == 0 and res.stdout:
                    data = json.loads(res.stdout)
                    if isinstance(data, list) and len(data) > 0:
                        rg = data[0].get('resourceGroup')
            except Exception:
                rg = None

        if not rg:
            print('Could not detect resource group for Cosmos account', account, ' skipping az provisioning. Provide CONTAINER_APP_RESOURCE_GROUP to enable provisioning.')
            return

        if not shutil.which('az'):
            print("ERROR: Azure CLI ('az') was not found in PATH. Skipping provisioning.")
            return

        az_exe = shutil.which('az')

        def run_az(cmd: List[str], timeout: int = 30):
            cmd0 = list(cmd)
            cmd0[0] = az_exe
            try:
                res = subprocess.run(cmd0, check=False, capture_output=True, text=True, timeout=timeout)
                return res.returncode, res.stdout, res.stderr
            except subprocess.TimeoutExpired as e:
                return -1, '', f'Timeout after {timeout}s: {e}'

        # Ensure database exists
        rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'database', 'show', '--account-name', account, '--resource-group', rg, '--name', database], timeout=20)
        if rc == 0:
            print(f"   Cosmos SQL database '{database}' already exists.")
        else:
            print(f"   Creating Cosmos SQL database '{database}' (account={account}, rg={rg})")
            rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'database', 'create', '--account-name', account, '--resource-group', rg, '--name', database], timeout=60)
            if rc != 0:
                print(f"    ERROR creating database: rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"     Created database '{database}'.")

        # Ensure containers
        for c in containers:
            if not c:
                continue
            print(f"   Ensuring container '{c}' in DB '{database}'...")
            rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'container', 'show', '--account-name', account, '--resource-group', rg, '--database-name', database, '--name', c], timeout=20)
            if rc == 0:
                print(f"     Cosmos container '{c}' already exists in DB '{database}'.")
                continue
            print(f"     Creating Cosmos container '{c}' in DB '{database}'")
            rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'container', 'create', '--account-name', account, '--resource-group', rg, '--database-name', database, '--name', c, '--partition-key-path', '/id', '--throughput', '400'], timeout=60)
            if rc != 0:
                print(f"      ERROR creating container '{c}': rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"       Created container '{c}'.")

    async def _uploader_upload_prompts(self):
        """Upload prompts from `scripts/assets/prompts`."""
        print('Uploading prompts from assets...')
        if not ASSETS_PROMPTS.exists():
            print('   No prompts assets directory found at', ASSETS_PROMPTS)
            return
        for fname in os.listdir(ASSETS_PROMPTS):
            if not str(fname).endswith('.md') and not str(fname).endswith('.json'):
                continue
            path = ASSETS_PROMPTS / fname
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # If JSON, parse and upload as object; if MD, upload as system prompt
                if fname.endswith('.json'):
                    data = json.loads(content)
                    await self.cosmos_client.upsert_item(
                        container_name=settings.cosmos.prompts_container,
                        item=data
                    )
                    print('   Uploaded prompt (json):', fname)
                else:
                    # MD file - create a prompt document
                    agent_name = Path(fname).stem
                    prompt_doc = {
                        'id': agent_name,
                        'agent_name': agent_name,
                        'type': 'system',
                        'content': content
                    }
                    await self.cosmos_client.upsert_item(
                        container_name=settings.cosmos.prompts_container,
                        item=prompt_doc
                    )
                    print('   Uploaded prompt (md):', fname)
            except Exception as e:
                print('   Failed to upload prompt', fname, 'error:', e)

    async def _uploader_upload_functions(self):
        """Upload function/tool/agent definitions from `scripts/assets/functions`."""
        print('Uploading function definitions from assets...')
        # Tools
        if ASSETS_FUNCTIONS_TOOLS.exists():
            for fname in os.listdir(ASSETS_FUNCTIONS_TOOLS):
                if not str(fname).endswith('.json'):
                    continue
                path = ASSETS_FUNCTIONS_TOOLS / fname
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # Ensure the document has an 'id' field
                    if 'id' not in data and 'name' in data:
                        data['id'] = data['name']

                    if not data.get('id'):
                        print(f'   Tool file {fname} missing "id" or "name" field, skipping')
                        continue

                    await self.cosmos_client.upsert_item(
                        container_name=settings.cosmos.agent_functions_container,
                        item=data
                    )
                    print('   Uploaded tool function:', data['id'])
                except Exception as e:
                    print('   Failed to upload tool file', fname, 'error:', e)

        # Agents
        if ASSETS_FUNCTIONS_AGENTS.exists():
            for fname in os.listdir(ASSETS_FUNCTIONS_AGENTS):
                if not str(fname).endswith('.json'):
                    continue
                path = ASSETS_FUNCTIONS_AGENTS / fname
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # Ensure the document has an 'id' field
                    if 'id' not in data and 'name' in data:
                        data['id'] = data['name']

                    if not data.get('id'):
                        print(f'   Agent file {fname} missing "id" or "name" field, skipping')
                        continue

                    await self.cosmos_client.upsert_item(
                        container_name=settings.cosmos.agent_functions_container,
                        item=data
                    )
                    print('   Uploaded agent registration:', data['id'])
                except Exception as e:
                    print('   Failed to upload agent file', fname, 'error:', e)

    async def _uploader_upload_schema(self):
        """Upload SQL schema definitions from `scripts/assets/schema`."""
        print('Uploading SQL schema definitions from assets...')
        if not ASSETS_SCHEMA.exists():
            print('   No schema assets directory found at', ASSETS_SCHEMA)
            return

        for fname in os.listdir(ASSETS_SCHEMA):
            if not str(fname).endswith('.json'):
                continue
            path = ASSETS_SCHEMA / fname
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    schema_data = json.load(f)

                # schema_data should be an array of table definitions
                if not isinstance(schema_data, list):
                    print(f'   Schema file {fname} is not a JSON array, skipping')
                    continue

                # Upload each table definition to sql_schema container
                for table_def in schema_data:
                    table_id = table_def.get('id')
                    if not table_id:
                        print(f'   Table definition in {fname} missing "id" field, skipping')
                        continue

                    await self.cosmos_client.upsert_item(
                        container_name="sql_schema",
                        item=table_def
                    )
                    print(f'   Uploaded schema for table: {table_def.get("table_name", table_id)}')

            except Exception as e:
                print('   Failed to upload schema file', fname, 'error:', e)

    async def upload_dummy_graph_data(self):
        """Upload demo graph data: accounts, SOWs, offerings, and technology stack (no extra noise)."""
        print("  Uploading demo graph data (accounts, sows, offerings, tech)...")

        # 1) Availability probe
        try:
            await self.gremlin_client.execute_query("g.V().limit(1)")
        except (RetryError, GremlinServerError, Exception) as e:
            inner = e
            if isinstance(e, RetryError) and hasattr(e, 'last_attempt'):
                try:
                    inner = e.last_attempt.exception()
                except Exception:
                    inner = e
            msg = str(inner)
            if ("DefaultAzureCredential failed" in msg
                or "Unable to get authority configuration" in msg
                or "credential" in msg.lower()):
                print("  Gremlin auth failed (DefaultAzureCredential). Skipping graph upload.")
                print("   -> Ensure you're logged in (az login) or running with a managed identity that has data-plane access to Cosmos DB.")
                return
            if "NotFound" in msg or "404" in msg:
                print("  Gremlin graph/collection not found. Skipping graph upload.")
                print("   -> Create the Gremlin graph (relationships) or run scripts/infra/deploy.ps1 and re-run this initializer.")
                return
            print(f"  Gremlin check failed: {inner}")
            return

        try:
            # 2) Clear graph (opt-in via env)
            init_clear = os.environ.get('INIT_DATA_CLEAR_GRAPH', 'true').lower() in ('1', 'true', 'yes')
            if init_clear:
                print("   Clearing existing graph data (INIT_DATA_CLEAR_GRAPH=true)...")
                await self.gremlin_client.execute_query("g.E().drop()")
                await self.gremlin_client.execute_query("g.V().drop()")

            # 3) Accounts (normalized numerics)
            accounts = [
                {
                    "id": "acc_salesforce",
                    "name": "Salesforce Inc",
                    "type": "CRM",
                    "tier": "Enterprise",
                    "industry": "Technology",
                    "revenue": 34100000000.0,   # 34.1B -> numeric
                    "employees": 79000,
                    "status": "Active Customer",
                    "contract_value": 2500000.0, # 2.5M -> numeric
                    "renewal_date": "2025-03-15"
                },
                {
                    "id": "acc_microsoft",
                    "name": "Microsoft Corporation",
                    "type": "Enterprise Software",
                    "tier": "Strategic",
                    "industry": "Technology",
                    "revenue": 245100000000.0,
                    "employees": 221000,
                    "status": "Prospect",
                    "contract_value": 0.0,
                    "renewal_date": None
                },
                {
                    "id": "acc_oracle",
                    "name": "Oracle Corporation",
                    "type": "Database",
                    "tier": "Enterprise",
                    "industry": "Technology",
                    "revenue": 52900000000.0,
                    "employees": 164000,
                    "status": "Active Customer",
                    "contract_value": 1800000.0,
                    "renewal_date": "2024-11-30"
                },
                {
                    "id": "acc_aws",
                    "name": "Amazon Web Services",
                    "type": "Cloud Infrastructure",
                    "tier": "Competitor",
                    "industry": "Cloud Computing",
                    "revenue": 90000000000.0,
                    "employees": 1600000,
                    "status": "Competitor",
                    "contract_value": 0.0,
                    "renewal_date": None
                },
                {
                    "id": "acc_google",
                    "name": "Google LLC",
                    "type": "Cloud Services",
                    "tier": "Competitor",
                    "industry": "Technology",
                    "revenue": 307400000000.0,
                    "employees": 190000,
                    "status": "Competitor",
                    "contract_value": 0.0,
                    "renewal_date": None
                },
                {
                    "id": "acc_sap",
                    "name": "SAP SE",
                    "type": "ERP",
                    "tier": "Enterprise",
                    "industry": "Enterprise Software",
                    "revenue": 33800000000.0,
                    "employees": 111000,
                    "status": "Prospect",
                    "contract_value": 0.0,
                    "renewal_date": None
                }
            ]

            for a in accounts:
                q = f"""
                g.addV('account')
                .property('id','{a["id"]}')
                .property('partitionKey','{a["id"]}')
                .property('name','{a["name"]}')
                .property('type','{a["type"]}')
                .property('tier','{a["tier"]}')
                .property('industry','{a["industry"]}')
                .property('revenue',{a["revenue"]})
                .property('employees',{a["employees"]})
                .property('status','{a["status"]}')
                .property('contract_value',{a["contract_value"]})
                .property('renewal_date','{a["renewal_date"] or ""}')
                """
                await self.gremlin_client.execute_query(q)
                print(f"   Added account: {a['name']}")

            # 4) Offerings (promoted to vertices)
            offerings = [
                {"id": "off_ai_chatbot",       "name": "ai_chatbot",        "category": "AI"},
                {"id": "off_fabric_deployment","name": "fabric_deployment", "category": "Data"},
                {"id": "off_dynamics",         "name": "dynamics",          "category": "CRM"},
                {"id": "off_data_migration",   "name": "data_migration",    "category": "Data"}
            ]
            for o in offerings:
                q = f"""
                g.addV('offering')
                .property('id','{o['id']}')
                .property('partitionKey','{o['id']}')
                .property('name','{o['name']}')
                .property('category','{o['category']}')
                """
                await self.gremlin_client.execute_query(q)
            print("   Added offering vertices.")

            # 5) Technology stack
            techs = [
                {"id":"tech_azure_openai","name":"Azure OpenAI","category":"LLM"},
                {"id":"tech_aws_bedrock","name":"AWS Bedrock","category":"LLM"},
                {"id":"tech_gcp_dialogflow","name":"Google Dialogflow","category":"Conversational"},
                {"id":"tech_ms_teams","name":"Microsoft Teams","category":"Collaboration"},
                {"id":"tech_servicenow","name":"ServiceNow","category":"ITSM"},
                {"id":"tech_twilio","name":"Twilio","category":"Comms"},
                {"id":"tech_ms_fabric","name":"Microsoft Fabric","category":"Data"},
                {"id":"tech_snowflake","name":"Snowflake","category":"Data"},
                {"id":"tech_databricks","name":"Databricks","category":"Data"},
                {"id":"tech_ms_dynamics","name":"Microsoft Dynamics 365","category":"CRM"}
            ]
            for t in techs:
                q = f"""
                g.addV('tech')
                .property('id','{t['id']}')
                .property('partitionKey','{t['id']}')
                .property('name','{t['name']}')
                .property('category','{t['category']}')
                """
                await self.gremlin_client.execute_query(q)
            print("   Added tech vertices.")

            # 6) SOWs (keep offering as a property for convenience, but we also link to offering vertex)
            sows = [
                {"id":"sow_msft_ai_chatbot_2023",       "account":"acc_microsoft",  "title":"Microsoft AI Chatbot PoC",            "offering":"ai_chatbot",        "year":2023, "value":250000},
                {"id":"sow_salesforce_ai_chatbot_2023", "account":"acc_salesforce", "title":"Salesforce Service Chatbot Rollout",  "offering":"ai_chatbot",        "year":2023, "value":300000},
                {"id":"sow_google_ai_chatbot_2024",     "account":"acc_google",     "title":"Google Customer Support Chatbot",     "offering":"ai_chatbot",        "year":2024, "value":410000},
                {"id":"sow_aws_ai_chatbot_2022",        "account":"acc_aws",        "title":"AWS Internal Helpdesk Bot",           "offering":"ai_chatbot",        "year":2022, "value":150000},
                {"id":"sow_sap_ai_chatbot_2023",        "account":"acc_sap",        "title":"SAP Field Service Chatbot",           "offering":"ai_chatbot",        "year":2023, "value":210000},

                {"id":"sow_msft_fabric_2024",           "account":"acc_microsoft",  "title":"Microsoft Fabric Deployment",         "offering":"fabric_deployment", "year":2024, "value":560000},
                {"id":"sow_salesforce_dynamics_2022",   "account":"acc_salesforce", "title":"Salesforce Dynamics Integration",      "offering":"dynamics",          "year":2022, "value":180000},
                {"id":"sow_oracle_migration_2024",      "account":"acc_oracle",     "title":"Oracle Data Migration",                "offering":"data_migration",    "year":2024, "value":320000},
                {"id":"sow_sap_fabric_2023",            "account":"acc_sap",        "title":"SAP Fabric Proof of Value",            "offering":"fabric_deployment", "year":2023, "value":120000},
            ]
            # offering name -> offering vertex id
            offering_id_by_name = {o["name"]: o["id"] for o in offerings}

            for sow in sows:
                title_escaped = sow["title"].replace('"', '\\"')
                q = f"""
                g.addV('sow')
                .property('id','{sow['id']}')
                .property('partitionKey','{sow['id']}')
                .property('title',"{title_escaped}")
                .property('offering','{sow['offering']}')
                .property('year',{sow['year']})
                .property('value',{sow['value']})
                """
                await self.gremlin_client.execute_query(q)

                # account -> sow
                link_q = f"""
                g.V('{sow['account']}')
                .addE('has_sow')
                .to(g.V('{sow['id']}'))
                .property('role','contract')
                """
                await self.gremlin_client.execute_query(link_q)

                # sow -> offering vertex
                off_id = offering_id_by_name[sow["offering"]]
                off_q = f"g.V('{sow['id']}').addE('has_offering').to(g.V('{off_id}'))"
                await self.gremlin_client.execute_query(off_q)

            print("   Added SOWs and linked offerings.")

            # 7) Account-level tech signals
            account_tech = {
                "acc_microsoft":  ["tech_ms_teams","tech_ms_fabric","tech_azure_openai","tech_ms_dynamics"],
                "acc_salesforce": ["tech_servicenow","tech_twilio","tech_aws_bedrock","tech_ms_dynamics"],
                "acc_google":     ["tech_gcp_dialogflow","tech_snowflake"],
                "acc_aws":        ["tech_aws_bedrock","tech_twilio"],
                "acc_oracle":     ["tech_databricks","tech_snowflake"],
                "acc_sap":        ["tech_servicenow","tech_ms_fabric"]
            }
            for acc_id, tech_ids in account_tech.items():
                for tid in tech_ids:
                    q = f"g.V('{acc_id}').addE('uses_tech').to(g.V('{tid}')).property('scope','org').property('confidence',0.8)"
                    await self.gremlin_client.execute_query(q)
            print("   Linked accounts to org-level tech stack.")

            # 8) SOW-level tech usage
            sow_tech = {
                "sow_msft_ai_chatbot_2023":      ["tech_azure_openai","tech_ms_teams"],
                "sow_salesforce_ai_chatbot_2023":["tech_aws_bedrock","tech_twilio","tech_servicenow"],
                "sow_google_ai_chatbot_2024":    ["tech_gcp_dialogflow","tech_twilio"],
                "sow_aws_ai_chatbot_2022":       ["tech_aws_bedrock"],
                "sow_sap_ai_chatbot_2023":       ["tech_azure_openai","tech_servicenow"],
                "sow_msft_fabric_2024":          ["tech_ms_fabric"],
                "sow_salesforce_dynamics_2022":  ["tech_ms_dynamics","tech_twilio"],
                "sow_oracle_migration_2024":     ["tech_snowflake","tech_databricks"],
                "sow_sap_fabric_2023":           ["tech_ms_fabric"]
            }
            for sow_id, tech_ids in sow_tech.items():
                for tid in tech_ids:
                    q = f"g.V('{sow_id}').addE('uses_tech').to(g.V('{tid}')).property('scope','project').property('confidence',0.9)"
                    await self.gremlin_client.execute_query(q)
            print("   Linked SOWs to project-level tech.")

            # 9) SOW similarity (unchanged)
            sow_similarities = [
                {"a":"sow_msft_ai_chatbot_2023","b":"sow_salesforce_ai_chatbot_2023","score":0.85,"note":"enterprise support chatbots"},
                {"a":"sow_msft_ai_chatbot_2023","b":"sow_google_ai_chatbot_2024","score":0.80,"note":"customer service chatbots"},
                {"a":"sow_salesforce_ai_chatbot_2023","b":"sow_aws_ai_chatbot_2022","score":0.70,"note":"IT/helpdesk assistant"},
                {"a":"sow_google_ai_chatbot_2024","b":"sow_sap_ai_chatbot_2023","score":0.65,"note":"multilingual bot UX"},
                {"a":"sow_aws_ai_chatbot_2022","b":"sow_sap_ai_chatbot_2023","score":0.60,"note":"FAQ intent modeling overlap"},
                {"a":"sow_msft_ai_chatbot_2023","b":"sow_salesforce_dynamics_2022","score":0.60,"note":"conversational integration"},
                {"a":"sow_msft_fabric_2024","b":"sow_sap_fabric_2023","score":0.80,"note":"Fabric deployments"},
                {"a":"sow_oracle_migration_2024","b":"sow_salesforce_dynamics_2022","score":0.40,"note":"data migration overlap"},
            ]
            for sim in sow_similarities:
                q = f"""
                g.V('{sim['a']}')
                .addE('similar_to')
                .to(g.V('{sim['b']}'))
                .property('score',{sim['score']})
                .property('note',"{sim['note']}")
                """
                await self.gremlin_client.execute_query(q)
            print("   Linked similar SOWs.")

            print("   Graph data upload completed.")

        except (RetryError, GremlinServerError) as e:
            inner = e
            if isinstance(e, RetryError) and hasattr(e, 'last_attempt'):
                try:
                    inner = e.last_attempt.exception()
                except Exception:
                    inner = e
            print(f"    Gremlin server error while uploading graph data: {inner}")
            print("   -> If this is a NotFound error, ensure the Gremlin graph/collection exists. See scripts/infra/deploy.ps1.")
            return
        except Exception as e:
            print(f"   Failed to upload graph data: {e}")
            raise


    async def ensure_cosmos_containers(self):
        """Best-effort creation of Cosmos DB SQL containers using az CLI.

        This uses the `az` CLI with AAD credentials. If the current principal
        lacks the necessary management permissions this will warn and continue.
        We create the chat history container here so init_data can be used to
        fully prepare a dev environment.
        """
        rg = os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
        if not rg:
            print("  CONTAINER_APP_RESOURCE_GROUP not set in environment; skipping Cosmos container provisioning.")
            return

        cos_end = settings.cosmos.endpoint
        if not cos_end:
            print("  COSMOS_ENDPOINT not configured in settings; skipping container creation.")
            return

        # Extract account name from endpoint (https://{account}.documents.azure.com)
        acct = cos_end.replace('https://', '').split('.')[0]
        db_name = settings.cosmos.database_name
        # Essential containers for unified Cosmos DB storage
        container_fields = [
            'chat_container',  # Unified container for sessions, messages, cache, feedback
            'agent_functions_container',  # Agent and tool function definitions
            'prompts_container',  # System prompts
        ]
        containers = []
        for f in container_fields:
            val = getattr(settings.cosmos, f, None)
            if val:
                containers.append(val)

        # Add sql_schema container
        containers.append("sql_schema")

        if not acct or not db_name or not containers:
            print("  Insufficient Cosmos settings to create container; skipping.")
            return

        print(f" Ensuring Cosmos containers exist in DB '{db_name}' on account '{acct}' (rg: {rg}) using Azure CLI (required)")

        import subprocess
        import shutil

        if not shutil.which("az"):
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            # Exit cleanly with non-zero status so CI/automation can detect failure without a stacktrace
            sys.exit(2)

        az_exe = shutil.which("az")
        if not az_exe:
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            sys.exit(2)

        def run_az_command(cmd: List[str], timeout: int = 30):
            """Run az command using absolute az executable, return (rc, stdout, stderr).

            We use a small timeout to avoid hangs; caller should handle non-zero rc.
            """
            cmd0 = list(cmd)
            cmd0[0] = az_exe
            try:
                res = subprocess.run(cmd0, check=False, capture_output=True, text=True, timeout=timeout)
                return res.returncode, res.stdout, res.stderr
            except subprocess.TimeoutExpired as e:
                return -1, "", f"Timeout after {timeout}s: {e}"

        # Check if database exists first
        show_db_cmd = [
            "az", "cosmosdb", "sql", "database", "show",
            "--account-name", acct,
            "--resource-group", rg,
            "--name", db_name,
        ]
        rc, out, err = run_az_command(show_db_cmd, timeout=20)
        if rc == 0:
            print(f"   Cosmos SQL database '{db_name}' already exists.")
        else:
            print(f"   Creating Cosmos SQL database '{db_name}' (account={acct}, rg={rg})")
            create_db_cmd = [
                "az", "cosmosdb", "sql", "database", "create",
                "--account-name", acct,
                "--resource-group", rg,
                "--name", db_name,
            ]
            rc, out, err = run_az_command(create_db_cmd, timeout=60)
            if rc != 0:
                print(f"    ERROR creating database: rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"     Created database '{db_name}'.")

        # Iterate through configured containers and ensure each exists
        for container_name in containers:
            print(f"   Ensuring container '{container_name}' in DB '{db_name}'...")
            show_cont_cmd = [
                "az", "cosmosdb", "sql", "container", "show",
                "--account-name", acct,
                "--resource-group", rg,
                "--database-name", db_name,
                "--name", container_name,
            ]
            rc, out, err = run_az_command(show_cont_cmd, timeout=20)
            if rc == 0:
                print(f"     Cosmos container '{container_name}' already exists in DB '{db_name}'.")
                continue

            print(f"     Creating Cosmos container '{container_name}' in DB '{db_name}'")
            create_cont_cmd = [
                "az", "cosmosdb", "sql", "container", "create",
                "--account-name", acct,
                "--resource-group", rg,
                "--database-name", db_name,
                "--name", container_name,
                "--partition-key-path", "/id",
                "--throughput", "400",
            ]
            rc, out, err = run_az_command(create_cont_cmd, timeout=60)
            if rc != 0:
                print(f"      ERROR creating container '{container_name}': rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"       Created container '{container_name}'.")

    async def ensure_gremlin_graph(self):
        """Best-effort creation of Gremlin database and graph using az CLI.

        This follows the same pattern as `ensure_cosmos_containers` and will
        quietly continue if the environment lacks the resource group var or
        if the az CLI call fails due to permissions.
        """
        rg = os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
        if not rg:
            print("  CONTAINER_APP_RESOURCE_GROUP not set in environment; skipping Gremlin provisioning.")
            return

        gremlin_endpoint = os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT') or settings.gremlin.endpoint
        gremlin_db = os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE') or getattr(settings.gremlin, 'database', None) or getattr(settings.gremlin, 'database_name', None)
        gremlin_graph = os.environ.get('AZURE_COSMOS_GREMLIN_GRAPH') or getattr(settings.gremlin, 'graph', None) or getattr(settings.gremlin, 'graph_name', None)

        # If the configured graph name is the legacy or incorrect 'relationships',
        # prefer the known graph/container name 'account_graph' and prefer the
        # Gremlin database named 'graphdb' which is used in our deployments.
        if gremlin_graph and gremlin_graph.lower().startswith('relationship'):
            print(f"   Found legacy Gremlin graph name '{gremlin_graph}'; preferring 'account_graph' as the graph name.")
            gremlin_graph = 'account_graph'

        if not gremlin_endpoint or not gremlin_db or not gremlin_graph:
            print("  Insufficient Gremlin settings to create graph; skipping.")
            return

        # Extract account name from endpoint
        acct = gremlin_endpoint.replace('https://', '').split('.')[0]

        print(f" Creating Gremlin database '{gremlin_db}' and graph '{gremlin_graph}' on account '{acct}' (rg: {rg}) using Azure CLI (required)")

        import subprocess
        import shutil

        if not shutil.which("az"):
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            sys.exit(2)

        az_exe = shutil.which("az")
        if not az_exe:
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            sys.exit(2)

        def run_az_command(cmd: List[str], timeout: int = 30):
            cmd0 = list(cmd)
            cmd0[0] = az_exe
            try:
                res = subprocess.run(cmd0, check=False, capture_output=True, text=True, timeout=timeout)
                return res.returncode, res.stdout, res.stderr
            except subprocess.TimeoutExpired as e:
                return -1, "", f"Timeout after {timeout}s: {e}"

        # Check if gremlin database exists (use gremlin subcommand)
        show_db_cmd = [
            "az", "cosmosdb", "gremlin", "database", "show",
            "--account-name", acct,
            "--resource-group", rg,
            "--name", gremlin_db,
        ]
        rc, out, err = run_az_command(show_db_cmd, timeout=20)
        if rc == 0:
            print(f"   Gremlin database '{gremlin_db}' already exists.")
        else:
            print(f"   Creating Gremlin database '{gremlin_db}' (account={acct}, rg={rg})")
            create_db_cmd = [
                "az", "cosmosdb", "gremlin", "database", "create",
                "--account-name", acct,
                "--resource-group", rg,
                "--name", gremlin_db,
            ]
            rc, out, err = run_az_command(create_db_cmd, timeout=60)
            if rc != 0:
                print(f"    ERROR creating gremlin database: rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"     Created gremlin database '{gremlin_db}'.")

        # Check if graph exists
        show_graph_cmd = [
            "az", "cosmosdb", "gremlin", "graph", "show",
            "--account-name", acct,
            "--resource-group", rg,
            "--database-name", gremlin_db,
            "--name", gremlin_graph,
        ]
        rc, out, err = run_az_command(show_graph_cmd, timeout=20)
        if rc == 0:
            print(f"   Gremlin graph '{gremlin_graph}' already exists in DB '{gremlin_db}'.")
        else:
            # The configured graph was not found. Try a small set of sensible
            # existing names to handle common naming mismatches (e.g. using
            # `account_graph` instead of `relationships`). This is conservative
            # and only tries explicit alternatives rather than broad heuristics.
            print(f"   Gremlin graph '{gremlin_graph}' not found in DB '{gremlin_db}' (rc={rc}). Checking common alternatives...")
            tried = []
            # Try common alternative database/graph name pairs. We prefer
            # ('graphdb', 'account_graph') because our infra uses `graphdb`
            # as the Gremlin database and `account_graph` as the graph/collection.
            alternatives = [
                (gremlin_db, 'account_graph'),
                ('graphdb', 'account_graph'),
                ('account_graph', gremlin_graph),
                ('account_graph', 'account_graph'),
            ]
            found = False
            for alt_db, alt_graph in alternatives:
                if (alt_db, alt_graph) in tried:
                    continue
                tried.append((alt_db, alt_graph))
                alt_show = [
                    "az", "cosmosdb", "gremlin", "graph", "show",
                    "--account-name", acct,
                    "--resource-group", rg,
                    "--database-name", alt_db,
                    "--name", alt_graph,
                ]
                rc2, out2, err2 = run_az_command(alt_show, timeout=20)
                if rc2 == 0:
                    print(f"     Found existing Gremlin graph '{alt_graph}' in DB '{alt_db}'. Using that.")
                    # adopt the alternative names for the rest of the run
                    gremlin_db = alt_db
                    gremlin_graph = alt_graph
                    found = True
                    break

            if not found:
                print("    No common alternative Gremlin graph found. Attempting to create the configured graph.")
                create_graph_cmd = [
                    "az", "cosmosdb", "gremlin", "graph", "create",
                    "--account-name", acct,
                    "--resource-group", rg,
                    "--database-name", gremlin_db,
                    "--name", gremlin_graph,
                    "--throughput", "400",
                ]
                rc, out, err = run_az_command(create_graph_cmd, timeout=60)
                if rc != 0:
                    print(f"    ERROR creating gremlin graph: rc={rc}\nstdout={out}\nstderr={err}")
                else:
                    print(f"     Created gremlin graph '{gremlin_graph}'.")

async def main():
    """Main entry point for data initialization."""
    initializer = DataInitializer()
    await initializer.initialize_all()


if __name__ == "__main__":
    asyncio.run(main())