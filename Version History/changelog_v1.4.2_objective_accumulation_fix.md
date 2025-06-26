# Changelog v1.4.2 - Objective Accumulation Bug Fix

## Date: 2025-01-26

## Issue Description
The system was accumulating 23+ objectives by turn 274, indicating a critical bug in objective management. The objectives should be replaced/updated every 15 turns, not continuously accumulated.

## Root Cause Analysis
1. **Primary Issue**: Incorrect API response handling in `_update_discovered_objectives()`
   - Code was accessing `response.content` directly
   - Should access `response.choices[0].message.content` per OpenAI API structure
   - This caused the response parsing to fail with AttributeError

2. **Secondary Issue**: Failed parsing didn't update the turn counter
   - When parsing failed, `self.objective_update_turn` wasn't updated
   - This caused the system to retry objective updates every single turn
   - Objectives kept accumulating instead of being replaced

3. **Widespread Issue**: Multiple locations had the same API response bug
   - `_generate_gameplay_summary()` 
   - `_evaluate_objective_completion()`
   - `_refine_discovered_objectives()`

## Changes Made

### 1. Fixed API Response Handling in `_update_discovered_objectives()` (lines 2759-2803)
```python
# Before:
response.content  # This doesn't exist on OpenAI response objects

# After:
response_content = response.choices[0].message.content if response.choices else ""
```

### 2. Added Turn Counter Update on Parse Failure (lines 2790-2803)
```python
# Added this line when parsing fails:
self.objective_update_turn = self.turn_count
```
This ensures the system waits for the configured interval (15 turns) before trying again, even if parsing fails.

### 3. Fixed All Other Instances of response.content
- Line 2484: `_generate_gameplay_summary()`
- Line 3057: `_evaluate_objective_completion()`
- Lines 3287, 3295, 3302: `_refine_discovered_objectives()`

## Configuration Context
- `objective_update_interval`: 15 turns (from config.py)
- `objective_refinement_interval`: 75 turns
- `max_objectives_before_forced_refinement`: 20

## Testing Recommendations
1. Monitor objective count over multiple turns
2. Verify objectives are replaced (not accumulated) every 15 turns
3. Check logs for "objectives_parsing_failed" events
4. Ensure objective refinement triggers at appropriate intervals

## Impact
This fix prevents unbounded objective accumulation which was likely causing:
- Performance degradation due to large objective lists
- Context overflow in agent prompts
- Confusion in agent decision-making with too many goals

## Related Files Modified
- `zork_orchestrator.py`: All objective management and LLM response handling