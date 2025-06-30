#!/usr/bin/env python3
"""
Standalone test for the response parsing functionality.
This tests just the _extract_content_from_response method without requiring dependencies.
"""

import json
from typing import Dict, Any

def extract_content_from_response(response_data: Dict[str, Any], model: str) -> str:
    """
    Extract content from response data, handling different provider formats.
    
    This is a copy of the method from llm_client.py for standalone testing.
    
    Args:
        response_data: Raw JSON response from the API
        model: Model name to help identify provider
        
    Returns:
        Extracted content string
        
    Raises:
        ValueError: If content cannot be extracted from the response
    """
    # Try OpenAI/OpenAI-compatible format first (most common)
    if "choices" in response_data and len(response_data["choices"]) > 0:
        choice = response_data["choices"][0]
        if "message" in choice and "content" in choice["message"]:
            return choice["message"]["content"]
        # Some providers put content directly in choice
        if "content" in choice:
            return choice["content"]
        # Some providers use "text" field
        if "text" in choice:
            return choice["text"]
    
    # Try Google Gemini format
    if "candidates" in response_data and len(response_data["candidates"]) > 0:
        candidate = response_data["candidates"][0]
        if "content" in candidate:
            if "parts" in candidate["content"] and len(candidate["content"]["parts"]) > 0:
                return candidate["content"]["parts"][0].get("text", "")
            if "text" in candidate["content"]:
                return candidate["content"]["text"]
        if "text" in candidate:
            return candidate["text"]
    
    # Try Anthropic Claude format
    if "content" in response_data:
        if isinstance(response_data["content"], list) and len(response_data["content"]) > 0:
            if "text" in response_data["content"][0]:
                return response_data["content"][0]["text"]
        if isinstance(response_data["content"], str):
            return response_data["content"]
    
    # Try direct content/text field (some simple APIs)
    if "text" in response_data:
        return response_data["text"]
    if "content" in response_data and isinstance(response_data["content"], str):
        return response_data["content"]
    
    # Try response field (some APIs)
    if "response" in response_data:
        if isinstance(response_data["response"], str):
            return response_data["response"]
        if isinstance(response_data["response"], dict) and "text" in response_data["response"]:
            return response_data["response"]["text"]
    
    # Try generation field (some APIs)
    if "generation" in response_data:
        if isinstance(response_data["generation"], str):
            return response_data["generation"]
        if isinstance(response_data["generation"], dict) and "text" in response_data["generation"]:
            return response_data["generation"]["text"]
    
    # Try results array format
    if "results" in response_data and len(response_data["results"]) > 0:
        result = response_data["results"][0]
        if "text" in result:
            return result["text"]
        if "content" in result:
            return result["content"]
    
    # Last resort: try to find any text-like field
    possible_fields = ["output", "generated_text", "completion", "message", "answer"]
    for field in possible_fields:
        if field in response_data:
            if isinstance(response_data[field], str):
                return response_data[field]
            if isinstance(response_data[field], dict) and "text" in response_data[field]:
                return response_data[field]["text"]
    
    # If we can't find content, provide detailed error
    available_keys = list(response_data.keys())
    raise ValueError(
        f"Unable to extract content from {model} response. "
        f"Available keys: {available_keys}. "
        f"Response structure: {json.dumps(response_data, indent=2)[:500]}..."
    )

def test_response_format_compatibility():
    """Test the response parsing function with different provider formats."""
    
    # Test cases with different provider response formats
    test_cases = [
        {
            "name": "OpenAI format",
            "response": {
                "choices": [
                    {
                        "message": {
                            "content": "Hello from OpenAI!"
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4}
            },
            "expected": "Hello from OpenAI!"
        },
        {
            "name": "Google Gemini format",
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "Hello from Gemini!"
                                }
                            ]
                        }
                    }
                ]
            },
            "expected": "Hello from Gemini!"
        },
        {
            "name": "Anthropic Claude format",
            "response": {
                "content": [
                    {
                        "text": "Hello from Claude!"
                    }
                ]
            },
            "expected": "Hello from Claude!"
        },
        {
            "name": "Simple text format",
            "response": {
                "text": "Hello from simple API!"
            },
            "expected": "Hello from simple API!"
        },
        {
            "name": "Response field format",
            "response": {
                "response": "Hello from response field!"
            },
            "expected": "Hello from response field!"
        },
        {
            "name": "Generation field format",
            "response": {
                "generation": {
                    "text": "Hello from generation!"
                }
            },
            "expected": "Hello from generation!"
        },
        {
            "name": "Results array format",
            "response": {
                "results": [
                    {
                        "text": "Hello from results!"
                    }
                ]
            },
            "expected": "Hello from results!"
        },
        {
            "name": "Direct content string",
            "response": {
                "content": "Hello from direct content!"
            },
            "expected": "Hello from direct content!"
        }
    ]
    
    print("Testing LLM response format compatibility...")
    print("=" * 60)
    
    all_passed = True
    
    for test_case in test_cases:
        try:
            # Test the extraction method
            result = extract_content_from_response(
                test_case["response"], 
                "test-model"
            )
            
            if result == test_case["expected"]:
                print(f"✅ {test_case['name']}: PASSED")
            else:
                print(f"❌ {test_case['name']}: FAILED")
                print(f"   Expected: {test_case['expected']}")
                print(f"   Got: {result}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ {test_case['name']}: ERROR - {e}")
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("🎉 All tests passed! The response parser should work with multiple providers.")
    else:
        print("⚠️  Some tests failed. Please check the implementation.")
    
    return all_passed

def test_error_handling():
    """Test error handling for invalid response formats."""
    print("\nTesting error handling for invalid responses...")
    print("-" * 60)
    
    # Test case with no valid content fields
    invalid_response = {
        "status": "ok",
        "metadata": {"tokens": 100}
    }
    
    try:
        result = extract_content_from_response(invalid_response, "test-model")
        print("❌ Error handling: FAILED - Should have raised ValueError")
        return False
    except ValueError as e:
        if "Unable to extract content" in str(e):
            print("✅ Error handling: PASSED - Proper error message")
            return True
        else:
            print(f"❌ Error handling: FAILED - Wrong error message: {e}")
            return False
    except Exception as e:
        print(f"❌ Error handling: FAILED - Unexpected exception: {e}")
        return False

if __name__ == "__main__":
    print("ZorkGPT LLM Provider Compatibility Test (Standalone)")
    print("=" * 60)
    
    # Run compatibility tests
    compatibility_passed = test_response_format_compatibility()
    
    # Run error handling tests
    error_handling_passed = test_error_handling()
    
    print("\n" + "=" * 60)
    print("SUMMARY:")
    
    if compatibility_passed and error_handling_passed:
        print("🎉 ALL TESTS PASSED!")
        print("The response parser is compatible with multiple provider formats.")
        print("\nSupported providers:")
        print("- OpenAI and OpenAI-compatible APIs")
        print("- Google Gemini")
        print("- Anthropic Claude")
        print("- Generic text-based APIs")
        exit(0)
    else:
        print("❌ SOME TESTS FAILED!")
        print("Please review the implementation before using with different providers.")
        exit(1)