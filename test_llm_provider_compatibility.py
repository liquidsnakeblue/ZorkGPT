#!/usr/bin/env python3
"""
Test script to verify LLM client compatibility with different provider response formats.
This tests the new _extract_content_from_response method with various response structures.
"""

import json
from llm_client import LLMClient

def test_response_format_compatibility():
    """Test the LLM client's ability to parse different provider response formats."""
    
    # Create a mock LLM client instance
    client = LLMClient()
    
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
    
    print("Testing LLM client response format compatibility...")
    print("=" * 60)
    
    all_passed = True
    
    for test_case in test_cases:
        try:
            # Test the extraction method
            result = client._extract_content_from_response(
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
        print("🎉 All tests passed! The LLM client should now work with multiple providers.")
    else:
        print("⚠️  Some tests failed. Please check the implementation.")
    
    return all_passed

def test_error_handling():
    """Test error handling for invalid response formats."""
    print("\nTesting error handling for invalid responses...")
    print("-" * 60)
    
    client = LLMClient()
    
    # Test case with no valid content fields
    invalid_response = {
        "status": "ok",
        "metadata": {"tokens": 100}
    }
    
    try:
        result = client._extract_content_from_response(invalid_response, "test-model")
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
    print("ZorkGPT LLM Provider Compatibility Test")
    print("=" * 60)
    
    # Run compatibility tests
    compatibility_passed = test_response_format_compatibility()
    
    # Run error handling tests
    error_handling_passed = test_error_handling()
    
    print("\n" + "=" * 60)
    print("SUMMARY:")
    
    if compatibility_passed and error_handling_passed:
        print("🎉 ALL TESTS PASSED!")
        print("The LLM client is now compatible with multiple provider formats.")
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