#!/usr/bin/env python3
"""
Test script to verify Docker LLM backend integration.

Usage:
    python test_docker_backend.py
"""

import asyncio
import sys
import os

# Add parent directory to path to import mcp_agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.mcpclient.mcp_agent import list_models_from_docker, ollama_chat_async

async def test_list_models():
    """Test listing models from Docker container"""
    print("=" * 60)
    print("Test 1: List models from Docker container")
    print("=" * 60)
    
    endpoint = "http://localhost:11434"
    
    try:
        models = await list_models_from_docker(endpoint)
        print(f"✅ Success! Found {len(models)} model(s):")
        for model in models:
            name = model.get("name", "Unknown")
            size = model.get("size", 0)
            size_gb = size / (1024**3)
            print(f"  - {name} ({size_gb:.2f} GB)")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_chat():
    """Test chat completion with Docker container"""
    print("\n" + "=" * 60)
    print("Test 2: Chat completion with Docker container")
    print("=" * 60)
    
    endpoint = "http://localhost:11434"
    model = "qwen2.5:7b-instruct"
    
    messages = [
        {"role": "user", "content": "Say 'Hello from Docker backend!' in one sentence."}
    ]
    
    try:
        print(f"Calling {endpoint} with model {model}...")
        response = await ollama_chat_async(
            model=model,
            messages=messages,
            llm_endpoint=endpoint,
            timeout=60.0
        )
        
        content = response.get("message", {}).get("content", "")
        print(f"✅ Success! Response: {content}")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all tests"""
    print("\n🧪 Testing Docker LLM Backend Integration\n")
    
    results = []
    
    # Test 1: List models
    results.append(await test_list_models())
    
    # Test 2: Chat completion
    results.append(await test_chat())
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

