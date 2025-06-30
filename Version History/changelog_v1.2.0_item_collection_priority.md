# Changelog - Version 1.2.0: Item Collection Priority Enhancement

## Date: 2025-06-25

## Overview
This update addresses the issue where the ZorkGPT agent was not prioritizing item collection sufficiently, leading to missed scoring opportunities and suboptimal gameplay. The changes emphasize the critical importance of taking items in Zork, where most collectible objects either increase score immediately or are essential for puzzle-solving.

## Problem Identified
- Agent was treating item collection as just another action rather than a high-priority objective
- Critic was not specifically rewarding "take" or "get" actions
- Knowledge base lacked emphasis on the importance of collecting items
- No clear guidance that items in Zork almost always contribute to score or puzzle solutions

## Changes Made

### 1. Agent Prompt Updates (agent.md)
- Added "CRITICAL Priority" tier specifically for item collection in the objective prioritization system
- Enhanced the "Important Object Strategy" section to emphasize:
  - Always take items when seen
  - Examine first, then take
  - Even mundane items are important
  - The game rarely penalizes item collection
- Updated priority orders to check for and collect items before exploration
- Added specific guidance to take ALL visible objects when entering new locations

### 2. Knowledge Base Updates (knowledgebase.md)
- Added a new "CRITICAL - Item Collection" section emphasizing:
  - Items increase score instantly upon collection
  - Items are required for puzzle-solving
  - Items provide essential capabilities (light, weapons, tools)
  - Never assume an item is unimportant
- Updated "Item-First Exploration" strategy to prioritize collection over navigation
- Enhanced inventory management guidance to encourage taking everything possible

### 3. Critic Evaluation Updates (critic.md)
- Added specific scoring guidance for item collection actions:
  - `take`, `get`, `pick up` actions: +0.6 to +1.0 score
  - `examine` before taking: +0.4 to +0.6 score
  - `drop` valuable items without reason: -0.5 to -0.8 score
- Added "ITEM COLLECTION WISDOM" section explaining why taking items is crucial
- Emphasized that items often increase score immediately and have later uses

### 4. Critic Code Updates (zork_critic.py)
- Added separate `item_collection_verbs` category with highest priority
- Modified action diversity calculation to recognize item collection as a distinct category
- Updated override logic to always allow item collection actions unless explicitly failed
- Prioritized item collection actions in the reasonable actions list when stuck

## Expected Impact
- Agent should now actively seek and collect items in every location
- Score progression should improve significantly as treasures are collected
- Puzzle-solving capability should improve with better inventory management
- Reduced likelihood of missing important items that block progress later

## Testing Recommendations
- Monitor if agent now takes items immediately upon discovery
- Check if scores increase more consistently across episodes
- Verify that the agent examines and then takes objects systematically
- Ensure the critic properly rewards item collection actions
- Watch for any edge cases where item collection might be detrimental

## Future Considerations
- Could add specific item value recognition (treasures vs. tools)
- Might implement inventory management strategies for when carrying capacity is reached
- Consider adding memory of where dropped items were left for later retrieval