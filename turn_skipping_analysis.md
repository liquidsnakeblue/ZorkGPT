# Turn Skipping Analysis - ZorkGPT

## Problem Summary
The agent starts skipping turns after Turn 27, with messages like:
- "Exhausted rejection attempts, SKIPPING turn due to low-scoring action"

## Log Analysis

### Key Observations

1. **Turn 7**: First sign of critic disagreement
   - Message: "High disagreement in critic evaluations (range: 0.50), using most confident"
   - Action: "north" scored 0.00
   - This action failed: "The forest becomes impenetrable to the north"

2. **Turn 9**: First critic rejection
   - Agent proposed "south" 
   - Critic evaluation: Score=-0.50, "repeating action 'south' which has already been tried"
   - Agent then proposed "examine tree" which was accepted

3. **Turn 10**: Another rejection
   - Agent proposed "north"
   - Critic evaluation: Score=-0.80, "repeating action 'north' which has already failed in this location"
   - Agent then proposed "east" which was accepted

4. **Turn 14**: Another rejection
   - Agent proposed "east"
   - Critic evaluation: Score=-0.80, "action 'east' has previously failed in this specific location"
   - Agent then proposed "south" which was accepted

5. **Turn 22**: Rejection with override consideration
   - Agent proposed "open wooden door"
   - Critic evaluation: Score=-0.80, "wooden door...described as 'nailed shut'"
   - Agent then proposed "east" which was accepted

6. **Turn 24**: Failed action
   - Agent tried "doorway"
   - Game response: "I don't know the word 'doorway'"
   - This was a parser error, not a movement failure

7. **Turn 28**: FIRST TURN SKIP
   - Agent proposed "examine wooden door" 3 times
   - Critic kept scoring it -0.40 (repetition)
   - After 3 attempts, system skipped the turn

8. **Turns 30 & 32**: More skips
   - Agent kept proposing "east"
   - Critic scored it -0.80 each time
   - System skipped turns after exhausting retries

## Root Cause Analysis

### 1. Agent Behavior Pattern
The agent appears to be getting stuck in a loop where it:
- Proposes the same action repeatedly
- Even after critic rejection, it proposes the same action again
- This suggests the agent isn't properly incorporating the critic's feedback

### 2. Critic Evaluation Issues
The critic is correctly identifying repetitive actions, but:
- The rejection threshold might be too aggressive
- The critic is penalizing reasonable exploration attempts

### 3. System Design Issue
The core problem appears to be in the rejection retry logic:
```python
# From orchestrator line 931
if rejection_attempt < max_rejections - 1:
    # Get new action from agent with reasoning
    rejected_actions_context = ", ".join(
        self.critic.rejection_system.rejected_actions_this_turn
    )
    agent_response = self.agent.get_action_with_reasoning(
        game_state_text=current_game_state
        + f"\n\n[Previous action(s) '{rejected_actions_context}' were rejected by critic: {critic_justification}]",
        ...
    )
```

The agent is being told about rejections, but it's not effectively using this information to generate different actions.

### 4. Agent Context Window Issue
Looking at turns 28-32, the agent seems to have lost awareness of:
- What actions have been tried
- What the current state is
- What alternatives are available

## Key Problems Identified

1. **Agent doesn't diversify after rejection**: When told an action was rejected, the agent often proposes the same action again.

2. **Limited action repertoire**: The agent seems to have a very limited set of actions it considers, leading to repetition.

3. **Context not effectively used**: The rejection context and justification aren't leading to meaningful adaptation.

4. **Critic threshold too strict**: The rejection threshold might be causing too many rejections for reasonable exploration.

## Recommendations

1. **Improve Agent Prompt**: Add stronger instructions about diversifying actions after rejection.

2. **Add Action Suggestion System**: When rejecting an action, the critic could suggest alternatives.

3. **Adjust Rejection Threshold**: Consider making the threshold less strict to allow more exploration.

4. **Better Context Management**: Ensure the agent has clear visibility of:
   - Available exits
   - Objects in the room
   - Actions that have failed
   - Suggested alternatives

5. **Add Fallback Actions**: If the agent can't generate a good action after rejections, have a set of fallback exploration commands.

6. **Debug Agent Response Generation**: The agent seems to be ignoring the rejection feedback - this needs investigation.