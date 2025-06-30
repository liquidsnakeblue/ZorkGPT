# Changelog - Version 1.3.0: Discovery Priority Fix

## Date: 2025-06-25

## Overview
This update addresses the issue where the agent was over-prioritizing movement to avoid loops, even when it had just discovered something new that should be explored. The agent was moving away from newly revealed features (like gratings) instead of investigating them, leading to missed opportunities and inefficient gameplay.

## Problem Identified
In the example provided, after taking leaves and revealing a grating, the agent immediately tried to move east instead of exploring the newly discovered grating. This was caused by:
- Loop detection being too aggressive
- No distinction between "stuck in a location" vs "just discovered something new in a location"
- Critic not penalizing movement away from new discoveries
- Missing guidance about prioritizing newly revealed features

## Changes Made

### 1. Agent Prompt Updates (agent.md)
- Modified loop detection to recognize that new discoveries are NOT loops
- Added explicit check: "Did I just discover something new? If yes, EXPLORE IT FIRST"
- Created new priority section: "Priority Order When Something New is Revealed"
  - CRITICAL: Always explore newly revealed objects immediately
  - Examine the new feature first
  - Try interacting with it before moving
- Updated stuck detection to check for new discoveries first

### 2. Critic Evaluation Updates (critic.md)
- Added "NEW DISCOVERY PRIORITY" section with specific scoring:
  - Actions exploring new discoveries: +0.7 to +1.0
  - Movement away from new discoveries: -0.5 to -0.8
  - Explicitly states this overrides anti-loop concerns
- Added exception to stagnation rules for new discoveries
- Enhanced reward criteria to include:
  - Exploring newly revealed objects or features
  - Interacting with discoveries from the previous turn

### 3. Knowledge Base Updates (knowledgebase.md)
- Added "Discovery Priority" as a strategic pattern
- Emphasized that revealing something new is progress, not a loop
- Added "Follow Through on Discoveries" to problem-solving patterns
- Provided specific examples (gratings, hidden doors, new passages)
- Clear guidance: "Movement is premature until you've fully explored the discovery"

## Expected Impact
- Agent will properly explore newly revealed features instead of abandoning them
- Better puzzle-solving as hidden features are properly investigated
- Reduced missed opportunities from premature movement
- More logical gameplay flow: discover → explore → then move
- Improved balance between anti-loop behavior and thorough exploration

## Testing Recommendations
- Monitor situations where actions reveal new features
- Verify agent explores gratings, hidden doors, and other discoveries
- Check that movement is delayed until discoveries are investigated
- Ensure anti-loop behavior still works when truly stuck
- Watch for proper prioritization of new discoveries over movement

## Example Fix
Before: Take leaves → Grating revealed → Move east (abandoning discovery)
After: Take leaves → Grating revealed → Examine grating → Open/enter grating → Only then consider movement

## Future Considerations
- Could add memory of unexplored discoveries for later return
- Might implement a "discovery queue" to track multiple reveals
- Consider different priority levels for different types of discoveries