#!/usr/bin/env python3
"""
Debug script to test OpenRouter + Gemini API directly.
This helps isolate the issue without running the full ZorkGPT system.
"""

import os
import json
import requests
from typing import Dict, Any

def test_openrouter_gemini():
    """Test OpenRouter with Google Gemini directly."""
    
    # Configuration
    base_url = "https://openrouter.ai/api/v1"
    model = "google/gemini-2.5-pro"
    api_key = os.environ.get("CLIENT_API_KEY")
    
    print("🔧 OpenRouter + Gemini Debug Test")
    print("=" * 50)
    print(f"Base URL: {base_url}")
    print(f"Model: {model}")
    print(f"API Key: {'✅ Set' if api_key else '❌ Missing'}")
    
    if not api_key:
        print("\n❌ ERROR: CLIENT_API_KEY environment variable not set!")
        print("Please set your OpenRouter API key:")
        print("export CLIENT_API_KEY=your_openrouter_api_key_here")
        return False
    
    print(f"API Key Preview: {api_key[:10]}...{api_key[-4:]}")
    print()
    
    # Test cases
    test_cases = [
        {
            "name": "Simple Test",
            "messages": [{"role": "user", "content": "Say hello"}],
            "params": {"temperature": 0.7, "max_tokens": 50}
        },
        {
            "name": "Critic-style Test (might trigger filtering)",
            "messages": [{"role": "user", "content": "Evaluate this action: 'examine mailbox'. Score it from -1 to 1."}],
            "params": {"temperature": 0.6, "max_tokens": 300}
        },
        {
            "name": "JSON Request Test",
            "messages": [{"role": "user", "content": "Return a JSON object with 'location': 'West of House'"}],
            "params": {"temperature": 0.6, "max_tokens": 800}
        }
    ]
    
    success_count = 0
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"🧪 Test {i}: {test_case['name']}")
        print("-" * 30)
        
        # Build request
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Title": "ZorkGPT-Debug",
            "HTTP-Referer": "https://zorkgpt.com"
        }
        
        payload = {
            "model": model,
            "messages": test_case["messages"],
            **test_case["params"]
        }
        
        print(f"📤 Request:")
        print(f"  Messages: {test_case['messages'][0]['content'][:50]}...")
        print(f"  Params: {test_case['params']}")
        
        try:
            # Make request
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            print(f"📥 Response:")
            print(f"  Status: {response.status_code}")
            
            if response.ok:
                response_data = response.json()
                print(f"  Keys: {list(response_data.keys())}")
                
                # Try to extract content using our parser logic
                content = extract_content_debug(response_data)
                
                if content and content.strip():
                    print(f"  ✅ Content: {content[:100]}...")
                    success_count += 1
                else:
                    print(f"  ❌ Empty/whitespace content!")
                    print(f"  Raw content: {repr(content)}")
                    print(f"  Full response: {json.dumps(response_data, indent=2)}")
                    
            else:
                print(f"  ❌ Error: {response.text}")
                
        except Exception as e:
            print(f"  ❌ Exception: {e}")
        
        print()
    
    print("=" * 50)
    print(f"📊 Results: {success_count}/{len(test_cases)} tests passed")
    
    if success_count == 0:
        print("🔍 Possible issues:")
        print("- Invalid API key")
        print("- OpenRouter account issues")
        print("- Gemini content filtering")
        print("- Model name incorrect")
        print("- Request parameters incompatible")
    elif success_count < len(test_cases):
        print("🔍 Partial success suggests content filtering or parameter issues")
    else:
        print("✅ All tests passed - issue might be in ZorkGPT integration")
    
    return success_count > 0

def extract_content_debug(response_data: Dict[str, Any]) -> str:
    """Debug version of content extraction."""
    
    # Try OpenAI format
    if "choices" in response_data and len(response_data["choices"]) > 0:
        choice = response_data["choices"][0]
        if "message" in choice and "content" in choice["message"]:
            return choice["message"]["content"]
    
    # Try Gemini format  
    if "candidates" in response_data and len(response_data["candidates"]) > 0:
        candidate = response_data["candidates"][0]
        if "content" in candidate:
            if "parts" in candidate["content"] and len(candidate["content"]["parts"]) > 0:
                return candidate["content"]["parts"][0].get("text", "")
    
    # Try direct fields
    for field in ["text", "content", "response"]:
        if field in response_data:
            return str(response_data[field])
    
    return ""

if __name__ == "__main__":
    test_openrouter_gemini()