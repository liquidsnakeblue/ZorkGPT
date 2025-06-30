# Version 1.5.4 - Critic Focus Fix, Inventory Context, Relaxed Loop Detection, Parser Experimentation & Exit Preservation

## Date: 2025-06-26

## Overview
Fixed multiple critical bugs: critic evaluating wrong actions, overly aggressive loop detection, parser experimentation being blocked, agent location tracking confusion, and exit information being lost after movement failures. These fixes prevent turn skipping and game breakage.

## Problem
The critic was receiving context about previous actions and responses, which it would then incorrectly reference when justifying its evaluation of the current proposed action. For example:
- Agent proposes: "north"
- Critic evaluation: "The agent used a noun-only command 'tree' which lacks a verb..."

The critic was seeing "tree" in the recent actions context and using that to justify its evaluation of "north".

## Changes Made

### 1. Updated Critic User Prompt (zork_critic.py)
Modified the `evaluate_action` method to make it crystal clear that the critic should ONLY evaluate the proposed action:
- Added explicit instructions to focus only on the proposed action
- Clarified that previous actions are for context only, not evaluation
- Emphasized the proposed action multiple times in the prompt
- Added clear instructions about what NOT to do

### 2. Updated Critic System Prompt (critic.md)
Added a critical instruction section at the beginning of the prompt:
- Clear examples of correct vs incorrect evaluation
- Explicit instruction to never reference previous actions in justifications
- Reinforcement that justifications must address the proposed action only

## Technical Details

### Files Modified:
1. `zork_critic.py` - Updated user prompt construction in `evaluate_action` method and added inventory context
2. `critic.md` - Added critical instruction section at the beginning
3. `zork_orchestrator.py` - Updated to pass current inventory to critic evaluation

### Key Changes:
- The critic now receives much clearer instructions about what to evaluate
- Previous actions are still provided for context but with explicit warnings not to evaluate them
- The proposed action is emphasized multiple times to ensure focus
- The critic now receives the current inventory as context for better evaluation of actions

### Inventory Context Addition:
- Added `current_inventory` parameter to both `evaluate_action` and `get_robust_evaluation` methods
- The orchestrator now passes the current inventory when calling critic evaluation
- The inventory is displayed in the critic's prompt to help evaluate actions that involve items

## Impact
This fix should resolve the issue where valid actions were being rejected based on previous failed actions, which was causing excessive turn skipping and preventing game progress.

## Loop Detection Relaxation

The loop detection was too aggressive and preventing legitimate exploration. The following changes were made:

### Changes to `should_override_critic_rejection`:
1. **Immediate repetition detection**: Changed from 3 to 5 repeated actions
2. **Location-based detection**: Changed from 6 to 8 locations and from ≤2 to ≤1 unique locations
3. **Action diversity thresholds**:
   - Low diversity: 0.3 → 0.2
   - Low diversity with stagnation: 0.5 → 0.3 and 4 → 8 turns
   - Simple location exploration: 4 → 8 actions
   - Extended stagnation: 10 → 15 turns without progress
   - Repetitive actions: 0.4 → 0.3 diversity and 6 → 10 turns

### Changes to `_detect_action_cycling`:
1. Minimum actions to check: 6 → 8
2. Unique actions threshold: ≤3 → ≤2
3. Repetition threshold: 40% → 60%

These changes allow the agent more freedom to explore and try different approaches before being flagged as stuck in a loop.

## Agent Loop Detection Relaxation

The agent's own loop detection was also too aggressive, warning after just 3 turns in the same location. This has been relaxed:

### Changes to `get_relevant_memories_for_prompt` in `zork_agent.py`:
1. **Location history window**: Changed from checking last 5 turns to last 8 turns
2. **Loop trigger threshold**: Changed from 3 to 6 - now requires 6 out of 8 turns in the same location
3. **Warning message**: Updated to reflect "last 8 turns" instead of "last 5 turns"

This means the agent will now only receive a loop warning if it has spent 6 out of its last 8 turns in the same location, giving it much more time to explore a location thoroughly before being prompted to move.

## Critical Parser Experimentation Fix

Fixed a critical issue where the critic was preventing the agent from experimenting with different command variations, especially for item collection. This was causing turn skipping and breaking the game.

### Changes to `critic.md`:
1. **Added ERROR MESSAGE HANDLING section**:
   - Explicitly instructs the critic not to reject actions based on previous error messages
   - Recognizes that text adventure parsers often require specific phrasing
   - Allows experimentation with different command variations

2. **Updated SPECIAL SCORING FOR ITEM ACTIONS**:
   - Removed "repeatedly failed" condition for item collection
   - Added explicit guidance to score variations positively (e.g., "take egg" after "take large egg" failed)
   - Score range for retrying: +0.3 to +0.7

3. **Updated Repetitive Actions Guidance**:
   - Added PARSER EXPERIMENTATION EXCEPTION
   - Clarified that variations of commands should NOT be penalized
   - Only penalize EXACT repetitions or clearly impossible actions

This fix ensures the agent can try different phrasings like "take egg", "get egg", "take large egg", etc. without being blocked by the critic, which is essential for text adventure gameplay.

## Agent Prompt Improvements

Added critical guidance to help the agent better understand location-based action tracking and Zork commands.

### Location-Based Action Tracking (agent.md)
Added a new section "CRITICAL - LOCATION-BASED ACTION TRACKING" that clarifies:
- Actions must be tracked BY LOCATION - "north failed" only applies where it actually failed
- Actions that brought you TO a location are different from actions FROM that location
- Example: Going "north" FROM Forest Path TO Clearing doesn't mean "north" failed FROM Clearing
- Each location has its own valid exits - don't assume failures transfer between locations

This addresses the state tracking error where the agent was confusing actions from different locations.

### Comprehensive Zork Command Reference (agent.md)
Added a complete command reference section including:
- **Movement Commands**: All directional commands with shortcuts
- **Essential Game Commands**: Save, restore, inventory, look, etc.
- **Item Interaction Commands**: Take, drop, examine, open, close, etc.
- **Combat Commands**: Attack and kill syntax
- **Communication Commands**: NPC interaction format
- **Special Commands**: Prayer, greetings, wand spells
- **Parser Tips**: 6-letter limit, adjective usage, command simplicity

This ensures the agent has a clear reference for all available Zork commands and their proper syntax.

## Exit Preservation After Movement Failures

Fixed a critical bug where movement failure messages were causing the extractor to incorrectly parse available exits.

### Problem
When a movement failed (e.g., "The forest becomes impenetrable to the north"), the extractor would incorrectly extract only "north" as the available exit, losing all other valid exits and creating a deadlock.

### Changes Made:

1. **Updated extractor.md**:
   - Added "CRITICAL - Movement Failure Handling" section
   - Clarified that movement failures don't change available exits
   - **KEY CHANGE**: Instructed extractor to return EMPTY exits list [] on movement failures
   - This allows the map's merge functionality to preserve existing exits
   - Added clear examples showing correct (empty list) vs incorrect (extracting "north" from failure)
   - Explained why empty list is correct: prevents overriding valid exits with incorrect data

2. **Updated map_graph.py - update_room_exits()**:
   - Added `merge` parameter (default True) to preserve existing exits
   - Now merges new exits with existing ones instead of replacing
   - Prevents loss of exit information when extractor provides incomplete data

This ensures that when the agent tries a blocked direction, the system maintains the full list of available exits rather than incorrectly limiting options.

## Testing Recommendations
1. Monitor critic evaluations to ensure they reference only the proposed action
2. Check that justifications match the action being evaluated
3. Verify that turn skipping is reduced to appropriate levels
4. Ensure the agent can make progress through the game without excessive rejections
5. Verify that the relaxed loop detection still catches actual loops while allowing legitimate exploration