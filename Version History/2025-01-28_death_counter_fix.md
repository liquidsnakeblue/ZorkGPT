# Death Counter Fix - January 28, 2025

## Issue
The death counter was staying at 0 and not incrementing when the agent died in ZorkGPT.

## Root Cause
A new `ZorkOrchestrator` instance was being created for each episode in `main.py`, which reset the death count to 0 at the start of each episode. The death count is meant to be cumulative across all episodes.

## Changes Made

### 1. main.py
- **Line 8**: Modified `run_episode()` function to accept orchestrator as a parameter
- **Line 82**: Moved `ZorkOrchestrator()` instantiation outside the episode loop
- **Line 37**: Added display of total deaths across all episodes in episode summary

#### Before:
```python
def run_episode():
    """Run a long episode with adaptive knowledge management."""
    orchestrator = ZorkOrchestrator()
    # ...

if __name__ == "__main__":
    print("=" * 60)
    while True:
        try:
            run_episode()
```

#### After:
```python
def run_episode(orchestrator):
    """Run a long episode with adaptive knowledge management."""
    # ...

if __name__ == "__main__":
    print("=" * 60)
    # Create orchestrator once, outside the episode loop
    orchestrator = ZorkOrchestrator()
    
    while True:
        try:
            run_episode(orchestrator)
```

### 2. zork_orchestrator.py
- **Lines 746-754**: Added explicit death detection logging in inventory check
- **Lines 1143-1151**: Added explicit death detection logging in regular gameplay

#### Enhancement:
Added logging when death is detected to show cumulative death count:
```python
if self._is_death_reason(game_over_reason):
    self.death_count += 1
    self.logger.info(
        f"Death detected! Total deaths across all episodes: {self.death_count}",
        extra={
            "event_type": "death_detected",
            "episode_id": self.episode_id,
            "turn": self.turn_count,
            "cumulative_death_count": self.death_count,
        }
    )
```

## Result
The death counter now properly persists across episodes and increments each time the agent dies. The orchestrator instance is created once and reused for all episodes, ensuring that session-persistent state (like death count) is maintained correctly.

## Testing Notes
- The `reset_episode_state()` method was already correctly implemented to preserve the death count
- Death detection logic in `_is_death_reason()` was working correctly
- The fix only required ensuring the orchestrator instance persists across episodes