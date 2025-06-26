"""
Location-Action Database for ZorkGPT

Tracks all actions attempted at each location with their outcomes in a compact format.
This provides comprehensive action history while using minimal tokens.
"""

from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict
import json


class LocationActionDatabase:
    """
    Maintains a compact database of all actions tried at each location.
    
    Format: {location: {action: outcome}}
    Example: {"Forest": {"north": "You can't go that way", "examine tree": "Large oak tree"}}
    """
    
    def __init__(self):
        # Main database: location -> action -> outcome
        self.location_actions: Dict[str, Dict[str, str]] = defaultdict(dict)
        
        # Track successful movements: (from_location, action) -> to_location
        self.successful_moves: Dict[Tuple[str, str], str] = {}
        
        # Track items found: location -> list of items
        self.items_found: Dict[str, Set[str]] = defaultdict(set)
        
    def record_action(self, location: str, action: str, outcome: str, 
                     new_location: Optional[str] = None, items_found: Optional[List[str]] = None) -> None:
        """
        Record an action and its outcome at a location.
        
        Args:
            location: Current location name
            action: Action attempted
            outcome: First line or key part of game response
            new_location: If action resulted in movement, the new location
            items_found: Any items discovered from this action
        """
        # Normalize inputs
        location = location.strip()
        action = action.lower().strip()
        
        # Truncate outcome to first meaningful line (save tokens)
        outcome_lines = outcome.strip().split('\n')
        compact_outcome = outcome_lines[0][:50]  # First 50 chars of first line
        
        # Store the action-outcome pair
        self.location_actions[location][action] = compact_outcome
        
        # Track successful movement
        if new_location and new_location != location:
            self.successful_moves[(location, action)] = new_location
            
        # Track items found
        if items_found:
            self.items_found[location].update(items_found)
            
    def get_location_summary(self, location: str) -> str:
        """
        Get a compact summary of all actions tried at a location.
        
        Returns a token-efficient string like:
        "Forest: north='Can't go', south='Kitchen', examine tree='Oak tree', take acorn='Taken'"
        """
        if location not in self.location_actions:
            return f"{location}: No actions recorded"
            
        actions = self.location_actions[location]
        
        # Build compact summary
        summary_parts = []
        
        # Add movement outcomes
        movements = ['north', 'south', 'east', 'west', 'up', 'down', 'in', 'out']
        for direction in movements:
            if direction in actions:
                # Check if it's a successful move
                if (location, direction) in self.successful_moves:
                    dest = self.successful_moves[(location, direction)]
                    summary_parts.append(f"{direction}→{dest}")
                else:
                    summary_parts.append(f"{direction}=✗")
                    
        # Add key object interactions
        for action, outcome in actions.items():
            if action not in movements:
                # Shorten common outcomes
                if "don't understand" in outcome.lower():
                    summary_parts.append(f"{action}=?")
                elif "taken" in outcome.lower():
                    summary_parts.append(f"{action}=✓")
                elif "can't" in outcome.lower() or "no" in outcome.lower():
                    summary_parts.append(f"{action}=✗")
                else:
                    # Include first few words of outcome
                    short_outcome = ' '.join(outcome.split()[:3])
                    summary_parts.append(f"{action}={short_outcome}")
                    
        # Add items found
        if location in self.items_found and self.items_found[location]:
            items_str = ",".join(sorted(self.items_found[location]))
            summary_parts.append(f"items:{items_str}")
            
        return f"{location}: {'; '.join(summary_parts)}"
    
    def get_compact_database(self) -> str:
        """
        Get entire database in compact format for agent context.
        
        Returns multi-line string with one location per line:
        ```
        West of House: north→North of House; south→South of House; open mailbox=✓; items:leaflet
        Kitchen: west=✗; up→Attic; examine table=Wooden table
        ```
        """
        summaries = []
        for location in sorted(self.location_actions.keys()):
            summaries.append(self.get_location_summary(location))
        return '\n'.join(summaries)
    
    def has_tried_action(self, location: str, action: str) -> bool:
        """Check if an action has been tried at a location."""
        return action.lower().strip() in self.location_actions.get(location, {})
    
    def get_outcome(self, location: str, action: str) -> Optional[str]:
        """Get the recorded outcome of an action at a location."""
        return self.location_actions.get(location, {}).get(action.lower().strip())
    
    def estimate_tokens(self) -> int:
        """Estimate token count for the compact database."""
        # Rough estimate: 4 characters per token
        return len(self.get_compact_database()) // 4


# Example usage and integration point
def create_location_action_context(database: LocationActionDatabase, 
                                 current_location: str,
                                 max_locations: int = 20) -> str:
    """
    Create context string for agent including location-action database.
    
    Prioritizes:
    1. Current location
    2. Recently visited locations  
    3. Locations with many discoveries
    """
    context_parts = ["## LOCATION ACTION HISTORY (✓=success, ✗=failed, →=moves to)"]
    
    # Always include current location first
    if current_location in database.location_actions:
        context_parts.append(database.get_location_summary(current_location))
        context_parts.append("")  # blank line
        
    # Add other locations
    other_summaries = []
    for location in sorted(database.location_actions.keys()):
        if location != current_location:
            other_summaries.append(database.get_location_summary(location))
            
    # Limit to max_locations to control token usage
    if len(other_summaries) > max_locations:
        other_summaries = other_summaries[:max_locations]
        context_parts.append(f"(Showing {max_locations} of {len(database.location_actions)} locations)")
        
    context_parts.extend(other_summaries)
    
    return '\n'.join(context_parts)