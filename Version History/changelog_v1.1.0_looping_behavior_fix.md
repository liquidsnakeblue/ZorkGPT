# ZorkGPT Changelog - Version 1.1.0
## Looping Behavior Fix Implementation

**Date:** June 25, 2025  
**Version:** 1.1.0  
**Focus:** Reducing repetitive behavior and improving exploration efficiency

---

## Overview

This version implements critical improvements to address the looping behavior problem where the AI agent was repeatedly trying failed actions every ~10 turns. The changes focus on enhanced memory, better failure tracking, and smarter objective management.

---

## High Priority Changes

### 1. Extended Action History Window
**File:** [`zork_agent.py`](../zork_agent.py)  
**Line:** 199  
**Change:** Extended action history from 8 to 15 turns

```python
# Before:
for i, (action, response) in enumerate(previous_actions_and_responses[-8:]):

# After:
for i, (action, response) in enumerate(previous_actions_and_responses[-15:]):
```

**Impact:** Reduces the likelihood of repeating actions from 9-15 turns ago that were previously "forgotten"

### 2. Location-Specific Failure Tracking
**File:** [`zork_orchestrator.py`](../zork_orchestrator.py)  
**Lines:** 237-260  
**New Method:** `track_location_failure()`

- Tracks failed actions by specific location
- Records failure count, response snippets, and turn numbers
- Maintains failure type classification for each action

**Data Structure:**
```python
failed_actions_by_location = {
    "Kitchen": {
        "north": {
            "count": 3,
            "responses": ["wall", "wall", "wall"],
            "failure_type": "PERMANENT",
            "first_turn": 12,
            "last_turn": 45
        }
    }
}
```

### 3. Failure Type Classification System
**File:** [`zork_orchestrator.py`](../zork_orchestrator.py)  
**Lines:** 49-55, 227-235  
**New Constants and Method:**

```python
FAILURE_TYPES = {
    "PERMANENT": ["wall", "too narrow", "no exit", "can't go that way"],
    "MISSING_ITEM": ["locked", "need key", "requires", "can't open"],
    "PARSER": ["don't understand", "don't know", "what do you want"],
    "TEMPORARY": ["nothing happens", "already open", "already closed"]
}
```

**Method:** `classify_failure_type()` - Categorizes failures to determine retry worthiness

---

## Medium Priority Changes

### 1. Extended Context Summary
**File:** [`zork_orchestrator.py`](../zork_orchestrator.py)  
**Lines:** 262-330  
**New Method:** `generate_extended_context()`

Provides agents with:
- Permanent barriers from current location
- Actions requiring specific items
- Confirmed successful paths
- Globally overused actions (>5 attempts)

**Integration:** Lines 709-717 - Extended context is merged with relevant memories

### 2. Objective Feasibility Tracking
**File:** [`zork_orchestrator.py`](../zork_orchestrator.py)  
**Lines:** 332-366, 393  
**New Methods and Data:**

- `objective_feasibility` dictionary tracks status of each objective
- `update_objective_feasibility()` - Updates objective status based on failures
- `get_feasible_objectives()` - Returns only achievable objectives

**Objective Display Enhancement:** Lines 669-703
- Shows objectives categorized as "ACHIEVABLE NOW" vs "BLOCKED/IMPOSSIBLE"
- Provides clear reasons for blocked objectives

### 3. Enhanced Critic Integration
**File:** [`zork_orchestrator.py`](../zork_orchestrator.py)  
**Line:** 744  
**Enhancement:** Critic already receives `failed_actions_by_location`

The critic now has access to complete location-specific failure history for more informed action evaluation.

---

## Integration Points

### Game Loop Integration
**File:** [`zork_orchestrator.py`](../zork_orchestrator.py)  
**Lines:** 969-986  
**Change:** Automatic failure tracking after each action

```python
# Track location-specific failures
if self.current_room_name_for_map:
    failure_indicators = ["wall", "can't", "don't", "no way", ...]
    if any(indicator in response_lower for indicator in failure_indicators):
        self.track_location_failure(...)
```

---

## Expected Outcomes

Based on the analysis, these changes should provide:

1. **50-70% reduction** in repetitive actions
2. **Faster exploration** of new areas
3. **Better focus** on solvable challenges
4. **Improved scores** through efficient gameplay
5. **Reduced frustration** when watching AI play

---

## Testing Recommendations

### Metrics to Track:
- Repetition rate (same action in same location)
- Exploration efficiency (new rooms per turn)
- Score progression rate
- Time to escape stuck situations

### Key Test Scenarios:
- Rooms with multiple permanent barriers
- Puzzles requiring specific items
- Parser-challenging situations
- Multi-path exploration choices

---

## Technical Notes

### Memory Efficiency:
- Location-specific tracking only stores first 100 characters of responses
- Failure history is reset between episodes
- Extended context is generated on-demand

### Backward Compatibility:
- All changes maintain existing API contracts
- No breaking changes to method signatures
- Enhanced data is additive, not replacement

---

## Future Enhancements (Not Implemented)

The following were identified as "Long Term" improvements for future versions:
- Redesign memory system for persistent patterns
- Implement smart retry logic with condition checking
- Create progressive exploration strategy with priority queues

---

## Files Modified

1. **[`zork_agent.py`](../zork_agent.py)** - Extended history window
2. **[`zork_orchestrator.py`](../zork_orchestrator.py)** - Core improvements for tracking and context

---

## Version History

- **v1.0.0** - Initial release
- **v1.1.0** - Looping behavior fix (this version)
---

## Bug Fixes

### MapGraph Attribute Error Fix
**Issue:** AttributeError: 'MapGraph' object has no attribute 'nodes'  
**File:** [`zork_orchestrator.py`](../zork_orchestrator.py)  
**Lines:** 301-320  
**Fix:** Updated `generate_extended_context()` to use correct MapGraph attributes:
- Changed from `self.game_map.nodes` to `self.game_map.rooms`
- Changed from `get_node()` to direct dictionary access
- Properly normalized location names for room lookup
- Used correct connection confidence lookup structure

**Date Fixed:** June 25, 2025

---

## Fixed Issues

### Location Disambiguation Problem - FIXED
**Issue:** The map system was assuming locations with the same name are the same place
**Impact:** Multiple locations named "Clearing" were being treated as a single location
**Example:** Different clearings in the forest were merged into one map node
**Root Cause:** `_create_unique_location_id()` was only using room name and exit patterns for identification

**Solution Implemented:**
- Modified `_create_unique_location_id()` in [`map_graph.py`](../map_graph.py) to incorporate description hashing
- Updated the method to create a 6-character MD5 hash of cleaned room descriptions
- Combined room name + exit patterns + description hash for unique identification
- Updated `get_or_create_node_id()` to properly check for description hash differences
- Modified [`zork_orchestrator.py`](../zork_orchestrator.py) to store and use unique location IDs with description hashes

**Changes Made:**
1. **map_graph.py:_create_unique_location_id()** - Now generates IDs like "Clearing (north only) #73c258" where the hash distinguishes different clearings
2. **map_graph.py:get_or_create_node_id()** - Enhanced to check description hashes when matching existing rooms
3. **zork_orchestrator.py** - Added `current_location_unique_id` tracking to maintain proper unique IDs across turns

**Test Results:** All test cases pass - different locations with the same name now get unique IDs while the same location consistently gets the same ID

**Date Fixed:** June 25, 2025
