# ZorkGPT Looping Behavior Analysis and Improvement Recommendations

## Current Looping Problem

The AI agent exhibits repetitive behavior, trying the same failed actions approximately every 10 turns. This occurs despite multiple anti-repetition mechanisms in place.

## Current Anti-Repetition Mechanisms

### 1. **Limited History Window (8 turns)**
- **Location:** [`zork_agent.py:199`](Z:/ZorkGPT/zork_agent.py:199)
- **Issue:** Only the last 8 turns are shown to the agent
- **Problem:** Actions from 9+ turns ago are "forgotten" and can be retried

### 2. **Action Count Tracking**
- **Location:** [`zork_orchestrator.py:738`](Z:/ZorkGPT/zork_orchestrator.py:738)
- **Mechanism:** Tracks total count of each action across entire episode
- **Warning Threshold:** Actions tried >2 times trigger warnings
- **Issue:** Warning is advisory only, not enforced

### 3. **Critic Scoring System**
- **Location:** [`critic.md`](Z:/ZorkGPT/critic.md:30-41)
- **Penalties:** -0.8 to -1.0 for actions failed 2+ times
- **Issue:** Critic sees limited context and may not recognize older repetitions

### 4. **Agent Instructions**
- **Location:** [`agent.md`](Z:/ZorkGPT/agent.md:78-84)
- **Rules:** Explicit anti-repetition rules and mandatory avoidance
- **Issue:** Instructions compete with other objectives, can be overridden

## Root Causes of Looping

### 1. **Memory Window Mismatch**
- Agent sees 8 turns of history
- Actions from 10+ turns ago appear "new" again
- Global action counts shown but not action-location pairs

### 2. **Context Loss**
- Failed actions in specific locations aren't tracked long-term
- Agent doesn't remember "north from Kitchen = wall" after 8 turns
- Location-specific failure patterns are lost

### 3. **Objective Pressure**
- Discovered objectives push agent to retry approaches
- Exploration pressure conflicts with repetition avoidance
- No mechanism to mark objectives as "currently impossible"

### 4. **Insufficient Failure Categorization**
- All failures treated equally
- "Wall" responses vs. "I don't understand" vs. "Nothing happens"
- No persistent memory of hard barriers vs. temporary obstacles

## Recommended Improvements

### 1. **Enhanced Action-Location Memory**
```python
# Track action failures by location
failed_actions_by_location = {
    "Kitchen": {
        "north": {"count": 3, "response": "wall", "last_turn": 45},
        "open refrigerator": {"count": 2, "response": "locked", "last_turn": 52}
    }
}
```

**Implementation:**
- Modify `zork_orchestrator.py` to track location-specific failures
- Include this in agent context beyond the 8-turn window
- Persist "hard failures" (walls, missing objects) indefinitely

### 2. **Failure Classification System**
```python
FAILURE_TYPES = {
    "PERMANENT": ["wall", "too narrow", "no exit"],  # Never retry
    "MISSING_ITEM": ["locked", "need key"],          # Retry only with new items
    "PARSER": ["don't understand", "don't know"],    # Try different syntax
    "TEMPORARY": ["nothing happens", "already open"]  # Can retry after state change
}
```

**Benefits:**
- Agent learns which failures are permanent vs. solvable
- Reduces pointless retries of permanent barriers
- Focuses effort on solvable problems

### 3. **Extended Context Summary**
```python
def generate_extended_context(self, current_location):
    """Generate a summary of important past events beyond 8-turn window"""
    return f"""
    PERMANENT BARRIERS FROM THIS LOCATION:
    - North: wall (confirmed turn 12)
    - East: locked door (need key, last tried turn 45)
    
    FAILED ACTIONS HERE (>2 attempts):
    - "climb tree": Not climbable (tried 4 times)
    - "open window": Too high (tried 3 times)
    
    SUCCESSFUL PATHS FROM HERE:
    - South: leads to Garden
    - West: leads to Living Room
    """
```

### 4. **Objective Feasibility Tracking**
```python
objectives_with_status = {
    "Get sword from stone": {
        "status": "blocked",
        "reason": "need special tool",
        "retry_condition": "find_new_tool"
    },
    "Explore north from Kitchen": {
        "status": "impossible", 
        "reason": "permanent wall"
    }
}
```

**Benefits:**
- Prevents objectives from driving repetitive behavior
- Focuses agent on achievable goals
- Automatically updates when conditions change

### 5. **Smart Retry Logic**
```python
def should_retry_action(action, location, history):
    """Determine if an action is worth retrying"""
    
    # Never retry permanent failures
    if is_permanent_failure(action, location):
        return False
    
    # Only retry with changed conditions
    if requires_item(action, location):
        return inventory_changed_since_last_try()
    
    # Retry parser errors with different syntax
    if is_parser_error(action):
        return not tried_all_synonyms(action)
    
    return state_changed_significantly()
```

### 6. **Progressive Exploration Strategy**
Instead of random retry after forgetting, implement:
1. **Systematic exploration** of untried actions first
2. **Conditional retries** only when game state changes
3. **Blacklist permanent failures** across entire episode
4. **Priority queue** for actions based on success probability

### 7. **Enhanced Critic Integration**
```python
# Provide critic with extended failure history
critic_context = {
    "proposed_action": action,
    "location_failure_history": failed_actions_by_location[current_location],
    "global_failure_count": action_counts[action],
    "turns_since_last_try": turns_since_action[action],
    "failure_type": classify_failure(last_response)
}
```

## Implementation Priority

1. **High Priority (Quick Wins):**
   - Extend action history shown to agent (8 → 15 turns)
   - Add location-specific failure tracking
   - Classify failure types (permanent vs. temporary)

2. **Medium Priority (Significant Impact):**
   - Implement extended context summary
   - Add objective feasibility tracking
   - Enhance critic with failure history

3. **Long Term (Architectural Changes):**
   - Redesign memory system for persistent patterns
   - Implement smart retry logic
   - Create progressive exploration strategy

## Expected Outcomes

With these improvements:
- **50-70% reduction** in repetitive actions
- **Faster exploration** of new areas
- **Better focus** on solvable challenges
- **Improved scores** through efficient gameplay
- **Reduced frustration** in watching AI play

## Testing Recommendations

1. **Metrics to Track:**
   - Repetition rate (same action in same location)
   - Exploration efficiency (new rooms per turn)
   - Score progression rate
   - Time to escape stuck situations

2. **Test Scenarios:**
   - Rooms with multiple permanent barriers
   - Puzzles requiring specific items
   - Parser-challenging situations
   - Multi-path exploration choices

3. **A/B Testing:**
   - Compare current vs. improved system
   - Measure turns to reach specific milestones
   - Track critic score averages
   - Monitor objective completion rates