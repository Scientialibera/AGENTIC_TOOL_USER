"""
Direct test of Azure OpenAI Assistants Code Interpreter API.

This script tests the Azure OpenAI Assistants Code Interpreter functionality
directly, without going through the MCP server. This helps validate:
1. Azure credentials work
2. Assistants API responds correctly
3. Code execution works as expected
4. We understand the response format

Run this BEFORE testing the MCP server.
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from root .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider


async def test_code_interpreter():
    """Test Azure OpenAI Assistants Code Interpreter directly."""
    
    print("="*70)
    print(" Testing Azure OpenAI Assistants Code Interpreter API")
    print("="*70)
    
    # Get configuration from environment
    endpoint = os.getenv("AOAI_ENDPOINT")
    deployment = os.getenv("AOAI_CHAT_DEPLOYMENT", "gpt-4o")
    api_key = os.getenv("AOAI_API_KEY")  # Optional: if set, use key instead of managed identity
    
    if not endpoint:
        print("\n✗ Error: AOAI_ENDPOINT not set in environment")
        print(f"   Tried to load from: {env_path}")
        return
    
    print(f"\n  Endpoint: {endpoint}")
    print(f"  Deployment: {deployment}")
    if api_key:
        print(f"  Auth: API Key")
    else:
        print(f"  Auth: Managed Identity (DefaultAzureCredential)")
    
    # Step 1: Create Azure OpenAI client
    print("\n" + "-"*70)
    print(" Step 1: Creating Azure OpenAI client...")
    print("-"*70)
    
    try:
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential,
            "https://cognitiveservices.azure.com/.default"
        )
        
        # Ensure endpoint doesn't have trailing slash
        endpoint_clean = endpoint.rstrip('/')
        
        client = AsyncAzureOpenAI(
            azure_endpoint=endpoint_clean,
            api_version="2024-05-01-preview",
            azure_ad_token_provider=token_provider
        )
        
        print("✓ Client created successfully")
        print(f"  Using endpoint: {endpoint_clean}")
        print(f"  API version: 2024-05-01-preview")
        
    except Exception as e:
        print(f"✗ Error creating client: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 2: Create Assistant with code_interpreter
    print("\n" + "-"*70)
    print(" Step 2: Creating Assistant with code_interpreter tool...")
    print("-"*70)
    
    try:
        assistant = await client.beta.assistants.create(
            model=deployment,
            name="Code Interpreter Test",
            description="Test assistant for code execution",
            tools=[{"type": "code_interpreter"}],
            instructions="You are a helpful assistant that can execute Python code to solve mathematical and data analysis problems."
        )
        
        print(f"✓ Assistant created: {assistant.id}")
        
    except Exception as e:
        print(f"✗ Error creating assistant: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 3: Create Thread
    print("\n" + "-"*70)
    print(" Step 3: Creating conversation thread...")
    print("-"*70)
    
    try:
        thread = await client.beta.threads.create()
        print(f"✓ Thread created: {thread.id}")
        
    except Exception as e:
        print(f"✗ Error creating thread: {e}")
        import traceback
        traceback.print_exc()
        await client.beta.assistants.delete(assistant.id)
        return
    
    # Step 4: Add message with task
    print("\n" + "-"*70)
    print(" Step 4: Sending task to assistant...")
    print("-"*70)
    
    task = "Calculate the revenue per employee if we sold $10,000 and have 2 employees"
    print(f"\n  Task: {task}")
    
    try:
        message = await client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=task
        )
        
        print(f"✓ Message sent: {message.id}")
        
    except Exception as e:
        print(f"✗ Error sending message: {e}")
        import traceback
        traceback.print_exc()
        await client.beta.assistants.delete(assistant.id)
        return
    
    # Step 5: Run Assistant
    print("\n" + "-"*70)
    print(" Step 5: Running assistant (executing code)...")
    print("-"*70)
    
    try:
        run = await client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id
        )
        
        print(f"✓ Run started: {run.id}")
        print(f"  Status: {run.status}")
        
    except Exception as e:
        print(f"✗ Error starting run: {e}")
        import traceback
        traceback.print_exc()
        await client.beta.assistants.delete(assistant.id)
        return
    
    # Step 6: Wait for completion
    print("\n" + "-"*70)
    print(" Step 6: Waiting for completion...")
    print("-"*70)
    
    try:
        max_wait = 60  # seconds
        waited = 0
        
        while run.status in ["queued", "in_progress"]:
            await asyncio.sleep(2)
            waited += 2
            
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            
            print(f"  Status: {run.status} (waited {waited}s)")
            
            if waited >= max_wait:
                print(f"✗ Timeout after {max_wait} seconds")
                await client.beta.assistants.delete(assistant.id)
                return
        
        print(f"✓ Run completed with status: {run.status}")
        
    except Exception as e:
        print(f"✗ Error waiting for completion: {e}")
        import traceback
        traceback.print_exc()
        await client.beta.assistants.delete(assistant.id)
        return
    
    # Step 6b: Get run steps to see actual code executed
    print("\n" + "-"*70)
    print(" Step 6b: Retrieving run steps (to see code executed)...")
    print("-"*70)
    
    try:
        run_steps = await client.beta.threads.runs.steps.list(
            thread_id=thread.id,
            run_id=run.id,
            order="asc"
        )
        
        print(f"✓ Retrieved {len(run_steps.data)} run steps")
        
        print("\n" + "="*70)
        print(" RUN STEPS DETAILS:")
        print("="*70)
        
        for idx, step in enumerate(run_steps.data, 1):
            print(f"\n--- Step {idx} ---")
            print(f"  ID: {step.id}")
            print(f"  Type: {step.type}")
            print(f"  Status: {step.status}")
            
            if step.type == "tool_calls":
                print(f"  Tool Calls:")
                for tool_call in step.step_details.tool_calls:
                    print(f"\n    Tool Call ID: {tool_call.id}")
                    print(f"    Type: {tool_call.type}")
                    
                    if tool_call.type == "code_interpreter":
                        print(f"    Code Interpreter:")
                        print(f"      Input (code):")
                        if hasattr(tool_call.code_interpreter, 'input'):
                            for line in tool_call.code_interpreter.input.split('\n'):
                                print(f"        {line}")
                        
                        print(f"      Outputs:")
                        if hasattr(tool_call.code_interpreter, 'outputs'):
                            for output in tool_call.code_interpreter.outputs:
                                print(f"        Type: {output.type}")
                                if output.type == "logs":
                                    print(f"        Logs: {output.logs}")
                                elif output.type == "image":
                                    print(f"        Image ID: {output.image.file_id}")
            
            elif step.type == "message_creation":
                print(f"  Message Created: {step.step_details.message_creation.message_id}")
        
    except Exception as e:
        print(f"✗ Error retrieving run steps: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 7: Get messages
    print("\n" + "-"*70)
    print(" Step 7: Retrieving assistant response...")
    print("-"*70)
    
    try:
        messages = await client.beta.threads.messages.list(
            thread_id=thread.id,
            order="asc"
        )
        
        print(f"✓ Retrieved {len(messages.data)} messages")
        
        # Display all messages
        print("\n" + "="*70)
        print(" CONVERSATION:")
        print("="*70)
        
        for msg in messages.data:
            role = msg.role.upper()
            print(f"\n[{role}]:")
            
            for content in msg.content:
                if content.type == "text":
                    print(f"  {content.text.value}")
                elif content.type == "image_file":
                    print(f"  [Image: {content.image_file.file_id}]")
        
        # Extract code and results from assistant messages
        print("\n" + "="*70)
        print(" EXTRACTED CODE & RESULTS:")
        print("="*70)
        
        code_blocks = []
        results = []
        
        for msg in messages.data:
            if msg.role == "assistant":
                for content in msg.content:
                    if content.type == "text":
                        text = content.text.value
                        
                        # Look for code blocks
                        if "```python" in text or "```" in text:
                            # Extract code between ```python and ```
                            import re
                            code_matches = re.findall(r'```python\n(.*?)```', text, re.DOTALL)
                            if code_matches:
                                code_blocks.extend(code_matches)
                            else:
                                # Try without python tag
                                code_matches = re.findall(r'```\n(.*?)```', text, re.DOTALL)
                                if code_matches:
                                    code_blocks.extend(code_matches)
                        
                        # Extract results (text after code or standalone)
                        if text.strip() and not text.strip().startswith("```"):
                            results.append(text.strip())
        
        if code_blocks:
            print("\nCode executed:")
            for i, code in enumerate(code_blocks, 1):
                print(f"\n  Block {i}:")
                for line in code.strip().split('\n'):
                    print(f"    {line}")
        
        if results:
            print("\nResults:")
            for i, result in enumerate(results, 1):
                print(f"\n  {i}. {result}")
        
    except Exception as e:
        print(f"✗ Error retrieving messages: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 8: Cleanup
    print("\n" + "-"*70)
    print(" Step 8: Cleaning up...")
    print("-"*70)
    
    try:
        await client.beta.assistants.delete(assistant.id)
        print("✓ Assistant deleted")
        
    except Exception as e:
        print(f"⚠ Warning: Could not delete assistant: {e}")
    
    print("\n" + "="*70)
    print(" Test completed successfully!")
    print("="*70)


async def main():
    """Run the test."""
    await test_code_interpreter()


if __name__ == "__main__":
    asyncio.run(main())
