# ZorkGPT Context Utilization Analysis

## Current Issues

### 1. Limited Action History
The agent only receives the last 5 actions when called, severely limiting its ability to recognize patterns and avoid repetition.

### 2. Insufficient Memory Context
While the agent internally extends to 15 actions, this is still inadequate for complex navigation and puzzle-solving.

### 3. Missing Critical Information
The agent lacks access to:
- Full map visualization (Mermaid diagram)
- Complete inventory history
- Puzzle state tracking across locations
- Temporal patterns of discoveries
- Cross-location relationships

### 4. Static Context Size
Despite having 32K tokens available, the system uses a fixed, minimal context regardless of the situation.

## Proposed Improvements

### 1. Dynamic Context Expansion
Implement adaptive context sizing based on:
- Number of repeated actions
- Time spent in same location
- Critic score trends
- Discovery rate

### 2. Enhanced Memory System
Include:
- Full action history (up to 100 turns)
- Complete map visualization
- Item discovery timeline
- Puzzle state tracker
- Location relationship graph

### 3. Context Prioritization
When approaching token limits:
- Prioritize recent actions and current location
- Summarize older history
- Keep critical discoveries and puzzle states
- Maintain full map data

### 4. Situation-Aware Context
Provide different context based on agent state:
- **Exploration mode**: Map data, unexplored areas, item locations
- **Puzzle-solving mode**: Relevant items, previous attempts, hints
- **Combat mode**: Weapon inventory, combat history, escape routes
- **Stuck/looping mode**: Full history, all available options, alternative strategies

## Implementation Priority

1. **Immediate**: Increase action history from 5 to 50 actions
2. **High**: Add full map visualization to agent context
3. **High**: Include complete inventory and item discovery history
4. **Medium**: Implement dynamic context expansion
5. **Medium**: Add puzzle state tracking
6. **Low**: Implement context summarization for older events