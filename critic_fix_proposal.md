# Critic Fix Proposal - Addressing Turn Skipping Issue

## Problem Summary

The agent is getting stuck in loops where:
1. It proposes the same action repeatedly
2. The critic correctly rejects it
3. The agent doesn't effectively use the rejection feedback to diversify
4. After 3 attempts, the system skips the turn

## Root Causes

### 1. Rejection Threshold Too Strict
- Current threshold: `-0.05` (line 94 in config.py)
- This means any action scoring below -0.05 gets rejected
- The critic is giving scores like -0.40, -0.80 for repeated actions
- This is working as intended, but the agent isn't adapting

### 2. Agent Not Using Rejection Context
Looking at the orchestrator code (lines 936-942), when an action is rejected:
```python
agent_response = self.agent.get_action_with_reasoning(
    game_state_text=current_game_state
    + f"\n\n[Previous action(s) '{rejected_actions_context}' were rejected by critic: {critic_justification}]",
    ...
)
```

The rejection context is appended to the game state, but the agent seems to ignore it.

### 3. Limited Action Generation Diversity
The agent appears to have a very limited repertoire of actions it considers, leading to:
- Proposing "east" multiple times even after rejection
- Proposing "examine wooden door" repeatedly
- Not exploring other available options

## Proposed Solutions

### Solution 1: Enhanced Agent Prompt (Priority: HIGH)
Add explicit instructions to the agent prompt about handling rejections:

```markdown
**CRITICAL - HANDLING CRITIC REJECTIONS:**
If you see a message like "[Previous action(s) 'X' were rejected by critic: Y]":
1. **NEVER** propose the same action again
2. **READ** the critic's justification carefully
3. **IDENTIFY** what category of action was rejected (movement, examination, interaction)
4. **SWITCH** to a completely different category of action:
   - If movement was rejected → try examining objects or taking items
   - If examination was rejected → try movement or interaction
   - If interaction was rejected → try movement or examination
5. **PRIORITIZE** actions you haven't tried recently in this location
```

### Solution 2: Add Available Actions Context (Priority: HIGH)
Modify the agent's context to always include:
1. Available exits from the current location
2. Visible objects that can be interacted with
3. Actions that have been rejected this turn

This gives the agent concrete alternatives to choose from.

### Solution 3: Implement Action Suggestion System (Priority: MEDIUM)
When the critic rejects an action, have it suggest alternatives:

```python
class CriticResponse(BaseModel):
    score: float
    justification: str
    confidence: float = 0.8
    suggested_alternatives: List[str] = []  # NEW FIELD
```

### Solution 4: Adjust Rejection Threshold (Priority: LOW)
Consider making the threshold less strict:
- Current: -0.05
- Proposed: -0.20

This would allow more marginal actions through, but might not solve the core issue.

### Solution 5: Add Fallback Action Generator (Priority: HIGH)
If the agent fails to generate a diverse action after 2 rejections, invoke a fallback system:

```python
def get_fallback_action(current_location, available_exits, visible_objects, failed_actions):
    """Generate a reasonable fallback action when agent is stuck."""
    # Priority 1: Take any items not yet taken
    for obj in visible_objects:
        if obj not in failed_actions and any(verb in obj.lower() for verb in ['leaflet', 'lamp', 'sword']):
            return f"take {obj}"
    
    # Priority 2: Try an unexplored exit
    for exit in available_exits:
        if exit not in failed_actions:
            return exit
    
    # Priority 3: Examine an unexamined object
    for obj in visible_objects:
        examine_cmd = f"examine {obj}"
        if examine_cmd not in failed_actions:
            return examine_cmd
    
    # Priority 4: Basic exploration
    return "look"
```

## Implementation Plan

### Phase 1: Quick Fixes (Immediate)
1. Update agent.md with rejection handling instructions
2. Ensure available exits and objects are always passed to the agent

### Phase 2: Structural Improvements (Next)
1. Implement the fallback action generator
2. Add suggested_alternatives to CriticResponse
3. Modify the rejection retry loop to use fallback after 2 attempts

### Phase 3: Fine-tuning (Later)
1. Adjust rejection threshold if needed
2. Add more sophisticated action diversity metrics
3. Implement learning from successful actions

## Expected Outcomes

With these changes:
1. The agent should propose different actions after rejections
2. Turn skipping should be rare (only in truly stuck situations)
3. The agent should make more consistent progress
4. The system should be more robust to edge cases