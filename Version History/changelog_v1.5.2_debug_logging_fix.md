# Changelog v1.5.2 - Debug Logging Visibility Fix

## Date: 2025-01-26

## Issue Description
The debug logs in the agent were appearing empty in the console output:
- `[DEBUG] Raw agent response:` (nothing after colon)
- `[DEBUG] Reasoning extraction results:` (nothing after colon)
- `[DEBUG] Final reasoning result:` (nothing after colon)

This made it appear as if the LLM was returning empty responses, when in fact the responses were present but not visible in the console output.

## Root Cause Analysis
1. **Logging Format Issue**: The debug information was being passed to the logger's `extra` parameter, which is used for structured logging but doesn't appear in the console output
2. **Missing Content in Message**: The actual log message only contained the prefix (e.g., "[DEBUG] Raw agent response:") without the actual content
3. **Misleading Output**: This created confusion about whether the LLM was working properly

## Changes Made

### Fixed Debug Log Visibility in `zork_agent.py`

1. **Line 369** - Raw agent response logging:
   ```python
   # Before:
   f"[DEBUG] Raw agent response:"
   
   # After:
   f"[DEBUG] Raw agent response: {raw_response[:500]}{'...' if len(raw_response) > 500 else ''}"
   ```

2. **Line 403** - Reasoning extraction results:
   ```python
   # Before:
   f"[DEBUG] Reasoning extraction results:"
   
   # After:
   f"[DEBUG] Reasoning extraction results: think={len(think_matches)}, thinking={len(thinking_matches)}, reflection={len(reflection_matches)}, total={len(reasoning_parts)}"
   ```

3. **Line 443** - Fallback reasoning extraction:
   ```python
   # Before:
   f"[DEBUG] Fallback reasoning extraction:"
   
   # After:
   f"[DEBUG] Fallback reasoning extraction: found {len(potential_reasoning)} lines"
   ```

4. **Line 460** - Final reasoning result:
   ```python
   # Before:
   f"[DEBUG] Final reasoning result:"
   
   # After:
   f"[DEBUG] Final reasoning result: {reasoning[:200]}{'...' if len(reasoning) > 200 else ''}" if reasoning else "[DEBUG] Final reasoning result: (empty)"
   ```

## Impact
- Debug logs now show actual content in the console output
- Easier to diagnose LLM response issues
- Clearer visibility into the agent's reasoning extraction process
- No functional changes - only logging improvements

## Notes
- The `extra` parameters are retained for structured logging systems that can use them
- Response content is truncated in logs to prevent excessive output (500 chars for raw response, 200 for reasoning)
- Empty responses are now explicitly indicated as "(empty)" rather than showing nothing