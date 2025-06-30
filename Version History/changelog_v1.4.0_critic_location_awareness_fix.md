# Changelog - Version 1.4.0: Critic Location Awareness & Rejection Logic Fix

## Date: 2025-06-26

## Overview
This update fixes two critical issues in the critic system:
1. The critic was incorrectly penalizing actions based on failures in OTHER locations
2. Actions with scores below the rejection threshold were still being executed

## Problems Identified

### Issue 1: Location-Agnostic Evaluation
The critic was penalizing directions (like "east" or "west") because they had failed in DIFFERENT locations, not understanding that each location has unique valid exits. For example:
- "east" might fail in the Kitchen but be valid in the Garden
- The critic would see "east failed in Kitchen" and penalize it in the Garden
- This led to incorrect rejections of potentially valid moves

### Issue 2: Rejection Threshold Bug
When an action scored below the rejection threshold (e.g., -0.80 < -0.05):
- The rejection loop would exhaust all attempts
- The code would log a warning but STILL EXECUTE the bad action
- This completely defeated the purpose of having a critic

## Changes Made

### 1. Critic Prompt Updates (critic.md)
- Added "LOCATION-SPECIFIC EVALUATION" section emphasizing:
  - Each location has unique exits
  - Failures in other locations are IRRELEVANT
  - Only consider failures in the CURRENT location
- Updated spatial awareness rules to never penalize based on other locations
- Added clear distinction in repetition guidance:
  - "FAILED in this specific location" = SEVERE PENALTY
  - "failed in a different location" = IGNORE

### 2. Critic Code Updates (zork_critic.py)
- Modified context provided about failures in other locations:
  - Changed from "Note: 'X' also failed in a different location"
  - To "(Low importance - different location context): 'X' failed in 'Y', but this may not apply to the current location"
- Made it clear this is supplementary information, not primary evaluation criteria

### 3. Orchestrator Logic Fix (zork_orchestrator.py)
- Fixed rejection loop to properly handle overrides:
  - Added `break` when override is granted
  - Only get new action if override was NOT granted
- Fixed critical bug where low-scoring actions were executed:
  - Changed from "proceeding with low-scoring action"
  - To "SKIPPING turn due to low-scoring action"
  - Added `continue` to skip the turn instead of executing bad action
- Added trust tracker update when critic correctly rejects

## Expected Impact
- Critic will correctly evaluate actions based on current location only
- Valid directions won't be rejected just because they failed elsewhere
- Actions scoring below threshold will actually be rejected, not executed
- Better exploration as location-appropriate moves are allowed
- Safer gameplay as truly bad actions are prevented

## Testing Recommendations
- Verify critic evaluates directions based on current location only
- Check that failures in other locations don't affect current evaluation
- Confirm actions with scores < -0.05 are NOT executed
- Monitor that valid moves in new locations aren't incorrectly rejected
- Ensure the rejection loop properly exits when overrides are granted

## Example Fixes
Before: 
- "east" rejected in Garden because it failed in Kitchen (Score: -0.80)
- Action still executed despite low score

After:
- "east" evaluated based on Garden layout only
- Low-scoring actions are skipped, not executed