"""
Context Enhancement Patch for ZorkGPT

This patch improves the agent's decision-making by providing more comprehensive context.
The changes focus on expanding the action history window and including map visualization.
"""

# Suggested changes to zork_orchestrator.py

# Change 1: Increase action history window (line 736-738)
# OLD:
#     previous_actions_and_responses=self.action_history[-5:],  # Last 5 actions
# NEW:
#     previous_actions_and_responses=self.action_history[-50:],  # Last 50 actions

# Change 2: Add map visualization to relevant_memories (around line 720)
# After getting objectives_text, add:
"""
# Generate map visualization if available
map_visualization = ""
if hasattr(self, 'game_map') and self.game_map:
    map_mermaid = self.game_map.to_mermaid()
    if map_mermaid:
        map_visualization = f"\n\n## CURRENT WORLD MAP\n{map_mermaid}\n"
"""

# Change 3: Include more comprehensive location history in extended_context
# In generate_extended_context method, add:
"""
# Add recent location history with discoveries
if hasattr(self, 'memory_log_history') and self.memory_log_history:
    location_discoveries = []
    seen_locations = set()
    
    for memory in self.memory_log_history[-30:]:  # Last 30 turns
        loc_name = getattr(memory, 'current_location_name', None)
        if loc_name and loc_name not in seen_locations:
            seen_locations.add(loc_name)
            items = getattr(memory, 'visible_objects', [])
            if items:
                location_discoveries.append(f"- {loc_name}: found {', '.join(items)}")
    
    if location_discoveries:
        context_parts.append("RECENT DISCOVERIES BY LOCATION:")
        context_parts.extend(location_discoveries)
        context_parts.append("")
"""

# Change 4: Enhance agent's get_action_with_reasoning method (zork_agent.py)
# Update line 312 to include more history:
# OLD:
#     for i, (action, response) in enumerate(previous_actions_and_responses[-8:]):
# NEW:
#     for i, (action, response) in enumerate(previous_actions_and_responses[-30:]):

# Change 5: Add dynamic context expansion based on looping behavior
# In get_action_with_reasoning, before building messages:
"""
# Dynamic context expansion when stuck
context_expansion_factor = 1
if action_counts:
    # Check for high repetition indicating stuck behavior
    max_repetitions = max(action_counts.values()) if action_counts else 0
    if max_repetitions > 10:
        context_expansion_factor = 3  # Triple the context
    elif max_repetitions > 5:
        context_expansion_factor = 2  # Double the context
    
# Apply expansion factor
history_window = min(len(previous_actions_and_responses), 15 * context_expansion_factor)
for i, (action, response) in enumerate(previous_actions_and_responses[-history_window:]):
"""