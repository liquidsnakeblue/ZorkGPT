# Changelog v1.5.0 - Context Enhancement for Better Decision Making

## Date: 2025-01-26

## Problem Statement
The ZorkGPT agent was performing poorly due to insufficient context:
- Only processing ~8K tokens despite 32K token capacity
- Getting stuck repeating the same 20 actions in the same areas
- Limited to viewing only last 5 actions, causing repetitive behavior
- Missing critical information like map visualization and discovery history

## Root Causes Identified
1. **Minimal Action History**: Agent only received last 5 actions from orchestrator
2. **No Map Visualization**: Despite references in prompts, map diagram wasn't provided
3. **Limited Location Context**: No cross-location discovery tracking
4. **Static Context Size**: No adaptation based on agent's stuck/looping state
5. **Missing Historical Patterns**: No long-term memory of what worked/failed

## Changes Implemented

### 1. Expanded Action History Window
**File**: `zork_orchestrator.py` (line 738)
- Changed from `-5:` to `-50:` actions passed to agent
- Provides 10x more historical context for pattern recognition

### 2. Dynamic Context Expansion in Agent
**File**: `zork_agent.py` (lines 308-324)
- Implemented adaptive history window based on repetition count:
  - Default: 15 actions
  - Moderate repetition (>5): 30 actions
  - Severe repetition (>10): 45 actions
- Automatically provides more context when agent is stuck

### 3. Enhanced Extended Context Generation
**File**: `zork_orchestrator.py` (`generate_extended_context` method)
- Added full map visualization (Mermaid diagram)
- Added cross-location discovery tracking (last 50 turns)
- Shows items and exits found in each location
- Provides comprehensive world state beyond current location

### 4. Location-Action Database
**Files**: `location_action_database.py` (new), `zork_orchestrator.py`
- Compact database tracking ALL actions attempted at each location
- Format: "Location: action=outcome" (e.g., "Forest: north→Kitchen; south=✗; read paper=Welcome to")
- Prevents repetition of successful actions (like reading the same paper twice)
- Uses minimal tokens with symbols: ✓=success, ✗=failed, →=moves to, ?=parser error
- Tracks items found at each location

## Expected Improvements

### Immediate Benefits
1. **Better Pattern Recognition**: 10x more history prevents repeating failed sequences
2. **Improved Navigation**: Map visualization helps agent understand spatial relationships
3. **Strategic Planning**: Cross-location discoveries enable better item/puzzle connections
4. **Adaptive Behavior**: More context when stuck helps break out of loops

### Token Usage
- Base context: ~5-8K tokens (system prompt + knowledge base)
- Action history: +2-6K tokens (depending on repetition)
- Map visualization: +1-2K tokens
- Discovery tracking: +1-2K tokens
- **Total**: 9-18K tokens (well within 32K limit)

### Performance Metrics to Monitor
1. Average turns spent in same location before moving
2. Unique actions per episode
3. Score progression rate
4. Number of repeated action sequences
5. Discovery rate (new items/locations per turn)

## Testing Recommendations
1. Run 5-10 episodes with new context enhancements
2. Compare against baseline performance metrics
3. Monitor token usage to ensure within limits
4. Check for any latency increases from larger context
5. Verify map visualization renders correctly in prompts

## Future Enhancements
1. Implement context summarization for very old events
2. Add puzzle state tracking across locations
3. Include temporal patterns (time-based events)
4. Implement importance scoring for context prioritization
5. Add episodic memory retrieval based on similarity

## Configuration Notes
- No config changes required - uses existing 32K token limit
- Dynamic expansion is automatic based on behavior
- Backward compatible with existing episodes