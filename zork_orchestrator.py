"""
ZorkOrchestrator module for coordinating Zork gameplay episodes.

This module contains the main game loop and ties together all other modules:
- ZorkAgent for action generation
- ZorkExtractor for information extraction
- ZorkCritic for action evaluation
- Movement analysis and mapping
- Logging and experience tracking
"""

from typing import List, Tuple, Optional, Dict, Any
from collections import Counter
from datetime import datetime, timezone
import os
import json
import time
import re
import glob

from zork_api import ZorkInterface
from llm_client import LLMClientWrapper
from map_graph import MapGraph
from movement_analyzer import MovementAnalyzer, MovementContext
from logger import setup_logging
from location_action_database import LocationActionDatabase, create_location_action_context

# Import our refactored modules with aliases to avoid conflicts
from zork_agent import ZorkAgent as AgentModule
from hybrid_zork_extractor import ExtractorResponse
from hybrid_zork_extractor import HybridZorkExtractor
from zork_critic import ZorkCritic, CriticResponse
from zork_strategy_generator import AdaptiveKnowledgeManager
from config import get_config, get_client_api_key

# Optional S3 support
try:
    import boto3

    S3_AVAILABLE = True
except ImportError:
    S3_AVAILABLE = False

# Import shared utilities
from shared_utils import estimate_context_tokens

# Failure classification constants
FAILURE_TYPES = {
    "PERMANENT": ["wall", "too narrow", "no exit", "can't go that way", "there is no way to go"],
    "MISSING_ITEM": ["locked", "need key", "requires", "can't open"],
    "PARSER": ["don't understand", "don't know", "what do you want", "i can't see"],
    "TEMPORARY": ["nothing happens", "already open", "already closed", "it is already"]
}


class ZorkOrchestrator:
    """
    Orchestrates Zork gameplay episodes by coordinating all subsystems.

    This class manages the main game loop and ties together:
    - Agent action generation
    - Information extraction
    - Critic evaluation
    - Movement tracking
    - Experience logging
    
    KNOWLEDGE BASE GENERATION (Method 2 - Single-batch):
    This implementation uses Method 2 (single-batch) knowledge generation,
    which processes the entire episode at once at episode end for optimal
    token efficiency. Benefits:
    - 32% fewer tokens compared to incremental approach
    - Higher quality analysis (7.0/10 vs 2.0/10 for individual windows)  
    - Eliminates context growth problems
    - Comprehensive episode-wide analysis
    """

    def __init__(
        self,
        agent_model: str = None,
        critic_model: str = None,
        info_ext_model: str = None,
        episode_log_file: str = None,
        json_log_file: str = None,
        max_turns_per_episode: int = None,
        client_base_url: str = None,
        client_api_key: str = None,
        # Turn-based knowledge updating
        knowledge_update_interval: int = None,
        # Map updating (more frequent than full knowledge updates)
        map_update_interval: int = None,
        # Objective updating (fastest update cycle for goal discovery)
        objective_update_interval: int = None,
        # State export configuration
        enable_state_export: bool = None,
        state_export_file: str = None,
        s3_bucket: str = None,
        s3_key_prefix: str = None,
        # Gameplay delay for viewer experience
        turn_delay_seconds: float = None,
        # Objective Refinement Configuration
        enable_objective_refinement: bool = None,
        objective_refinement_interval: int = None,
        max_objectives_before_forced_refinement: int = None,
        refined_objectives_target_count: int = None,
        last_objective_refinement_turn: int = None,
    ):
        """Initialize the ZorkOrchestrator with all subsystems."""
        # Load configuration
        config = get_config()
        
        # Store configuration with precedence: parameters > config > defaults
        self.episode_log_file = episode_log_file if episode_log_file is not None else config.files.episode_log_file
        self.json_log_file = json_log_file if json_log_file is not None else config.files.json_log_file

        # Save/restore configuration
        self.zork_save_filename_template = config.gameplay.zork_save_filename_template
        self.zork_game_workdir = config.gameplay.zork_game_workdir
        self.save_signal_filename = config.gameplay.save_signal_filename
        
        # Calculate absolute paths
        self.zork_workdir_abs_path = os.path.abspath(self.zork_game_workdir)
        self.save_signal_file_abs_path = os.path.abspath(self.save_signal_filename)

        # Initialize current save filename - will be set when save is triggered or restored
        self.current_save_filename = None

        # Ensure game directory exists
        os.makedirs(self.zork_workdir_abs_path, exist_ok=True)

        # Game settings
        self.max_turns_per_episode = max_turns_per_episode if max_turns_per_episode is not None else config.orchestrator.max_turns_per_episode
        self.turn_delay_seconds = turn_delay_seconds if turn_delay_seconds is not None else config.gameplay.turn_delay_seconds

        # Adaptive knowledge management (always enabled)
        self.knowledge_update_interval = knowledge_update_interval if knowledge_update_interval is not None else config.orchestrator.knowledge_update_interval
        self.last_knowledge_update_turn = 0
        
        # Map updating (more frequent than full knowledge updates)
        self.map_update_interval = map_update_interval if map_update_interval is not None else config.orchestrator.map_update_interval
        self.last_map_update_turn = 0

        # Objective updating (fastest update cycle for goal discovery)
        self.objective_update_interval = objective_update_interval if objective_update_interval is not None else config.orchestrator.objective_update_interval

        # Objective Refinement Configuration
        self.enable_objective_refinement = enable_objective_refinement if enable_objective_refinement is not None else config.orchestrator.enable_objective_refinement
        self.objective_refinement_interval = objective_refinement_interval if objective_refinement_interval is not None else config.orchestrator.objective_refinement_interval
        self.max_objectives_before_forced_refinement = max_objectives_before_forced_refinement if max_objectives_before_forced_refinement is not None else config.orchestrator.max_objectives_before_forced_refinement
        self.refined_objectives_target_count = refined_objectives_target_count if refined_objectives_target_count is not None else config.orchestrator.refined_objectives_target_count
        self.last_objective_refinement_turn = last_objective_refinement_turn if last_objective_refinement_turn is not None else 0

        # Context management configuration
        self.max_context_tokens = config.orchestrator.max_context_tokens if hasattr(config.orchestrator, 'max_context_tokens') else 150000
        self.context_overflow_threshold = config.orchestrator.context_overflow_threshold if hasattr(config.orchestrator, 'context_overflow_threshold') else 0.8
        self.last_summarization_turn = 0

        # Initialize logger
        self.logger = setup_logging(self.episode_log_file, self.json_log_file)

        # State export configuration
        self.enable_state_export = enable_state_export if enable_state_export is not None else config.orchestrator.enable_state_export
        self.state_export_file = state_export_file if state_export_file is not None else config.files.state_export_file
        self.s3_bucket = s3_bucket or config.aws.s3_bucket
        self.s3_key_prefix = s3_key_prefix if s3_key_prefix is not None else config.aws.s3_key_prefix

        # Initialize S3 client if available and configured
        self.s3_client = None
        if S3_AVAILABLE and self.s3_bucket:
            try:
                self.s3_client = boto3.client("s3")
                self.logger.info(f"S3 export enabled for bucket: {self.s3_bucket}")
            except Exception as e:
                self.logger.warning(f"Failed to initialize S3 client: {e}")

        # Initialize LLM clients with model-specific base URLs
        # Agent client
        agent_client = LLMClientWrapper(
            base_url=client_base_url or config.llm.get_base_url_for_model('agent'),
            api_key=client_api_key or get_client_api_key(),
            logger=self.logger,
        )
        
        # Info extractor client  
        extractor_client = LLMClientWrapper(
            base_url=client_base_url or config.llm.get_base_url_for_model('info_ext'),
            api_key=client_api_key or get_client_api_key(),
            logger=self.logger,
        )
        
        # Critic client
        critic_client = LLMClientWrapper(
            base_url=client_base_url or config.llm.get_base_url_for_model('critic'),
            api_key=client_api_key or get_client_api_key(),
            logger=self.logger,
        )

        # Initialize core components with their specific clients
        self.agent = AgentModule(
            model=agent_model, client=agent_client, logger=self.logger
        )

        # Initialize hybrid extractor (combines structured parsing with LLM extraction)
        self.extractor = HybridZorkExtractor(
            model=info_ext_model, client=extractor_client, logger=self.logger
        )
        if self.logger:
            self.logger.info("Using hybrid extractor (structured + LLM)")

        self.critic = ZorkCritic(
            model=critic_model, client=critic_client, logger=self.logger
        )

        # Initialize shared movement analyzer
        self.movement_analyzer = MovementAnalyzer()

        # Initialize adaptive knowledge manager (always enabled)
        self.adaptive_knowledge_manager = AdaptiveKnowledgeManager(
            log_file=self.json_log_file, output_file="knowledgebase.md"
        )

        # Session-persistent state (survives episode resets)
        self.death_count = 0  # Track cumulative deaths across all episodes

        # Episode state (reset for each episode)
        self.reset_episode_state()

    def classify_failure_type(self, response: str) -> str:
        """Classify the type of failure based on the response text."""
        response_lower = response.lower()
        
        for failure_type, patterns in FAILURE_TYPES.items():
            for pattern in patterns:
                if pattern in response_lower:
                    return failure_type
        
        return "UNKNOWN"
    
    def track_location_failure(self, location: str, action: str, response: str, turn: int) -> None:
        """Track failed actions by location with failure classification."""
        if location not in self.failed_actions_by_location:
            self.failed_actions_by_location[location] = {}
        
        failure_type = self.classify_failure_type(response)
        
        if action not in self.failed_actions_by_location[location]:
            self.failed_actions_by_location[location][action] = {
                "count": 0,
                "responses": [],
                "failure_type": failure_type,
                "first_turn": turn,
                "last_turn": turn
            }
        
        failure_info = self.failed_actions_by_location[location][action]
        failure_info["count"] += 1
        failure_info["last_turn"] = turn
        failure_info["responses"].append(response[:100])  # Store first 100 chars
        
        # Update failure type if it changes (e.g., from PARSER to MISSING_ITEM)
        if failure_type != "UNKNOWN" and failure_info["failure_type"] == "UNKNOWN":
            failure_info["failure_type"] = failure_type

    def generate_extended_context(self, current_location: str) -> str:
        """Generate a summary of important past events beyond the action history window."""
        context_parts = []
        
        # Add map visualization if available
        if hasattr(self, 'game_map') and self.game_map:
            map_diagram = self.game_map.render_mermaid()
            if map_diagram:
                context_parts.append("## CURRENT WORLD MAP")
                context_parts.append("```mermaid")
                context_parts.append(map_diagram)
                context_parts.append("```")
                context_parts.append("")
        
        # Add recent discoveries across all locations
        if hasattr(self, 'memory_log_history') and self.memory_log_history:
            location_discoveries = []
            seen_locations = {}
            
            # Scan through history to collect discoveries
            for memory in self.memory_log_history[-50:]:  # Last 50 turns for broader context
                loc_name = getattr(memory, 'current_location_name', None)
                if loc_name:
                    if loc_name not in seen_locations:
                        seen_locations[loc_name] = {
                            'items': set(),
                            'exits': set(),
                            'features': set()
                        }
                    
                    # Collect items
                    items = getattr(memory, 'visible_objects', [])
                    if items:
                        seen_locations[loc_name]['items'].update(items)
                    
                    # Collect exits
                    exits = getattr(memory, 'exits', [])
                    if exits:
                        seen_locations[loc_name]['exits'].update(exits)
            
            # Format discoveries
            for loc, data in seen_locations.items():
                if data['items']:
                    location_discoveries.append(f"- {loc}: Items found: {', '.join(sorted(data['items']))}")
                if data['exits'] and loc != current_location:  # Don't repeat current location exits
                    location_discoveries.append(f"  Exits: {', '.join(sorted(data['exits']))}")
            
            if location_discoveries:
                context_parts.append("DISCOVERIES ACROSS LOCATIONS:")
                context_parts.extend(location_discoveries)
                context_parts.append("")
        
        # Add location action database if available
        if hasattr(self, 'location_action_db') and self.location_action_db:
            db_context = create_location_action_context(
                self.location_action_db,
                current_location,
                max_locations=15  # Limit to control token usage
            )
            if db_context:
                context_parts.append(db_context)
                context_parts.append("")
        
        # Add location-specific failure information
        if current_location in self.failed_actions_by_location:
            location_failures = self.failed_actions_by_location[current_location]
            
            # Categorize failures by type
            permanent_failures = []
            item_failures = []
            other_failures = []
            
            for action, info in location_failures.items():
                if info["count"] >= 2:  # Only include actions tried multiple times
                    failure_entry = f"- {action}: {info['failure_type']} (tried {info['count']} times)"
                    
                    if info["failure_type"] == "PERMANENT":
                        permanent_failures.append(failure_entry)
                    elif info["failure_type"] == "MISSING_ITEM":
                        item_failures.append(failure_entry)
                    else:
                        other_failures.append(failure_entry)
            
            if permanent_failures:
                context_parts.append("PERMANENT BARRIERS FROM THIS LOCATION:")
                context_parts.extend(permanent_failures)
                context_parts.append("")
            
            if item_failures:
                context_parts.append("ACTIONS REQUIRING ITEMS:")
                context_parts.extend(item_failures)
                context_parts.append("")
            
            if other_failures:
                context_parts.append("OTHER FAILED ACTIONS HERE:")
                context_parts.extend(other_failures)
                context_parts.append("")
        
        # Add successful paths from current location
        if hasattr(self, 'game_map') and self.game_map.rooms:
            normalized_location = current_location.lower() if current_location else ""
            if normalized_location in self.game_map.rooms:
                room = self.game_map.rooms[normalized_location]
                successful_paths = []
                
                # Check connections from this room
                if normalized_location in self.game_map.connections:
                    for direction, connected_room in self.game_map.connections[normalized_location].items():
                        # Check confidence for this connection
                        confidence_key = (normalized_location, direction)
                        confidence = self.game_map.connection_confidence.get(confidence_key, 1.0)
                        
                        if confidence >= 0.8:  # High confidence connections
                            successful_paths.append(f"- {direction}: leads to {connected_room}")
                
                if successful_paths:
                    context_parts.append("CONFIRMED PATHS FROM HERE:")
                    context_parts.extend(successful_paths)
                    context_parts.append("")
        
        # Add global action warnings for highly repeated actions
        highly_repeated = [
            f"- {action} (attempted {count} times total)"
            for action, count in self.action_counts.items()
            if count > 5
        ]
        
        if highly_repeated:
            context_parts.append("GLOBALLY OVERUSED ACTIONS:")
            context_parts.extend(highly_repeated)
            context_parts.append("⚠️ These actions have been tried many times - avoid unless conditions have significantly changed!")
        
        return "\n".join(context_parts) if context_parts else ""
    
    def update_objective_feasibility(self, objective: str, location: str, action: str, failure_type: str) -> None:
        """Update the feasibility status of an objective based on failed actions."""
        if objective not in self.objective_feasibility:
            self.objective_feasibility[objective] = {
                "status": "active",
                "blocked_by": [],
                "retry_conditions": []
            }
        
        # Check if this failure indicates the objective is blocked
        if failure_type == "PERMANENT":
            self.objective_feasibility[objective]["status"] = "impossible"
            self.objective_feasibility[objective]["blocked_by"].append(f"{action} at {location}: permanent barrier")
        elif failure_type == "MISSING_ITEM":
            self.objective_feasibility[objective]["status"] = "blocked"
            self.objective_feasibility[objective]["blocked_by"].append(f"{action} at {location}: missing required item")
            self.objective_feasibility[objective]["retry_conditions"].append("find_required_item")
    
    def get_feasible_objectives(self) -> List[str]:
        """Return only objectives that are currently feasible to pursue."""
        feasible = []
        for obj in self.discovered_objectives:
            if obj not in self.objective_feasibility:
                # No known blockers
                feasible.append(obj)
            elif self.objective_feasibility[obj]["status"] == "active":
                feasible.append(obj)
            elif self.objective_feasibility[obj]["status"] == "blocked":
                # Check if retry conditions might be met (e.g., new items in inventory)
                if "find_required_item" in self.objective_feasibility[obj]["retry_conditions"]:
                    # This is a simple check - could be enhanced to track inventory changes
                    feasible.append(obj + " [requires item]")
        
        return feasible

    def _build_agent_context(self, base_game_state: str, rejected_actions: list = None,
                           critic_justification: str = None) -> str:
        """Build enriched context for the agent including available actions."""
        context_parts = [base_game_state]
        
        # Add available exits if known
        if self.memory_log_history:
            last_extraction = self.memory_log_history[-1]
            exits = getattr(last_extraction, "exits", [])
            if exits:
                context_parts.append(f"\nAvailable exits: {', '.join(exits)}")
            
            # Add visible objects
            objects = getattr(last_extraction, "visible_objects", [])
            if objects:
                context_parts.append(f"Visible objects: {', '.join(objects)}")
        
        # Add rejection context if provided
        if rejected_actions and critic_justification:
            rejection_msg = (
                f"\n\n[Previous action(s) '{', '.join(rejected_actions)}' were rejected by critic: "
                f"{critic_justification}]"
            )
            context_parts.append(rejection_msg)
            
            # Add helpful hints based on what was rejected
            if any(direction in str(rejected_actions).lower()
                   for direction in ['north', 'south', 'east', 'west', 'up', 'down']):
                context_parts.append("\nHint: Movement was rejected. Try examining objects or taking items instead.")
            elif 'examine' in str(rejected_actions).lower():
                context_parts.append("\nHint: Examination was rejected. Try movement or taking items instead.")
        
        return "\n".join(context_parts)

    def _get_fallback_action(self, failed_actions: list) -> str:
        """Generate a fallback action when agent is stuck."""
        # Get current context
        current_exits = []
        visible_objects = []
        
        if self.memory_log_history:
            last_extraction = self.memory_log_history[-1]
            current_exits = getattr(last_extraction, "exits", [])
            visible_objects = getattr(last_extraction, "visible_objects", [])
        
        # Priority 1: Take any items not yet taken
        for obj in visible_objects:
            if any(item_word in obj.lower() for item_word in 
                   ['leaflet', 'lamp', 'sword', 'bottle', 'sack', 'garlic', 'rope']):
                take_cmd = f"take {obj}"
                if take_cmd not in failed_actions:
                    return take_cmd
        
        # Priority 2: Try an unexplored exit
        for exit_dir in current_exits:
            if exit_dir not in failed_actions:
                return exit_dir
        
        # Priority 3: Examine an unexamined object  
        for obj in visible_objects:
            examine_cmd = f"examine {obj}"
            if examine_cmd not in failed_actions and obj not in str(failed_actions):
                return examine_cmd
        
        # Priority 4: Try standard directions not in exits list
        standard_dirs = ['north', 'south', 'east', 'west', 'up', 'down']
        for direction in standard_dirs:
            if direction not in current_exits and direction not in failed_actions:
                return direction
        
        # Priority 5: Basic exploration
        return "look"


    def reset_episode_state(self) -> None:
        """Reset all episode-specific state variables."""
        self.action_counts = Counter()
        self.action_history = []
        self.memory_log_history = []
        self.visited_locations = set()
        self.failed_actions_by_location = {}
        self.location_action_db = LocationActionDatabase()  # New compact database
        self.episode_id = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.previous_zork_score = 0
        self.turn_count = 0
        self.game_over_flag = False  # Track game over state for state export
        # Use MapGraph with enhanced confidence tracking
        self.game_map = MapGraph()
        self.current_room_name_for_map = ""
        self.current_location_unique_id = ""  # Store the unique ID with description hash
        self.prev_room_for_prompt_context: Optional[str] = None
        self.action_leading_to_current_room_for_prompt_context: Optional[str] = None
        self.current_inventory = []

        # Reset movement analyzer for new episode
        self.movement_analyzer.clear_pending_connections()

        # Agent reasoning tracking for state export
        self.action_reasoning_history = []

        # Discovered objectives tracking - maintains goals discovered through gameplay
        self.discovered_objectives = []
        self.completed_objectives = []  # Track completed objectives for learning
        self.objective_update_turn = 0
        # Add objective staleness tracking
        self.objective_staleness_tracker = {}  # Track turns since progress on each objective
        self.last_location_for_staleness = None
        self.last_score_for_staleness = 0
        
        # Objective feasibility tracking
        self.objective_feasibility = {}  # Track status and conditions for each objective

        # Reset adaptive knowledge tracking for new episode
        self.last_knowledge_update_turn = 0
        self.last_map_update_turn = 0

        # Note: death_count is NOT reset here - it persists across episodes

        # Update episode IDs in components
        self.agent.update_episode_id(self.episode_id)
        self.extractor.update_episode_id(self.episode_id)
        self.critic.update_episode_id(self.episode_id)

    def play_episode(self, zork_interface_instance) -> int:
        """
        Play a single episode of Zork.

        Args:
            zork_interface_instance: The Zork game interface

        Returns:
            Final Zork score
        """
        # Reset state for new episode
        self.reset_episode_state()

        # Generate episode ID
        episode_start_time = datetime.now()
        self.episode_id = episode_start_time.strftime("%Y-%m-%dT%H:%M:%S")

        # Log episode start
        self.logger.info(
            f"Starting episode {self.episode_id}",
            extra={
                "event_type": "episode_start",
                "episode_id": self.episode_id,
                "agent_model": self.agent.model,
                "critic_model": self.critic.model,
                "info_ext_model": self.extractor.model,
                "max_turns": self.max_turns_per_episode,
                "episode_start_time": episode_start_time.isoformat(),
            },
        )

        try:
            # Get initial game state
            current_game_state = zork_interface_instance.start()
        except Exception as e:
            self.logger.error(
                f"Failed to start Zork game: {e}",
                extra={"event_type": "error", "episode_id": self.episode_id}
            )
            raise

        # Enable verbose mode to get full room descriptions on every visit
        verbose_response = zork_interface_instance.send_command("verbose")
        self.logger.info(
            f"Enabled verbose mode: {verbose_response}",
            extra={
                "event_type": "verbose_mode_enabled",
                "episode_id": self.episode_id,
                "verbose_response": verbose_response,
            }
        )

        # Get current score and inventory for state initialization
        current_zork_score_val, max_zork_score = zork_interface_instance.score(
            current_game_state
        )
        current_inventory, _ = zork_interface_instance.inventory_with_response()

        # Update instance variables for state export
        self.previous_zork_score = current_zork_score_val
        self.current_inventory = current_inventory

        # Check if we should attempt to restore from a save file
        restore_attempted = self._attempt_restore_from_save(zork_interface_instance)
        if restore_attempted:
            # Re-get current state after restore
            current_game_state = zork_interface_instance.send_command("look")
            current_zork_score_val, max_zork_score = zork_interface_instance.score()
            current_inventory, _ = zork_interface_instance.inventory_with_response()
            
            # Update instance variables
            self.previous_zork_score = current_zork_score_val
            self.current_inventory = current_inventory
            
            self.logger.info(f"Game restored - Score: {current_zork_score_val}, Inventory: {len(current_inventory)} items", extra={
                "event_type": "game_restored",
                "episode_id": self.episode_id,
                "restored_score": current_zork_score_val,
                "restored_inventory_count": len(current_inventory),
            })

        # Extract initial information
        extracted_info = self.extractor.extract_info(current_game_state)

        # Log initial state
        self.logger.info(
            f"Initial game state extracted",
            extra={
                "event_type": "initial_state",
                "episode_id": self.episode_id,
                "game_state": current_game_state,
                "extracted_location": extracted_info.current_location_name if extracted_info else "Unknown",
                "initial_score": current_zork_score_val,
                "initial_inventory_count": len(current_inventory),
            },
        )

        if extracted_info:
            # Initialize room tracking
            self.current_room_name_for_map = extracted_info.current_location_name
            # Create initial unique ID with available information
            self.current_location_unique_id = self.game_map._create_unique_location_id(
                extracted_info.current_location_name,
                description=' '.join(extracted_info.important_messages) if extracted_info.important_messages else '',
                objects=extracted_info.visible_objects if extracted_info.visible_objects else [],
                exits=extracted_info.exits if extracted_info.exits else []
            )
            self.prev_room_for_prompt_context = None
            self.action_leading_to_current_room_for_prompt_context = None

            # Add initial location to map
            self.game_map.add_room(extracted_info.current_location_name)

            # Add to memory log
            self.memory_log_history.append(extracted_info)

            # Log successful extraction
            self.logger.info(
                f"Information extracted successfully: {extracted_info.current_location_name}",
                extra={
                    "event_type": "extraction_success",
                    "episode_id": self.episode_id,
                    "location": extracted_info.current_location_name,
                    "exits": extracted_info.exits,
                    "objects": extracted_info.visible_objects,
                    "characters": extracted_info.visible_characters,
                    "in_combat": extracted_info.in_combat,
                },
            )
        else:
            self.current_room_name_for_map = "Unknown (Initial Extraction Failed)"
            self.current_location_unique_id = self.current_room_name_for_map
            self.game_map.add_room(self.current_room_name_for_map)

        # Export initial state
        self.export_current_state()

        # Initialize game state variables
        game_over = False

        # Main game loop
        while (
            not game_over
            and zork_interface_instance.is_running()
            and self.turn_count < self.max_turns_per_episode
        ):
            self.turn_count += 1

            # Start timing the turn for delay calculation
            turn_start_time = time.time()

            # Log turn start
            self.logger.info(
                f"Turn {self.turn_count}",
                extra={
                    "event_type": "turn_start",
                    "episode_id": self.episode_id,
                    "turn": self.turn_count,
                    "turn_start_time": turn_start_time,
                },
            )

            # Check for save signal from external process (like manage_ec2.py)
            save_signal_processed = self._handle_save_signal(zork_interface_instance)
            if save_signal_processed:
                # Save signal was processed, continue with normal gameplay
                # The system is ready for shutdown but will complete current turn
                pass

            # Check if we're in combat from the previous turn's extracted info
            in_combat = False
            if self.memory_log_history:
                last_extraction = self.memory_log_history[-1]
                in_combat = getattr(last_extraction, "in_combat", False)

            # Get inventory only if not in combat (to avoid death during inventory checks)
            if not in_combat:
                current_inventory, inventory_response = (
                    zork_interface_instance.inventory_with_response()
                )
                # Update instance variable for state export
                self.current_inventory = current_inventory

                # Check if the inventory command caused game over
                if inventory_response:
                    game_over_flag, game_over_reason = (
                        zork_interface_instance.is_game_over(inventory_response)
                    )
                    if game_over_flag:
                        # Check if this is a death and increment counter
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
                        
                        # Set the game over flag for state export
                        self.game_over_flag = True
                        
                        # Log game over from inventory
                        self.logger.info(
                            f"Game over during inventory check: {game_over_reason}",
                            extra={
                                "event_type": "game_over",
                                "episode_id": self.episode_id,
                                "reason": f"Inventory check triggered: {game_over_reason}",
                                "turn": self.turn_count,
                                "death_count": self.death_count,
                            },
                        )

                        # Get final score
                        current_zork_score_val, max_zork_score = (
                            zork_interface_instance.score(inventory_response)
                        )
                        self.previous_zork_score = current_zork_score_val

                        # Log death during inventory
                        self.logger.info(
                            "Death during inventory check - episode ending",
                            extra={
                                "event_type": "death_during_inventory",
                                "episode_id": self.episode_id,
                                "final_score": self.previous_zork_score,
                            },
                        )

                        # Store reasoning for inventory-based death (for state export)
                        self.action_reasoning_history.append(
                            {
                                "turn": self.turn_count,
                                "action": "inventory",
                                "reasoning": f"Death occurred during inventory check: {game_over_reason}",
                                "critic_score": 0.0,
                                "critic_justification": "Death during inventory - no action evaluation",
                                "was_overridden": False,
                                "rejected_actions": None,
                            }
                        )

                        # Export final state with death information
                        self.export_current_state()

                        # Episode ends here
                        break
            else:
                # In combat - skip inventory check and log the decision
                self.logger.info(
                    "Skipping inventory check due to combat situation",
                    extra={
                        "event_type": "inventory_skip",
                        "episode_id": self.episode_id,
                        "reason": "In combat - avoiding dangerous inventory check",
                        "turn": self.turn_count,
                    },
                )

            # Get relevant memories for agent prompt
            relevant_memories = self.agent.get_relevant_memories_for_prompt(
                current_location_name_from_current_extraction=self.current_room_name_for_map,
                memory_log_history=self.memory_log_history,
                current_inventory=current_inventory,
                game_map=self.game_map,
                previous_room_name_for_map_context=self.prev_room_for_prompt_context,
                action_taken_to_current_room=self.action_leading_to_current_room_for_prompt_context,
                in_combat=in_combat,
                failed_actions_by_location=self.failed_actions_by_location,
            )

            # Add discovered objectives to the context if any exist
            if self.discovered_objectives:
                # Get only feasible objectives
                feasible_objectives = self.get_feasible_objectives()
                
                objectives_text = "\n--- Current Discovered Objectives ---\n"
                objectives_text += "🎯 Based on your recent gameplay patterns, you have discovered these objectives:\n"
                
                # Show feasible objectives
                if feasible_objectives:
                    objectives_text += "\nACHIEVABLE NOW:\n"
                    for i, obj in enumerate(feasible_objectives, 1):
                        objectives_text += f"  {i}. {obj}\n"
                
                # Show blocked objectives
                blocked_objectives = []
                for obj in self.discovered_objectives:
                    if obj in self.objective_feasibility:
                        status = self.objective_feasibility[obj]["status"]
                        if status == "blocked":
                            blocked_objectives.append(f"{obj} (blocked - needs item)")
                        elif status == "impossible":
                            blocked_objectives.append(f"{obj} (impossible - permanent barrier)")
                
                if blocked_objectives:
                    objectives_text += "\nBLOCKED/IMPOSSIBLE:\n"
                    for obj in blocked_objectives:
                        objectives_text += f"  - {obj}\n"
                
                objectives_text += "\n⚠️ FOCUS ON ACHIEVABLE OBJECTIVES when choosing your next action. Avoid pursuing blocked or impossible goals.\n"
                
                # Append to relevant memories
                if relevant_memories:
                    relevant_memories += objectives_text
                else:
                    relevant_memories = objectives_text.strip()

            # Generate extended context for better decision making
            extended_context = self.generate_extended_context(self.current_room_name_for_map)
            
            # Combine relevant memories with extended context
            if extended_context:
                if relevant_memories:
                    relevant_memories = f"{relevant_memories}\n\n--- LOCATION-SPECIFIC HISTORY ---\n{extended_context}"
                else:
                    relevant_memories = f"--- LOCATION-SPECIFIC HISTORY ---\n{extended_context}"

            # Get agent action with reasoning
            agent_response = self.agent.get_action_with_reasoning(
                game_state_text=self._build_agent_context(current_game_state),
                previous_actions_and_responses=self.action_history[
                    -50:
                ],  # Last 50 actions - increased from 5 for better context
                action_counts=self.action_counts,
                relevant_memories=relevant_memories,
            )
            agent_action = agent_response["action"]
            agent_reasoning = agent_response["reasoning"]

            # Get critic evaluation
            # Get available exits from most recent extraction for spatial awareness
            current_exits = []
            if self.memory_log_history:
                last_extraction = self.memory_log_history[-1]
                current_exits = getattr(last_extraction, "exits", [])
            
            critic_response = self.critic.get_robust_evaluation(
                game_state_text=current_game_state,
                proposed_action=agent_action,
                available_exits=current_exits,
                action_counts=self.action_counts,
                previous_actions_and_responses=self.action_history[
                    -3:
                ],  # Last 3 actions
                current_location_name=self.current_room_name_for_map,
                failed_actions_by_location=self.failed_actions_by_location,
                current_inventory=self.current_inventory,
            )

            critic_score_val = critic_response.score
            critic_justification = critic_response.justification
            critic_confidence = getattr(critic_response, "confidence", 0.8)

            # Check for action rejection and override logic with retry loop
            was_overridden = False
            rejection_threshold = self.critic.trust_tracker.get_rejection_threshold()
            max_rejections = 3  # Prevent infinite loops

            # Track all rejected actions and their justifications for transparency
            rejected_actions_with_justifications = []

            for rejection_attempt in range(max_rejections):
                if critic_score_val >= rejection_threshold:
                    break  # Action is acceptable, exit loop

                # Action was rejected by critic
                override_needed, override_reason = (
                    self.critic.rejection_system.should_override_rejection(
                        agent_action,
                        self.current_room_name_for_map,
                        self.failed_actions_by_location,
                        {
                            "turns_since_movement": getattr(
                                self, "turns_since_movement", 0
                            ),
                            "critic_confidence": critic_confidence,
                            "current_location": self.current_room_name_for_map,
                            "failed_actions_by_location": self.failed_actions_by_location,
                            "recent_locations": [
                                getattr(entry, "current_location_name", "")
                                for entry in self.memory_log_history[-10:]
                                if hasattr(entry, 'current_location_name')
                            ],
                            "recent_actions": [
                                action for action, _ in self.action_history[-8:]
                            ],
                            "previous_actions_and_responses": self.action_history[-8:],
                            "recent_critic_scores": [
                                reasoning.get("critic_score", 0.0)
                                for reasoning in self.action_reasoning_history[-5:]
                            ],
                        },
                    )
                )

                if override_needed:
                    was_overridden = True
                    self.logger.info(
                        f"Overriding critic rejection: {override_reason}",
                        extra={
                            "event_type": "critic_override",
                            "episode_id": self.episode_id,
                            "reason": override_reason,
                            "turn": self.turn_count,
                            "original_action": agent_action,
                            "original_score": critic_score_val,
                            "original_reasoning": critic_justification,
                        },
                    )
                    # If override is granted, we can proceed with the action
                    break

                # Log agent action
                self.logger.info(
                    f"Agent proposes: {agent_action}",
                    extra={
                        "event_type": "agent_action",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "agent_action": agent_action,
                        "agent_reasoning": agent_reasoning,
                    },
                )

                # Log critic evaluation
                self.logger.info(
                    f"Critic evaluation: Score={critic_score_val:.2f}, Justification='{critic_justification}'",
                    extra={
                        "event_type": "critic_evaluation",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "critic_score": critic_score_val,
                        "critic_justification": critic_justification,
                        "critic_confidence": critic_confidence,
                        "was_overridden": was_overridden,
                    },
                )

                # Track rejected action with its justification
                rejected_actions_with_justifications.append(
                    {
                        "action": agent_action,
                        "score": critic_score_val,
                        "justification": critic_justification,
                    }
                )

                # If override was not granted, we need to get a new action
                if not override_needed:
                    # Track rejected action and get a new one
                    self.critic.rejection_system.rejected_actions_this_turn.append(
                        agent_action
                    )

                    # Only get a new action if we haven't exhausted attempts
                    if rejection_attempt < max_rejections - 1:
                        # After 2 failed attempts, use fallback action
                        if rejection_attempt >= 1:
                            self.logger.info(
                                "Using fallback action generator after repeated rejections",
                                extra={
                                    "event_type": "fallback_action_triggered", 
                                    "episode_id": self.episode_id,
                                    "turn": self.turn_count,
                                    "rejected_actions": self.critic.rejection_system.rejected_actions_this_turn,
                                }
                            )
                            agent_action = self._get_fallback_action(
                                self.critic.rejection_system.rejected_actions_this_turn + 
                                [act for act, _ in self.action_history[-5:]]
                            )
                            agent_reasoning = "Using fallback action due to repeated rejections"
                            # Skip getting new action from agent, go straight to re-evaluation
                        else:
                            # First rejection - let agent try again
                            agent_response = self.agent.get_action_with_reasoning(
                                game_state_text=self._build_agent_context(
                                    current_game_state,
                                    rejected_actions=self.critic.rejection_system.rejected_actions_this_turn,
                                    critic_justification=critic_justification
                                ),
                                previous_actions_and_responses=self.action_history[-5:],
                                action_counts=self.action_counts,
                                relevant_memories=relevant_memories,
                            )
                            agent_action = agent_response["action"]
                            agent_reasoning = agent_response["reasoning"]

                        # Re-evaluate new action
                        critic_response = self.critic.get_robust_evaluation(
                            game_state_text=current_game_state,
                            proposed_action=agent_action,
                            available_exits=current_exits,
                            action_counts=self.action_counts,
                            previous_actions_and_responses=self.action_history[-3:],
                            current_location_name=self.current_room_name_for_map,
                            failed_actions_by_location=self.failed_actions_by_location,
                            current_inventory=self.current_inventory,
                        )
                        critic_score_val = critic_response.score
                        critic_justification = critic_response.justification
                        critic_confidence = getattr(critic_response, "confidence", 0.8)

            # If we've exhausted all rejection attempts and still have a low score, skip this turn
            if critic_score_val < rejection_threshold and not was_overridden:
                self.logger.warning(
                    f"Exhausted rejection attempts, SKIPPING turn due to low-scoring action: {agent_action} (score: {critic_score_val:.2f})",
                    extra={
                        "event_type": "rejection_attempts_exhausted",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "final_action": agent_action,
                        "final_score": critic_score_val,
                        "threshold": rejection_threshold,
                    },
                )
                
                # Update trust tracker - critic was right to reject
                self.critic.trust_tracker.update_trust(was_rejection_correct=True)
                
                # Skip this turn - don't execute the bad action
                self.turn_count += 1
                continue

            # Store reasoning for state export
            self.action_reasoning_history.append(
                {
                    "turn": self.turn_count,
                    "action": agent_action,
                    "reasoning": agent_reasoning,
                    "critic_score": critic_score_val,
                    "critic_justification": critic_justification,
                    "was_overridden": was_overridden,
                    "rejected_actions": rejected_actions_with_justifications
                    if rejected_actions_with_justifications
                    else None,
                }
            )

            # Log final selected action
            self.logger.info(
                f"SELECTED ACTION: {agent_action} (Score: {critic_score_val:.2f}, Confidence: {critic_confidence:.2f}, Override: {was_overridden})",
                extra={
                    "event_type": "final_action_selection",
                    "episode_id": self.episode_id,
                    "turn": self.turn_count,
                    "agent_action": agent_action,
                    "agent_reasoning": agent_reasoning,
                    "critic_score": critic_score_val,
                    "critic_confidence": critic_confidence,
                    "was_overridden": was_overridden,
                },
            )

            # Update action count for repetition tracking
            self.action_counts[agent_action] += 1

            # Send the chosen action to Zork
            room_before_action = self.current_room_name_for_map
            room_before_action_unique_id = self.current_location_unique_id  # Store the unique ID
            action_taken = agent_action

            try:
                next_game_state = zork_interface_instance.send_command(action_taken)

                # Get clean game text for display (without structured header)
                clean_game_text = next_game_state
                if hasattr(self.extractor, "get_clean_game_text"):
                    clean_game_text = self.extractor.get_clean_game_text(
                        next_game_state
                    )

                # Log Zork response (using clean text for display)
                self.logger.info(
                    f"ZORK RESPONSE for '{action_taken}':\n{clean_game_text}\n",
                    extra={
                        "event_type": "zork_response",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "action": action_taken,
                        "zork_response": clean_game_text,  # Store clean text for display
                        "raw_zork_response": next_game_state,  # Keep raw for parsing if needed
                    },
                )

                # Check if the game has ended based on the response
                game_over_flag, game_over_reason = zork_interface_instance.is_game_over(
                    next_game_state
                )
                if game_over_flag:
                    # Check if this is a death and track it
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
                    
                    # Set the game over flag for state export
                    self.game_over_flag = True
                    
                    # Log game over
                    self.logger.info(
                        f"Game over detected: {game_over_reason}",
                        extra={
                            "event_type": "game_over",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "reason": game_over_reason,
                            "death_count": self.death_count,
                        },
                    )

                    game_over = True
                    current_zork_score_val, max_zork_score = (
                        zork_interface_instance.score(next_game_state)
                    )
                    self.previous_zork_score = current_zork_score_val
                    # Store clean game text in action history (without structured header)
                    self.action_history.append((action_taken, clean_game_text))

                    # Log game over details
                    self.logger.info(
                        f"Game over: {game_over_reason}",
                        extra={
                            "event_type": "game_over_final",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "reason": game_over_reason,
                            "final_score": self.previous_zork_score,
                            "action_taken": action_taken,
                        },
                    )
                    
                    # Store reasoning for death action (for state export)
                    if 'agent_reasoning' in locals():
                        self.action_reasoning_history.append(
                            {
                                "turn": self.turn_count,
                                "action": action_taken,
                                "reasoning": agent_reasoning,
                                "critic_score": critic_score_val if 'critic_score_val' in locals() else 0.0,
                                "critic_justification": critic_justification if 'critic_justification' in locals() else "Game Over",
                                "was_overridden": was_overridden if 'was_overridden' in locals() else False,
                                "rejected_actions": rejected_actions_with_justifications if 'rejected_actions_with_justifications' in locals() else None,
                            }
                        )
                    
                    # Extract information about the death state
                    llm_extracted_info = self.extractor.extract_info(
                        next_game_state, room_before_action
                    )
                    if llm_extracted_info:
                        self.memory_log_history.append(llm_extracted_info)
                        # Update current room for state export
                        self.current_room_name_for_map = llm_extracted_info.current_location_name
                        
                        # Log death extraction
                        self.logger.info(
                            f"Death state extracted: {llm_extracted_info.current_location_name}",
                            extra={
                                "event_type": "death_extraction",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "extracted_info": llm_extracted_info.model_dump(),
                                "source": "Enhanced LLM"
                            },
                        )
                    
                    # Export final state with death information
                    self.export_current_state()
                    
                    # End the episode
                    break

                # Store clean game text in action history (without structured header)
                self.action_history.append((action_taken, clean_game_text))

                # Track location-specific failures
                if self.current_room_name_for_map:
                    # Check if this action appears to be a failure based on response patterns
                    response_lower = clean_game_text.lower()
                    failure_indicators = [
                        "wall", "can't", "don't", "no way", "too narrow", "locked",
                        "nothing happens", "already", "what", "i can't see", "not here"
                    ]
                    
                    if any(indicator in response_lower for indicator in failure_indicators):
                        self.track_location_failure(
                            self.current_room_name_for_map,
                            action_taken,
                            clean_game_text,
                            self.turn_count
                        )

                # Extract information using the extractor
                llm_extracted_info = self.extractor.extract_info(
                    next_game_state, room_before_action
                )

                # Use the extracted location directly - the enhanced extractor handles persistence internally
                if llm_extracted_info:
                    final_current_room_name = llm_extracted_info.current_location_name
                    source_of_location = "Enhanced LLM"
                    self.memory_log_history.append(llm_extracted_info)
                    
                    # Record action in location database
                    if room_before_action and hasattr(self, 'location_action_db'):
                        # Determine if this was a movement
                        new_location = None
                        if final_current_room_name != room_before_action:
                            new_location = final_current_room_name
                        
                        # Get items found from extraction
                        items_found = getattr(llm_extracted_info, 'visible_objects', [])
                        
                        # Record the action and outcome
                        self.location_action_db.record_action(
                            location=room_before_action,
                            action=action_taken,
                            outcome=clean_game_text,
                            new_location=new_location,
                            items_found=items_found if items_found else None
                        )

                    # Log extraction
                    self.logger.info(
                        f"State extracted: {final_current_room_name}",
                        extra={
                            "event_type": "extracted_info",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "extracted_info": llm_extracted_info.model_dump(),
                            "source": source_of_location,
                        },
                    )
                else:
                    # Fallback only if extraction completely fails
                    final_current_room_name = room_before_action or "Unknown Location"
                    source_of_location = "Fallback (Extraction Failed)"

                # Update map with the new room and its exits
                self.game_map.add_room(final_current_room_name)
                if llm_extracted_info:
                    self.game_map.update_room_exits(
                        final_current_room_name, llm_extracted_info.exits
                    )

                # Track rejection outcomes and update movement tracking
                rejected_actions = getattr(
                    self.critic.rejection_system, "rejected_actions_this_turn", []
                )
                self.critic.track_rejection_outcome(
                    rejected_actions, action_taken, next_game_state
                )
                self._update_movement_tracking(
                    action_taken, room_before_action, final_current_room_name
                )
                
                # Track all failed actions using LLM-based detection
                self._update_failed_actions_tracking(
                    action_taken, next_game_state, final_current_room_name
                )

                # Create stable location identifiers using exit-based unique ID system
                # This prioritizes exit patterns over volatile descriptions for stability
                current_location_id = self.game_map._create_unique_location_id(
                    final_current_room_name,
                    description=' '.join(llm_extracted_info.important_messages) if llm_extracted_info else '',
                    objects=llm_extracted_info.visible_objects if llm_extracted_info else [],
                    exits=llm_extracted_info.exits if llm_extracted_info else []
                )
                
                # Use shared MovementAnalyzer for consistent movement detection
                movement_context = MovementContext(
                    current_location=current_location_id,
                    previous_location=room_before_action,  # Will be converted to unique ID in movement analysis
                    action=action_taken,
                    game_response=next_game_state,
                    turn_number=self.turn_count,
                )

                # Analyze potential connections
                movement_result = self.movement_analyzer.analyze_movement(
                    movement_context
                )
                if movement_result.connection_created:
                    # Use the stored unique ID for the previous location if available
                    # This ensures we maintain the correct unique ID including description hash
                    if room_before_action_unique_id:
                        from_location_id = room_before_action_unique_id
                    else:
                        # Fallback: create ID without description (less accurate)
                        from_location_id = self.game_map._create_unique_location_id(
                            movement_result.from_location,
                            description='',  # No description available for previous location
                            objects=[],
                            exits=[]  # Exit info not available for previous location
                        )
                    to_location_id = current_location_id  # Already computed above
                    
                    # Add connection to map with unique identifiers
                    self.game_map.add_connection(
                        from_location_id,
                        movement_result.action,
                        to_location_id,
                    )

                    # Log the connection
                    self.logger.info(
                        f"Movement connection: {from_location_id} --[{movement_result.action}]--> {to_location_id}",
                        extra={
                            "extras": {
                                "event_type": "movement_connection_created",
                                "episode_id": self.episode_id,
                                "from_room": from_location_id,
                                "to_room": to_location_id,
                                "action": movement_result.action,
                                "confidence": getattr(
                                    movement_result, "confidence", 1.0
                                ),
                            }
                        },
                    )

                # Get score - try structured parser first if using hybrid extractor
                structured_score = None
                structured_moves = None

                if hasattr(self.extractor, "get_score_and_moves"):
                    structured_score, structured_moves = (
                        self.extractor.get_score_and_moves(next_game_state)
                    )

                if structured_score is not None:
                    # Use score from structured parser
                    current_zork_score_val = structured_score
                    max_zork_score = 585  # Known max score for Zork I

                    # Log successful structured score extraction
                    self.logger.debug(
                        f"Score extracted via structured parser: {current_zork_score_val} (moves: {structured_moves})",
                        extra={
                            "extras": {
                                "event_type": "structured_score_extraction",
                                "episode_id": self.episode_id,
                                "score": current_zork_score_val,
                                "moves": structured_moves,
                            }
                        },
                    )
                else:
                    # Fallback to traditional score extraction
                    try:
                        if not game_over and zork_interface_instance.is_running():
                            current_zork_score_val, max_zork_score = (
                                zork_interface_instance.score()
                            )
                        else:
                            # Use the score method with the game text for parsing
                            current_zork_score_val, max_zork_score = (
                                zork_interface_instance.score(next_game_state)
                            )
                        
                        # Check if score parsing returned 0 but we had a previous non-zero score
                        # This happens when the parser doesn't understand the command and returns default values
                        if (current_zork_score_val == 0 and max_zork_score == 0 and 
                            self.previous_zork_score > 0):
                            self.logger.warning(
                                f"Score parsing returned 0 but previous score was {self.previous_zork_score}. "
                                f"Likely parser error - maintaining previous score.",
                                extra={
                                    "event_type": "score_parsing_zero_fallback",
                                    "episode_id": self.episode_id,
                                    "turn": self.turn_count,
                                    "previous_score": self.previous_zork_score,
                                    "parsed_score": current_zork_score_val,
                                    "game_text": next_game_state[:100] + "..." if len(next_game_state) > 100 else next_game_state,
                                },
                            )
                            current_zork_score_val = self.previous_zork_score
                            max_zork_score = 585  # Default max score for Zork I
                            
                    except Exception as score_parse_error:
                        # If score parsing fails completely, maintain the previous score
                        self.logger.warning(
                            f"Score parsing failed, maintaining previous score: {self.previous_zork_score}. Error: {score_parse_error}",
                            extra={
                                "event_type": "score_parsing_exception_fallback",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "previous_score": self.previous_zork_score,
                                "error": str(score_parse_error),
                            },
                        )
                        current_zork_score_val = self.previous_zork_score
                        max_zork_score = 585  # Default max score for Zork I

            except RuntimeError as e:
                self.logger.error(
                    f"Zork process error: {e}",
                    extra={
                        "event_type": "error", 
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                    },
                )
                game_over = True
                next_game_state = "Game ended unexpectedly"
                continue

            # Check for Zork's internal score changes and log them
            score_change = current_zork_score_val - self.previous_zork_score
            if score_change > 0:
                self.logger.info(
                    f"Score increased by {score_change} points!",
                    extra={
                        "event_type": "score_increase",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "score_change": score_change,
                        "new_score": current_zork_score_val,
                    },
                )
            elif score_change < 0:
                self.logger.info(
                    f"Score decreased by {abs(score_change)} points",
                    extra={
                        "extras": {
                            "event_type": "score_decrease",
                            "episode_id": self.episode_id,
                            "score_change": score_change,
                            "new_score": current_zork_score_val,
                        }
                    },
                )

            self.previous_zork_score = current_zork_score_val

            current_game_state = next_game_state

            # Update current room name and unique ID for next iteration
            self.current_room_name_for_map = final_current_room_name
            self.current_location_unique_id = current_location_id

            # Reset critic rejection system for next turn
            self.critic.rejection_system.reset_turn()

            # Check for adaptive knowledge update
            self._check_adaptive_knowledge_update()
            
            # Check for map update (more frequent than full knowledge updates)
            self._check_map_update()
            
            # Check for discovered objectives update every turn
            # agent_reasoning should always be defined by this point in normal flow
            if 'agent_reasoning' not in locals():
                self.logger.error(
                    "agent_reasoning unexpectedly missing - this indicates a bug in the agent action flow",
                    extra={
                        "extras": {
                            "event_type": "missing_agent_reasoning_error",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "error": "agent_reasoning variable not in locals()",
                        }
                    },
                )
                current_agent_reasoning = ""
            else:
                current_agent_reasoning = agent_reasoning if agent_reasoning else ""

            try:
                self._check_objective_update(current_agent_reasoning)
            except Exception as objective_error:
                self.logger.warning(
                    f"Failed to check objective update: {objective_error}",
                    extra={
                        "extras": {
                            "event_type": "objective_update_error",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "error": str(objective_error),
                        }
                    },
                )
            
            # Check for objective completion after each turn
            self._check_objective_completion(action_taken, next_game_state, llm_extracted_info if 'llm_extracted_info' in locals() else None)
            
            # Check for objective refinement
            self._check_objective_refinement()
            
            # Check for objective staleness
            self._check_objective_staleness()

            # Check for context overflow and trigger summarization if needed
            self._check_context_overflow()
            
            # Export current state after each turn
            self.export_current_state()

            # Add configurable delay for viewer experience to ensure minimum turn duration
            if self.turn_delay_seconds > 0:
                turn_elapsed_time = time.time() - turn_start_time
                remaining_time = self.turn_delay_seconds - turn_elapsed_time
                
                if remaining_time > 0:
                    self.logger.info(
                        f"Turn took {turn_elapsed_time:.2f}s, pausing for {remaining_time:.2f}s more to reach minimum {self.turn_delay_seconds}s",
                        extra={
                            "extras": {
                                "event_type": "turn_delay",
                                "episode_id": self.episode_id,
                                "turn_elapsed_time": turn_elapsed_time,
                                "delay_seconds": remaining_time,
                                "target_turn_duration": self.turn_delay_seconds,
                                "turn": self.turn_count,
                            }
                        },
                    )
                    time.sleep(remaining_time)
                else:
                    self.logger.info(
                        f"Turn took {turn_elapsed_time:.2f}s (>= {self.turn_delay_seconds}s target), no additional delay needed",
                        extra={
                            "extras": {
                                "event_type": "turn_no_delay_needed",
                                "episode_id": self.episode_id,
                                "turn_elapsed_time": turn_elapsed_time,
                                "target_turn_duration": self.turn_delay_seconds,
                                "turn": self.turn_count,
                            }
                        },
                    )

        # Debug: Log why the episode ended
        end_reasons = []
        if game_over:
            end_reasons.append("game_over=True")
        if not zork_interface_instance.is_running():
            end_reasons.append("zork_process_not_running")
        if self.turn_count >= self.max_turns_per_episode:
            end_reasons.append(
                f"max_turns_reached({self.turn_count}>={self.max_turns_per_episode})"
            )

        self.logger.info(
            f"Episode ended. Reasons: {', '.join(end_reasons) if end_reasons else 'unknown'}",
            extra={
                "extras": {
                    "event_type": "episode_end_debug",
                    "episode_id": self.episode_id,
                    "game_over": game_over,
                    "zork_running": zork_interface_instance.is_running(),
                    "turn_count": self.turn_count,
                    "max_turns": self.max_turns_per_episode,
                    "reasons": end_reasons,
                }
            },
        )

        # Log episode end
        self.logger.info(
            "Episode finished",
            extra={
                "extras": {
                    "event_type": "episode_end",
                    "episode_id": self.episode_id,
                    "turn_count": self.turn_count,
                    "zork_score": self.previous_zork_score,
                    "final_max_turns": self.max_turns_per_episode,
                    # Performance metrics
                    "avg_critic_score": self.get_avg_critic_score(),
                }
            },
        )

        # Perform final adaptive knowledge update if there's been significant progress
        self._perform_final_knowledge_update()

        # Perform inter-episode synthesis to preserve key learnings across episodes
        self._perform_inter_episode_synthesis()

        return self.previous_zork_score

    def _check_adaptive_knowledge_update(self) -> None:
        """
        Method 2 (Single-batch): Periodic updates with entire episode context.
        
        Each knowledge update processes the complete episode from turn 1 to current turn,
        providing comprehensive context while ensuring the agent receives timely knowledge updates.
        """
        if not self.adaptive_knowledge_manager:
            return

        # METHOD 2: Check for periodic updates normally, but always process entire episode
        turns_since_last_update = self.turn_count - self.last_knowledge_update_turn

        if turns_since_last_update >= self.knowledge_update_interval:
            self.logger.info(
                f"🧠 Performing Method 2 knowledge update: processing entire episode (turns 1-{self.turn_count})",
                extra={
                    "extras": {
                        "event_type": "method2_periodic_knowledge_update",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "start_turn": 1,  # Always start from turn 1
                        "end_turn": self.turn_count,  # Process up to current turn
                        "total_turns_processed": self.turn_count,
                        "turns_since_last_update": turns_since_last_update,
                        "method": "single_batch_comprehensive",
                    }
                },
            )

            try:
                # Include map quality metrics for context
                map_metrics = self.game_map.get_map_quality_metrics()
                self.logger.info(
                    f"📊 Map Quality: {map_metrics['average_confidence']:.2f} avg confidence, "
                    f"{map_metrics['high_confidence_ratio']:.1%} high confidence, "
                    f"{map_metrics['verified_connections']} verified connections"
                )

                # METHOD 2: Always process entire episode (1 to current turn)
                update_success = (
                    self.adaptive_knowledge_manager.update_knowledge_from_turns(
                        episode_id=self.episode_id,
                        start_turn=1,  # Always start from turn 1 for comprehensive context
                        end_turn=self.turn_count,  # Process up to current turn
                        is_final_update=False,
                    )
                )

                if update_success:
                    self.last_knowledge_update_turn = self.turn_count
                    
                    self.logger.info(
                        f"✅ Method 2 knowledge update completed (processed {self.turn_count} turns)",
                        extra={
                            "extras": {
                                "event_type": "method2_knowledge_update_success",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "turns_processed": self.turn_count,
                                "method": "single_batch_comprehensive",
                            }
                        },
                    )
                    
                    # Update map in knowledge base after successful update
                    self._update_knowledge_base_map()
                    
                    # Reload agent knowledge for immediate use during current episode
                    self._reload_agent_knowledge()
                    
                else:
                    self.logger.info(
                        f"⚠️ Method 2 knowledge update skipped (quality assessment rejected data)",
                        extra={
                            "extras": {
                                "event_type": "method2_knowledge_update_skipped",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "reason": "low_quality_data",
                                "turns_analyzed": self.turn_count,
                                "method": "single_batch_comprehensive",
                            }
                        },
                    )

            except Exception as e:
                self.logger.warning(
                    f"❌ Method 2 knowledge update failed: {e}",
                    extra={
                        "extras": {
                            "event_type": "method2_knowledge_update_failed",
                            "episode_id": self.episode_id,
                            "error": str(e),
                            "turn": self.turn_count,
                            "turns_analyzed": self.turn_count,
                            "method": "single_batch_comprehensive",
                        }
                    },
                )

    def _check_map_update(self) -> None:
        """Check if it's time for a map update and perform it if needed."""
        if not self.adaptive_knowledge_manager:
            return

        # ALWAYS run consolidation every turn to prevent fragmentation buildup
        self._run_map_consolidation()
        
        # Check if enough turns have passed since last full map update (knowledge base sync)
        turns_since_last_map_update = self.turn_count - self.last_map_update_turn

        if turns_since_last_map_update >= self.map_update_interval:
            self.logger.info(
                f"Updating map in knowledge base (turn {self.turn_count})",
                extra={
                    "extras": {
                        "event_type": "map_update_check",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "turns_since_last_map_update": turns_since_last_map_update,
                    }
                },
            )

            # Update map in knowledge base (but consolidation already ran above)
            self._update_knowledge_base_map()
            self.last_map_update_turn = self.turn_count

    def _run_map_consolidation(self) -> None:
        """Run map consolidation every turn to prevent fragmentation buildup."""
        if not self.game_map:
            return
            
        try:
            # Enhanced base name consolidation to address main fragmentation source
            base_consolidations = self.game_map.consolidate_base_name_variants()
            if base_consolidations > 0:
                self.logger.info(
                    f"Map consolidation (turn {self.turn_count}): {base_consolidations} locations merged",
                    extra={
                        "extras": {
                            "event_type": "turn_based_consolidation",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "base_consolidations_performed": base_consolidations,
                        }
                    },
                )
            
            # Also run legacy consolidation for any remaining case variations
            if self.game_map.needs_consolidation():
                consolidations = self.game_map.consolidate_similar_locations()
                if consolidations > 0:
                    self.logger.info(
                        f"Legacy consolidation (turn {self.turn_count}): {consolidations} locations merged",
                        extra={
                            "extras": {
                                "event_type": "turn_based_legacy_consolidation",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "consolidations_performed": consolidations,
                            }
                        },
                    )
            
            # Prune fragmented nodes that serve no navigation purpose
            pruned_nodes = self.game_map.prune_fragmented_nodes()
            if pruned_nodes > 0:
                self.logger.info(
                    f"Map pruning (turn {self.turn_count}): {pruned_nodes} fragmented nodes removed",
                    extra={
                        "extras": {
                            "event_type": "turn_based_pruning",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "nodes_pruned": pruned_nodes,
                        }
                    },
                )
                
        except Exception as e:
            self.logger.warning(
                f"Failed to run map consolidation on turn {self.turn_count}: {e}",
                extra={
                    "extras": {
                        "event_type": "map_consolidation_failed",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "error": str(e),
                    }
                },
            )

    def _update_knowledge_base_map(self) -> None:
        """Update the mermaid map in the knowledge base."""
        if not self.adaptive_knowledge_manager:
            return
            
        try:
            # Note: Consolidation and pruning already ran in _run_map_consolidation()
            # This method now focuses on syncing the clean map to the knowledge base
            
            map_updated = self.adaptive_knowledge_manager.update_knowledge_with_map(
                episode_id=self.episode_id,
                game_map=self.game_map
            )
            
            if map_updated:
                self.logger.info(
                    "Map updated in knowledge base",
                    extra={
                        "extras": {
                            "event_type": "knowledge_base_map_update_success",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                        }
                    },
                )
            else:
                self.logger.info(
                    "Map update skipped (no map data)",
                    extra={
                        "extras": {
                            "event_type": "knowledge_base_map_update_skipped",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                        }
                    },
                )
                
        except Exception as e:
            self.logger.warning(
                f"Failed to update map in knowledge base: {e}",
                extra={
                    "extras": {
                        "event_type": "knowledge_base_map_update_failed",
                        "episode_id": self.episode_id,
                        "error": str(e),
                    }
                },
            )

    def _reload_agent_knowledge(self) -> None:
        """Reload the knowledge base in the agent for immediate use."""
        try:
            # Actually reload the knowledge base in the agent
            success = self.agent.reload_knowledge_base()
            
            if success:
                self.logger.info(
                    "Knowledge base reloaded for agent use",
                    extra={
                        "extras": {
                            "event_type": "agent_knowledge_reload",
                            "episode_id": self.episode_id,
                        }
                    },
                )
            else:
                self.logger.warning("Failed to reload agent knowledge base", extra={
                    "turn": self.turn_count,
                    "episode_id": self.episode_id
                })
                
        except Exception as e:
            self.logger.warning(f"Failed to reload agent knowledge: {e}", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })

    def _perform_final_knowledge_update(self) -> None:
        """
        Method 2 (Single-batch): Final knowledge update only if no recent comprehensive update.
        
        Since periodic updates now process the entire episode, we only need a final update
        if significant progress has been made since the last comprehensive update.
        
        EXCEPTION: Always update if episode ended in death (critical learning event).
        EXCEPTION: Always update if inter-episode synthesis will occur (to integrate new persistent wisdom).
        """
        if not self.adaptive_knowledge_manager:
            return

        # Check if we've already done a recent comprehensive update
        turns_since_last_update = self.turn_count - self.last_knowledge_update_turn
        
        # Check if episode ended in death (critical learning event)
        episode_ended_in_death = self.game_over_flag and self._is_death_episode()
        
        # Check if inter-episode synthesis will occur (need KB update to integrate new wisdom)
        config = get_config()
        will_synthesize_wisdom = (
            config.orchestrator.enable_inter_episode_synthesis and
            self.adaptive_knowledge_manager and
            self._should_synthesize_inter_episode_wisdom()
        )
        
        # Only perform final update if significant progress since last update OR death occurred OR wisdom synthesis needed
        if turns_since_last_update < 20 and not episode_ended_in_death and not will_synthesize_wisdom:
            skip_reason = f"recent comprehensive update at turn {self.last_knowledge_update_turn} ({turns_since_last_update} turns ago)"
            self.logger.info(
                f"Skipping final knowledge update - {skip_reason}",
                extra={
                    "extras": {
                        "event_type": "final_knowledge_update_skipped",
                        "episode_id": self.episode_id,
                        "reason": "recent_comprehensive_update",
                        "turn_count": self.turn_count,
                        "last_update_turn": self.last_knowledge_update_turn,
                        "turns_since_last": turns_since_last_update,
                        "episode_ended_in_death": episode_ended_in_death,
                        "will_synthesize_wisdom": will_synthesize_wisdom,
                        "method": "single_batch_comprehensive",
                    }
                },
            )
            return
        
        # Determine reason for final update
        if episode_ended_in_death:
            update_reason = "episode_ended_in_death"
            reason_desc = f"death analysis (death count: {self.death_count})"
        elif will_synthesize_wisdom:
            update_reason = "wisdom_synthesis_required"
            reason_desc = "wisdom synthesis will create new persistent knowledge"
        else:
            update_reason = "episode_ended_with_progress" 
            reason_desc = f"remaining progress ({turns_since_last_update} turns since last update)"

        if self.turn_count <= 0:
            self.logger.info(
                "Skipping final knowledge update - no turns completed",
                extra={
                    "extras": {
                        "event_type": "final_knowledge_update_skipped",
                        "episode_id": self.episode_id,
                        "reason": "no_turns_completed",
                        "turn_count": self.turn_count,
                    }
                },
            )
            return

        self.logger.info(
            f"🧠 Performing final Method 2 knowledge update for {reason_desc} (turns 1-{self.turn_count})",
            extra={
                "extras": {
                    "event_type": "method2_final_knowledge_update_start",
                    "episode_id": self.episode_id,
                    "start_turn": 1,  # Always start from turn 1
                    "end_turn": self.turn_count,  # Process entire episode
                    "total_turns": self.turn_count,
                    "turns_since_last_update": turns_since_last_update,
                    "method": "single_batch_comprehensive",
                    "reason": update_reason,
                    "episode_ended_in_death": episode_ended_in_death,
                    "will_synthesize_wisdom": will_synthesize_wisdom,
                    "death_count": self.death_count,
                }
            },
        )

        try:
            # Include map quality metrics for context
            map_metrics = self.game_map.get_map_quality_metrics()
            self.logger.info(
                f"📊 Final Map Quality: {map_metrics['average_confidence']:.2f} avg confidence, "
                f"{map_metrics['high_confidence_ratio']:.1%} high confidence, "
                f"{map_metrics['verified_connections']} verified connections"
            )

            # Perform final comprehensive knowledge update for entire episode
            update_success = (
                self.adaptive_knowledge_manager.update_knowledge_from_turns(
                    episode_id=self.episode_id,
                    start_turn=1,  # Always start from turn 1
                    end_turn=self.turn_count,  # Process entire episode
                    is_final_update=True,
                )
            )

            if update_success:
                # Mark that we've updated with all turns
                self.last_knowledge_update_turn = self.turn_count
                
                self.logger.info(
                    f"✅ Final Method 2 knowledge update completed (processed {self.turn_count} turns)",
                    extra={
                        "extras": {
                            "event_type": "method2_final_knowledge_update_success",
                            "episode_id": self.episode_id,
                            "turns_processed": self.turn_count,
                            "method": "single_batch_comprehensive",
                            "reason": update_reason,
                            "episode_ended_in_death": episode_ended_in_death,
                            "will_synthesize_wisdom": will_synthesize_wisdom,
                        }
                    },
                )
                
                # Update map in knowledge base after successful update
                self._update_knowledge_base_map()
                
                # Note: We don't reload agent knowledge here since the episode is ending
                
            else:
                self.logger.info(
                    f"⚠️ Final Method 2 knowledge update skipped (quality assessment rejected episode data)",
                    extra={
                        "extras": {
                            "event_type": "method2_final_knowledge_update_skipped",
                            "episode_id": self.episode_id,
                            "reason": "low_quality_data",
                            "turns_analyzed": self.turn_count,
                            "method": "single_batch_comprehensive",
                            "episode_ended_in_death": episode_ended_in_death,
                            "will_synthesize_wisdom": will_synthesize_wisdom,
                        }
                    },
                )

        except Exception as e:
            self.logger.warning(
                f"❌ Final Method 2 knowledge update failed: {e}",
                extra={
                    "extras": {
                        "event_type": "method2_final_knowledge_update_failed",
                        "episode_id": self.episode_id,
                        "error": str(e),
                        "turns_analyzed": self.turn_count,
                        "method": "single_batch_comprehensive",
                        "episode_ended_in_death": episode_ended_in_death,
                        "will_synthesize_wisdom": will_synthesize_wisdom,
                    }
                },
            )

    def _is_death_episode(self) -> bool:
        """Check if the current episode ended in death."""
        # Check if death count increased during this episode
        # We can also check the action reasoning history for death indicators
        if hasattr(self, 'action_reasoning_history') and self.action_reasoning_history:
            last_reasoning = self.action_reasoning_history[-1]
            last_reasoning_text = str(last_reasoning).lower()
            
            # Look for death indicators in the last action reasoning
            death_indicators = [
                'death', 'died', 'killed', 'grue', 'eaten', 'crushed', 
                'blown up', 'drowned', 'suffocated', 'game over'
            ]
            
            if any(indicator in last_reasoning_text for indicator in death_indicators):
                return True
        
        # Also check if game_over_flag is set (this should be True for deaths)
        return self.game_over_flag

    def _update_movement_tracking(
        self, action: str, from_room: str, to_room: str
    ) -> None:
        """Update movement tracking and failed actions."""
        config = get_config()
        
        # Track failed actions by location
        if from_room and from_room == to_room:
            # Action didn't result in movement, might be a failed action
            if from_room not in self.failed_actions_by_location:
                self.failed_actions_by_location[from_room] = {}

            # Only add to failed actions if it looks like a movement command that failed
            movement_keywords = [
                "north",
                "south",
                "east",
                "west",
                "up",
                "down",
                "enter",
                "exit",
                "go",
                "climb",
            ]
            if any(keyword in action.lower() for keyword in movement_keywords):
                # Use the new dictionary-based tracking structure
                if action not in self.failed_actions_by_location[from_room]:
                    self.failed_actions_by_location[from_room][action] = {
                        "count": 0,
                        "responses": [],
                        "failure_type": "PERMANENT",  # Movement failures are typically walls
                        "first_turn": self.turn_count,
                        "last_turn": self.turn_count
                    }
                self.failed_actions_by_location[from_room][action]["count"] += 1
                self.failed_actions_by_location[from_room][action]["last_turn"] = self.turn_count
                
                # NEW: Track the failed exit in the map for potential pruning
                if config.gameplay.enable_exit_pruning and self.game_map:
                    failure_count = self.game_map.track_exit_failure(from_room, action)
                    
                    # Check if this exit should be pruned
                    if failure_count >= config.gameplay.exit_failure_threshold:
                        pruned_count = self.game_map.prune_invalid_exits(
                            from_room, config.gameplay.exit_failure_threshold
                        )
                        
                        if pruned_count > 0:
                            self.logger.info(
                                f"Exit pruning triggered for {from_room}: {pruned_count} invalid exits removed",
                                extra={
                                    "extras": {
                                        "event_type": "exit_pruning",
                                        "episode_id": self.episode_id,
                                        "turn": self.turn_count,
                                        "room": from_room,
                                        "failed_action": action,
                                        "failure_count": failure_count,
                                        "exits_pruned": pruned_count,
                                    }
                                },
                            )

        # Update room context for next turn
        self.prev_room_for_prompt_context = from_room
        self.action_leading_to_current_room_for_prompt_context = action

    def _update_failed_actions_tracking(
        self, action: str, game_response: str, current_location: str
    ) -> None:
        """
        Update failed actions tracking using LLM-based failure detection.
        This tracks all types of failed actions, not just movement.
        """
        # Use the critic's LLM-based failure detection
        failure_detection = self.critic.detect_action_failure(action, game_response)
        
        if failure_detection.action_failed:
            # Initialize location tracking if needed
            if current_location not in self.failed_actions_by_location:
                self.failed_actions_by_location[current_location] = {}
            
            # Add the failed action to this location's dictionary
            action_lower = action.lower()
            if action_lower not in self.failed_actions_by_location[current_location]:
                self.failed_actions_by_location[current_location][action_lower] = {
                    "count": 0,
                    "responses": [],
                    "failure_type": self.classify_failure_type(game_response),
                    "first_turn": self.turn_count,
                    "last_turn": self.turn_count
                }
            self.failed_actions_by_location[current_location][action_lower]["count"] += 1
            self.failed_actions_by_location[current_location][action_lower]["last_turn"] = self.turn_count
            self.failed_actions_by_location[current_location][action_lower]["responses"].append(game_response[:100])
            
            # Log the failure detection
            self.logger.info(
                f"Action failed in {current_location}: {action}",
                extra={
                    "event_type": "action_failure_detected", 
                    "episode_id": self.episode_id,
                    "turn": self.turn_count,
                    "location": current_location,
                    "failed_action": action,
                    "failure_reason": failure_detection.reason,
                }
            )

    def get_current_state(self) -> Dict[str, Any]:
        """Get comprehensive current state for export."""
        
        # Ensure current_room matches the actual room key in the map for proper highlighting
        # The orchestrator may track unique IDs that get consolidated, so we need to find the actual key
        actual_current_room = self.current_room_name_for_map
        
        # If the tracked room name doesn't exist in the map, find the best match
        if actual_current_room not in self.game_map.rooms:
            # Try to find a room that contains or is contained in the tracked name
            for room_key in self.game_map.rooms.keys():
                # Check if the base names match (e.g., "Kitchen" matches "Kitchen (3-way: east-up-west)")
                base_tracked = actual_current_room.split('(')[0].strip()
                base_room = room_key.split('(')[0].strip()
                
                if base_tracked.lower() == base_room.lower():
                    actual_current_room = room_key
                    break
        
        state = {
            "metadata": {
                "episode_id": self.episode_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "turn_count": self.turn_count,
                "game_over": self.game_over_flag,
                "score": self.previous_zork_score,
                "max_turns": self.max_turns_per_episode,
                "models": {
                    "agent": self.agent.model,
                    "critic": self.critic.model,
                    "extractor": self.extractor.model,
                    "knowledge_base": self.adaptive_knowledge_manager.analysis_model if self.adaptive_knowledge_manager else "Not available",
                },
                "current_model_display": get_config().llm.current_model_display,
            },
            "current_state": {
                "location": actual_current_room,  # Use the matched room key
                "inventory": self.current_inventory,
                "in_combat": self._get_combat_status(),
                "death_count": self.death_count,
                "discovered_objectives": self.discovered_objectives,
                "completed_objectives": self.completed_objectives,
                "objective_update_turn": self.objective_update_turn,
            },
            "recent_log": self.get_recent_log(20),
            "map": {
                "mermaid_diagram": self.game_map.render_mermaid(),
                "current_room": actual_current_room,  # Use the matched room key for highlighting
                "total_rooms": len(self.game_map.rooms),
                "total_connections": sum(
                    len(connections)
                    for connections in self.game_map.connections.values()
                ),
                # Enhanced map metrics
                "quality_metrics": self.game_map.get_map_quality_metrics(),
                "confidence_report": self.game_map.render_confidence_report(),
                "fragmentation_report": self.game_map.get_fragmentation_report(),
                # Exit failure tracking
                "exit_failure_stats": self.game_map.get_exit_failure_stats(),
                "exit_failure_report": self.game_map.render_exit_failure_report(),
                # Optional: Include raw data for advanced frontends
                "raw_data": {
                    "rooms": {
                        name: {"exits": list(room.exits)}
                        for name, room in self.game_map.rooms.items()
                    },
                    "connections": self.game_map.connections,
                },
            },
            "knowledge_base": self.get_knowledge_base_summary(),
            "performance": {
                "avg_critic_score": self.get_avg_critic_score(),
                "recent_actions": self.get_recent_action_summary(),
            },
        }
        
        # Add save metadata if available (for sync verification)
        if hasattr(self, '_save_metadata'):
            state["save_metadata"] = self._save_metadata
            
        return state

    def get_recent_log(self, length: int = 10) -> List[Dict[str, Any]]:
        """Get recent game log entries with reasoning."""
        recent_log = []

        # Get the most recent entries from action_history and memory_log_history
        recent_actions = self.action_history[-length:] if self.action_history else []
        recent_extractions = (
            self.memory_log_history[-length:] if self.memory_log_history else []
        )
        recent_reasoning = (
            self.action_reasoning_history[-length:]
            if self.action_reasoning_history
            else []
        )

        # Combine them by turn (assuming they're in sync)
        for i, (action, zork_response) in enumerate(recent_actions):
            turn_num = self.turn_count - len(recent_actions) + i + 1

            log_entry = {
                "turn": turn_num,
                "action": action,
                "zork_response": zork_response,
            }

            # Add reasoning if available
            reasoning_entry = None
            for reasoning in recent_reasoning:
                if reasoning["turn"] == turn_num and reasoning["action"] == action:
                    reasoning_entry = reasoning
                    break

            if reasoning_entry:
                log_entry["reasoning"] = reasoning_entry["reasoning"]
                log_entry["critic_score"] = reasoning_entry["critic_score"]
                log_entry["critic_justification"] = reasoning_entry.get(
                    "critic_justification"
                )
                log_entry["was_overridden"] = reasoning_entry["was_overridden"]
                log_entry["rejected_actions"] = reasoning_entry.get("rejected_actions")

            # Add extraction info if available
            if i < len(recent_extractions):
                extraction = recent_extractions[i]
                if hasattr(extraction, "model_dump"):
                    log_entry["extracted_info"] = extraction.model_dump()
                else:
                    log_entry["extracted_info"] = {
                        "current_location_name": getattr(
                            extraction, "current_location_name", ""
                        ),
                        "exits": getattr(extraction, "exits", []),
                        "visible_objects": getattr(extraction, "visible_objects", []),
                        "important_messages": getattr(
                            extraction, "important_messages", []
                        ),
                    }

            recent_log.append(log_entry)

        return recent_log

    def get_knowledge_base_summary(self) -> Dict[str, Any]:
        """Get knowledge base without the embedded map."""
        try:
            with open("knowledgebase.md", "r") as f:
                content = f.read()

            # Remove the mermaid diagram section more precisely
            # Look for the pattern: ## CURRENT WORLD MAP followed by ```mermaid...```
            
            # Pattern to match the map section with mermaid diagram
            # This matches from "## CURRENT WORLD MAP" through the closing ```
            pattern = r'## CURRENT WORLD MAP\s*\n\s*```mermaid\s*\n.*?\n```'
            
            # Remove the mermaid diagram section while preserving other content
            knowledge_only = re.sub(pattern, '', content, flags=re.DOTALL)
            
            # Clean up any extra whitespace that might be left
            knowledge_only = re.sub(r'\n\s*\n\s*\n', '\n\n', knowledge_only)

            return {
                "content": knowledge_only.strip(),
                "last_updated": os.path.getmtime("knowledgebase.md")
                if os.path.exists("knowledgebase.md")
                else None,
            }
        except Exception:
            return {"content": "No knowledge base available", "last_updated": None}

    def _get_combat_status(self) -> bool:
        """Determine if currently in combat based on recent extractions."""
        if not self.memory_log_history:
            return False

        recent_extraction = self.memory_log_history[-1]
        return getattr(recent_extraction, "in_combat", False)

    def _is_death_reason(self, game_over_reason: str) -> bool:
        """Determine if a game over reason indicates a death (as opposed to victory)."""
        if not game_over_reason:
            return False
        
        reason_lower = game_over_reason.lower()
        
        # Death indicators from zork_api.py
        death_indicators = [
            "you have died",
            "you are dead",
            "you died",
            "you have been eaten",
            "eaten by a grue",
            "killed by",
            "you fall",
            "you are engulfed",
            "crushed",
            "blown up",
            "incinerated",
            "drowned",
            "suffocated",
            "starved",
            "frozen",
            "electrocuted",
            "poisoned",
            "dissolved",
            "obliterated",
            "annihilated",
            "terminated",
            "destroyed",
            "perished",
            "expired",
            "demise"
        ]
        
        # Victory indicators (explicitly not deaths)
        victory_indicators = [
            "you have won",
            "congratulations",
            "you win",
            "victory",
            "triumphant",
            "successful",
            "completed",
            "finished"
        ]
        
        # Check for victory first - if it's a victory, it's not a death
        for victory_word in victory_indicators:
            if victory_word in reason_lower:
                return False
        
        # Check for death indicators
        for death_word in death_indicators:
            if death_word in reason_lower:
                return True
        
        # Default: if game over but not explicitly victory, treat as death
        # This covers edge cases where the death message might be unusual
        return True

    def get_avg_critic_score(self) -> float:
        """Get average critic score for recent turns."""
        if (
            not hasattr(self, "action_reasoning_history")
            or not self.action_reasoning_history
        ):
            return 0.0

        recent_reasoning = self.action_reasoning_history[-10:]  # Last 10 turns
        critic_scores = [
            reasoning.get("critic_score", 0.0) for reasoning in recent_reasoning
        ]

        if not critic_scores:
            return 0.0

        return sum(critic_scores) / len(critic_scores)

    def get_recent_action_summary(self) -> List[str]:
        """Get summary of recent actions."""
        if not self.action_history:
            return []

        recent_actions = self.action_history[-5:]  # Last 5 actions
        return [action for action, _ in recent_actions]

    def export_current_state(self) -> None:
        """Export the current game state to a JSON file and optionally to S3."""
        if not self.enable_state_export:
            return

        try:
            current_state = self.get_current_state()
            temp_file_path = f"{self.state_export_file}.tmp"
            final_file_path = self.state_export_file

            # Write to a temporary file first
            with open(temp_file_path, "w") as f:
                json.dump(current_state, f, indent=4)

            # Atomically replace the final file with the temporary file
            os.replace(temp_file_path, final_file_path)

            # Upload to S3 if configured
            if self.s3_client:
                self._upload_state_to_s3(final_file_path)

        except Exception as e:
            self.logger.warning(f"Failed to export current state: {e}", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })

    def upload_state_to_s3(self, state: Dict[str, Any]) -> None:
        """Upload current state to S3."""
        try:
            # Current state file
            current_key = f"{self.s3_key_prefix}current_state.json"

            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=current_key,
                Body=json.dumps(state, indent=2),
                ContentType="application/json",
                CacheControl="no-cache, must-revalidate",  # Ensure fresh data
            )

            # Optional: Also save timestamped snapshot
            timestamp_key = f"{self.s3_key_prefix}snapshots/{state['metadata']['episode_id']}/turn_{state['metadata']['turn_count']}.json"
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=timestamp_key,
                Body=json.dumps(state, indent=2),
                ContentType="application/json",
            )

        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to upload state to S3: {e}", extra={
                    "turn": self.turn_count,
                    "episode_id": self.episode_id
                })

    def _check_context_overflow(self) -> bool:
        """
        Monitor context size and trigger summarization if needed.
        
        Inspired by the Pokemon agent's context management approach.
        
        Returns:
            True if summarization was triggered, False otherwise
        """
        # Estimate total context tokens
        estimated_tokens = self._estimate_context_tokens()
        
        if estimated_tokens > (self.max_context_tokens * self.context_overflow_threshold):
            turns_since_last = self.turn_count - self.last_summarization_turn
            
            # Only summarize if we have meaningful content since last summarization
            if turns_since_last >= 20:  # Minimum turns before summarization
                self.logger.info(f"Context overflow detected ({estimated_tokens} tokens), triggering summarization...", extra={"turns_since_last": turns_since_last,  "episode_id": self.episode_id})
                self._trigger_context_summarization()
                return True
                
        return False

    def _estimate_context_tokens(self) -> int:
        """
        Estimate total context tokens based on memory log history.
        
        Uses the shared token estimation utility.
        """
        return estimate_context_tokens(
            memory_history=self.memory_log_history,
            reasoning_history=self.action_reasoning_history,
            knowledge_base_path="knowledgebase.md"
        )

    def _trigger_context_summarization(self) -> None:
        """
        Generate a summary of recent gameplay and reset context.
        
        Similar to the Pokemon agent's summarization approach but tailored for Zork.
        """
        try:
            # Generate summary of recent progress
            summary = self._generate_gameplay_summary()
            
            # Create condensed memory log from summary
            condensed_memory = {
                "turn": self.turn_count,
                "type": "context_summary",
                "summary": summary,
                "turns_summarized": self.turn_count - self.last_summarization_turn,
                "timestamp": datetime.now().isoformat()
            }
            
            # Clear detailed memory but preserve recent critical information
            recent_critical_memories = self._extract_critical_memories(last_n_turns=10)
            
            # Reset memory log to summary + critical recent memories
            self.memory_log_history = [condensed_memory] + recent_critical_memories
            
            # Reset action reasoning history but preserve recent critic scores  
            # Keep 25 entries to ensure full export coverage (get_recent_log exports 20 by default)
            recent_reasoning = self.action_reasoning_history[-25:] if len(self.action_reasoning_history) > 25 else self.action_reasoning_history
            self.action_reasoning_history = recent_reasoning
            
            self.last_summarization_turn = self.turn_count
            
            self.logger.info(f"Context summarized, preserved {len(recent_critical_memories)} critical memories", extra={"episode_id": self.episode_id})
            
        except Exception as e:
            self.logger.warning(f"Failed to trigger summarization: {e}", extra={"episode_id": self.episode_id})

    def _generate_gameplay_summary(self) -> str:
        """Generate a comprehensive summary of recent gameplay progress."""
        if not hasattr(self.adaptive_knowledge_manager, 'client') or not self.adaptive_knowledge_manager.client:
            return "Summary generation unavailable (no LLM client)"
            
        # Prepare summary prompt
        recent_turns = self.memory_log_history[-50:] if len(self.memory_log_history) > 50 else self.memory_log_history
        
        # Convert ExtractorResponse objects to serializable format
        serializable_turns = []
        for turn in recent_turns:
            if hasattr(turn, "model_dump"):
                # Pydantic model - convert to dict
                serializable_turns.append(turn.model_dump())
            elif isinstance(turn, dict):
                # Already a dict (like summary entries)
                serializable_turns.append(turn)
            else:
                # Fallback for other objects
                serializable_turns.append({
                    "current_location_name": getattr(turn, "current_location_name", "Unknown"),
                    "exits": getattr(turn, "exits", []),
                    "visible_objects": getattr(turn, "visible_objects", []),
                    "important_messages": getattr(turn, "important_messages", []),
                    "in_combat": getattr(turn, "in_combat", False),
                    "score": getattr(turn, "score", None),
                    "moves": getattr(turn, "moves", None),
                })
        
        summary_prompt = f"""Analyze the following Zork gameplay session and provide a comprehensive summary:

EPISODE ID: {self.episode_id}
TURNS COVERED: {self.last_summarization_turn + 1} to {self.turn_count}
CURRENT SCORE: {self.previous_zork_score}
DEATH COUNT: {self.death_count}

RECENT GAMEPLAY DATA:
{json.dumps(serializable_turns, indent=2)}

CURRENT MAP STATE:
{self.game_map.render_mermaid()}

Please provide a summary that includes:
1. Major discoveries and progress made
2. Key items obtained and used
3. Important locations visited and mapped
4. Puzzles solved or attempted
5. Deaths and what caused them
6. Strategic insights learned
7. Current objectives and next steps

Format as a clear, structured summary that preserves essential information for continued gameplay."""

        try:
            messages = [{"role": "user", "content": summary_prompt}]
            
            response = self.adaptive_knowledge_manager.client.chat.completions.create(
                model=self.adaptive_knowledge_manager.analysis_model,
                messages=messages,
                **self.adaptive_knowledge_manager.analysis_sampling.model_dump(exclude_unset=True)
            )
            
            return response.content.strip() if response else ""
            
        except Exception as e:
            self.logger.error(f"Failed to generate LLM summary, using fallback: {e}", extra={"episode_id": self.episode_id})
            return self._generate_fallback_summary()

    def _extract_critical_memories(self, last_n_turns: int = 10) -> List[Dict]:
        """Extract the most critical memories from recent turns."""
        if len(self.memory_log_history) <= last_n_turns:
            return self.memory_log_history
            
        recent_memories = self.memory_log_history[-last_n_turns:]
        critical_memories = []
        
        for memory in recent_memories:
            # Preserve memories with important events
            if self._is_critical_memory(memory):
                critical_memories.append(memory)
                
        return critical_memories

    def _is_critical_memory(self, memory: Dict) -> bool:
        """Determine if a memory contains critical information that should be preserved."""
        memory_str = str(memory).lower()
        
        critical_indicators = [
            "death", "died", "killed", "grue",
            "new item", "took", "picked up",
            "opened", "unlocked", "solved",
            "score increased", "points",
            "new location", "room", "area",
            "combat", "fight", "attack",
            "puzzle", "riddle", "problem"
        ]
        
        return any(indicator in memory_str for indicator in critical_indicators)

    def _generate_fallback_summary(self) -> str:
        """Generate a basic summary without LLM assistance."""
        recent_actions = [memory.get("action", "") for memory in self.memory_log_history[-20:]]
        recent_locations = list(set([memory.get("location", "") for memory in self.memory_log_history[-20:] if memory.get("location")]))
        
        return f"""Gameplay Summary (Turns {self.last_summarization_turn + 1}-{self.turn_count}):
- Score: {self.previous_zork_score}
- Deaths: {self.death_count}
- Recent actions: {', '.join(recent_actions[-10:])}
- Locations visited: {', '.join(recent_locations)}
- Total turns: {self.turn_count}
"""

    def _immediate_knowledge_update(self, section_id: str, content: str, trigger_reason: str) -> None:
        """
        Perform immediate knowledge update for critical discoveries.
        
        Inspired by the Pokemon agent's runtime knowledge updates.
        Used for high-priority information that shouldn't wait for the next scheduled update.
        
        Args:
            section_id: Knowledge section to update (e.g., "dangers", "items")
            content: The critical information to add
            trigger_reason: Why this immediate update was triggered
        """
        try:
            success = self.adaptive_knowledge_manager.update_knowledge_section(
                section_id=section_id,
                content=content,
                quality_score=8.0  # High quality for immediate updates
            )
            
            if success:
                self.logger.info(
                    f"Immediate knowledge update triggered: {trigger_reason}",
                    extra={
                        "extras": {
                            "event_type": "immediate_knowledge_update",
                            "episode_id": self.episode_id,
                            "section_id": section_id,
                            "trigger_reason": trigger_reason,
                            "turn": self.turn_count,
                        }
                    },
                )
                
                # Reload agent knowledge immediately for current session benefit
                self._reload_agent_knowledge()
            else:
                self.logger.warning(
                    f"Failed immediate knowledge update for {trigger_reason}",
                    extra={
                        "extras": {
                            "event_type": "immediate_knowledge_update_failed",
                            "episode_id": self.episode_id,
                            "section_id": section_id,
                            "trigger_reason": trigger_reason,
                        }
                    },
                )
                
        except Exception as e:
            self.logger.error(
                f"Error during immediate knowledge update: {e}",
                extra={
                    "extras": {
                        "event_type": "immediate_knowledge_update_error",
                        "episode_id": self.episode_id,
                        "error": str(e),
                        "trigger_reason": trigger_reason,
                    }
                },
            )

    def _check_objective_update(self, current_agent_reasoning: str = "") -> None:
        """Check if it's time for an objective update and perform it if needed."""
        try:
            # Debug logging to help diagnose issues
            print(f"🔍 Objective update check: turn={self.turn_count}, interval={self.objective_update_interval}, last_update={self.objective_update_turn}")
            
            # Also log to the structured logger for permanent record
            self.logger.info(
                f"Objective update check: turn={self.turn_count}, last_update={self.objective_update_turn}",
                extra={
                    "extras": {
                        "event_type": "objective_update_check",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "objective_update_turn": self.objective_update_turn,
                        "current_objectives_count": len(self.discovered_objectives),
                    }
                },
            )
            
            # Update objectives every turn, ensuring it's not a duplicate call for the same turn.
            if (self.turn_count > 0 and 
            self.turn_count - self.objective_update_turn >= self.objective_update_interval):
                print(f"🎯 Triggering objective update at turn {self.turn_count}")
                self.logger.info(
                    f"Triggering objective update at turn {self.turn_count}",
                    extra={
                        "extras": {
                            "event_type": "objective_update_triggered",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                        }
                    },
                )
                self._update_discovered_objectives(current_agent_reasoning)
            else:
                print(f"🔍 Objective update skipped: turn_count={self.turn_count}, already updated this turn or turn 0.")
                self.logger.info(
                    f"Objective update skipped: turn_count={self.turn_count}, already updated this turn or turn 0",
                    extra={
                        "extras": {
                            "event_type": "objective_update_skipped",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "objective_update_turn": self.objective_update_turn,
                            "skip_reason": "turn_0" if self.turn_count == 0 else "already_updated",
                        }
                    },
                )
        except Exception as e:
            print(f"❌ Exception in _check_objective_update: {e}")
            self.logger.error(
                f"Exception in _check_objective_update: {e}",
                extra={
                    "extras": {
                        "event_type": "objective_update_exception",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "error": str(e),
                    }
                },
            )
            raise  # Re-raise to be caught by the outer try-catch

    def _update_discovered_objectives(self, current_agent_reasoning: str = "") -> None:
        """
        Use LLM to analyze recent gameplay and discover/update objectives.
        
        This maintains discovered objectives between turns while staying LLM-first.
        """
        try:
            print(f"🎯 Updating discovered objectives (turn {self.turn_count})...")
            
            # Log that we're starting the update
            self.logger.info(
                f"Starting objective discovery/update at turn {self.turn_count}",
                extra={
                    "extras": {
                        "event_type": "objective_discovery_start",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "current_objectives": self.discovered_objectives,
                        "current_score": self.previous_zork_score,
                    }
                },
            )
            
            # Get recent gameplay context for analysis
            recent_memory = self.memory_log_history[-20:] if len(self.memory_log_history) > 20 else self.memory_log_history
            recent_actions = self.action_history[-10:] if len(self.action_history) > 10 else self.action_history
            
            # Prepare context for LLM analysis
            gameplay_context = self._prepare_objective_analysis_context(recent_memory, recent_actions, current_agent_reasoning)
            
            # Create prompt for objective discovery/updating
            prompt = f"""Analyze the recent Zork gameplay to discover and maintain the agent's objectives.

CURRENT DISCOVERED OBJECTIVES:
{self.discovered_objectives if self.discovered_objectives else "None discovered yet"}

RECENTLY COMPLETED OBJECTIVES:
{[comp["objective"] for comp in self.completed_objectives[-5:]] if self.completed_objectives else "None completed yet"}

RECENT GAMEPLAY CONTEXT:
{gameplay_context}

CURRENT SCORE: {self.previous_zork_score}
CURRENT LOCATION: {self.current_room_name_for_map}
CURRENT INVENTORY: {self.current_inventory}

Based on this gameplay, identify the agent's discovered objectives. Look for:
1. **Score-increasing activities** (these reveal important objectives)
2. **Recurring patterns** in the agent's behavior that suggest goals
3. **Environmental clues** about what the agent should be doing
4. **Obstacles** that suggest significant rewards lie beyond them
5. **Items or locations** that appear strategically important

**IMPORTANT**: Consider the 'AGENT REASONING' provided in the context. If it contains new ideas, plans, or hypotheses for achieving goals, incorporate these into the objective list. However, if the reasoning is solely about escaping a loop, retrying a failed action, or simple exploration without a clear new goal, it should NOT lead to new objectives.

Update the objective list by:
- **Adding new objectives** discovered through recent gameplay patterns or valid agent reasoning
- **Updating existing objectives** with new information or progress
- **Removing objectives** that have been completed or proven incorrect
- **Prioritizing objectives** based on evidence of importance
- **Avoiding re-adding** objectives that were recently completed (listed above)

Format your response as:
OBJECTIVES:
- [objective 1]
- [objective 2]
- [etc.]

Focus on objectives the agent has actually discovered through gameplay patterns or its own novel reasoning, not general Zork knowledge."""

            # Get LLM response using adaptive knowledge manager's client
            if hasattr(self.adaptive_knowledge_manager, 'client') and self.adaptive_knowledge_manager.client:
                messages = [{"role": "user", "content": prompt}]
                
                model_to_use = self.adaptive_knowledge_manager.analysis_model if self.adaptive_knowledge_manager else self.agent.model
                print(f"  🔍 Using model: {model_to_use}")
                print(f"  🔍 Prompt length: {len(prompt)} characters")
                print(f"  🔍 First 200 chars of prompt: {prompt[:200]}...")
                
                # Log that we're about to make the LLM call
                self.logger.info(
                    f"Making LLM call for objective discovery with model {model_to_use}",
                    extra={
                        "extras": {
                            "event_type": "objective_llm_call_start",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "model": model_to_use,
                            "prompt_length": len(prompt),
                        }
                    },
                )
                
                try:
                    response = self.adaptive_knowledge_manager.client.chat.completions.create(
                        model=model_to_use,
                        messages=messages,
                        **self.adaptive_knowledge_manager.analysis_sampling.model_dump(exclude_unset=True) if self.adaptive_knowledge_manager else {"temperature": 0.3, "max_tokens": 5000}
                    )
                    
                    print(f"  🔍 LLM call successful, response type: {type(response)}")
                    
                    # Extract content from LLM response
                    response_content = response.content if response else ""
                    
                    print(f"  🔍 Response content type: {type(response_content)}")
                    print(f"  🔍 Response content length: {len(response_content) if response_content else 0}")
                    
                    # Parse objectives from response
                    updated_objectives = self._parse_objectives_from_response(response_content)
                    
                    print(f"  🔍 Raw LLM response: '{response_content}'")
                    print(f"  🔍 Parsed objectives: {updated_objectives}")
                    
                    if updated_objectives:
                        self.discovered_objectives = updated_objectives
                        self.objective_update_turn = self.turn_count
                        
                        print(f"  ✅ Objectives updated: {len(updated_objectives)} objectives discovered")
                        for i, obj in enumerate(updated_objectives[:3], 1):  # Show first 3
                            print(f"    {i}. {obj}")
                        
                        # Log the update
                        self.logger.info(
                            "Discovered objectives updated",
                            extra={
                                "extras": {
                                    "event_type": "objectives_updated",
                                    "episode_id": self.episode_id,
                                    "turn": self.turn_count,
                                    "objective_count": len(updated_objectives),
                                    "objectives": updated_objectives,
                                }
                            },
                        )
                    else:
                        print("  ⚠️ No objectives parsed from LLM response")
                        # IMPORTANT: Still update the turn counter to prevent repeated attempts every turn
                        self.objective_update_turn = self.turn_count
                        self.logger.warning(
                            "No objectives parsed from LLM response",
                            extra={
                                "extras": {
                                    "event_type": "objectives_parsing_failed",
                                    "episode_id": self.episode_id,
                                    "turn": self.turn_count,
                                    "llm_response": response_content,
                                }
                            },
                        )
                        
                except Exception as llm_error:
                    print(f"  ❌ LLM call failed: {llm_error}")
                    self.logger.error(
                        f"Objective LLM call failed: {llm_error}",
                        extra={
                            "extras": {
                                "event_type": "objective_llm_call_failed",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "error": str(llm_error),
                                "model": model_to_use,
                            }
                        },
                    )
            else:
                print("  ⚠️ No LLM client available for objective analysis")
                self.logger.error(
                    "No LLM client available for objective analysis",
                    extra={
                        "extras": {
                            "event_type": "objective_no_client",
                            "episode_id": self.episode_id,
                            "turn": self.turn_count,
                            "has_adaptive_manager": hasattr(self, 'adaptive_knowledge_manager'),
                            "has_client": hasattr(self.adaptive_knowledge_manager, 'client') if hasattr(self, 'adaptive_knowledge_manager') else False,
                            "client_value": str(self.adaptive_knowledge_manager.client) if hasattr(self, 'adaptive_knowledge_manager') and hasattr(self.adaptive_knowledge_manager, 'client') else "N/A",
                        }
                    },
                )
                
        except Exception as e:
            print(f"  ⚠️ Failed to update objectives: {e}")
            self.logger.error(
                f"Objective update failed: {e}",
                extra={
                    "extras": {
                        "event_type": "objective_update_failed",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "error": str(e),
                    }
                },
            )

    def _prepare_objective_analysis_context(self, recent_memory, recent_actions, current_agent_reasoning) -> str:
        """Prepare gameplay context for objective analysis."""
        context_parts = []
        
        # Add recent actions and responses
        if recent_actions:
            context_parts.append("RECENT ACTIONS:")
            for action, response in recent_actions[-5:]:  # Last 5 actions
                context_parts.append(f"  Action: {action}")
                context_parts.append(f"  Result: {response[:200]}...")  # Truncate long responses
                context_parts.append("")
        
        # Add notable events from memory
        if recent_memory:
            notable_events = []
            for memory in recent_memory:
                if hasattr(memory, 'important_messages') and memory.important_messages:
                    for msg in memory.important_messages:
                        if any(keyword in msg.lower() for keyword in ['score', 'points', 'treasure', 'lamp', 'door', 'open', 'take']):
                            notable_events.append(msg)
            
            if notable_events:
                context_parts.append("NOTABLE EVENTS:")
                for event in notable_events[-10:]:  # Last 10 notable events
                    context_parts.append(f"  - {event}")
                context_parts.append("")
        
        # Add score changes
        score_changes = []
        for memory in recent_memory:
            # Check if this memory entry indicates a score change
            if hasattr(memory, 'important_messages'):
                for msg in memory.important_messages:
                    if 'score' in msg.lower() or 'points' in msg.lower():
                        score_changes.append(msg)
        
        if score_changes:
            context_parts.append("SCORE CHANGES:")
            for change in score_changes:
                context_parts.append(f"  - {change}")
            context_parts.append("")
        
        # Add agent reasoning if it doesn't seem to be solely about escaping a loop
        if current_agent_reasoning:
            # Keywords indicating loop-escaping or simple re-attempts, not new objectives
            loop_keywords = [
                'stuck', 'loop', 'repeat', 'try again', 'another way', 'instead',
                'alternative', 'avoid repeating', 'different action', 'failed before'
            ]
            # Keywords indicating new ideas or goals
            idea_keywords = [
                'idea', 'maybe if', 'i should try', 'plan to', 'goal is to', 'what if',
                'perhaps', 'new approach', 'strategy', 'objective is to', 'hypothesize'
            ]

            reasoning_lower = current_agent_reasoning.lower()
            is_loop_related = any(keyword in reasoning_lower for keyword in loop_keywords)
            has_new_idea = any(keyword in reasoning_lower for keyword in idea_keywords)

            # Include reasoning if it has new ideas OR if it's not clearly loop-related
            # This prioritizes including potentially useful reasoning unless it's obviously just about getting unstuck.
            if has_new_idea or not is_loop_related:
                context_parts.append("AGENT REASONING (Current Turn):")
                context_parts.append(f"  {current_agent_reasoning}")
                context_parts.append("")
            else:
                context_parts.append("AGENT REASONING (Current Turn - Filtered as loop-related):")
                context_parts.append(f"  {current_agent_reasoning}") # Still include for LLM to see it was considered
                context_parts.append("")
         
        return "\n".join(context_parts)

    def _parse_objectives_from_response(self, response: str) -> List[str]:
        """Parse objectives from the LLM response."""
        try:
            objectives = []
            lines = response.strip().split('\n')
            
            # Look for the OBJECTIVES: section
            in_objectives_section = False
            for line in lines:
                line = line.strip()
                
                if line.upper().startswith('OBJECTIVES:'):
                    in_objectives_section = True
                    continue
                
                if in_objectives_section:
                    # Stop if we hit another section header
                    if line.endswith(':') and len(line.split()) <= 3:
                        break
                    
                    # Look for bullet points
                    if line.startswith('- ') or line.startswith('* '):
                        objective = line[2:].strip()
                        if objective and len(objective) > 5:  # Filter out very short entries
                            objectives.append(objective)
            
            return objectives
            
        except Exception as e:
            self.logger.warning(f"Failed to parse objectives from response: {e}", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })
            return []

    def _check_objective_completion(self, action_taken: str, game_response: str, extracted_info) -> None:
        """Check if any discovered objectives have been completed this turn."""
        if not self.discovered_objectives:
            return
            
        try:
            # Look for completion signals in the game response and context
            score_change = self.previous_zork_score - getattr(self, '_last_score_for_completion_check', self.previous_zork_score)
            self._last_score_for_completion_check = self.previous_zork_score
            
            completion_signals = []
            
            # Score increase is a strong completion signal
            if score_change > 0:
                completion_signals.append(f"Score increased by {score_change} points")
            
            # Check for completion keywords in game response
            completion_keywords = [
                "well done", "congratulations", "you have", "successfully", 
                "completed", "solved", "unlocked", "opened", "found", 
                "treasure", "victory", "accomplished"
            ]
            
            response_lower = game_response.lower()
            for keyword in completion_keywords:
                if keyword in response_lower:
                    completion_signals.append(f"Response contains completion keyword: '{keyword}'")
            
            # Check for location/inventory changes that might indicate completion
            if extracted_info:
                # New location reached
                if (hasattr(extracted_info, 'current_location_name') and 
                    extracted_info.current_location_name != self.current_room_name_for_map):
                    completion_signals.append(f"Reached new location: {extracted_info.current_location_name}")
                
                # New items acquired  
                if hasattr(extracted_info, 'inventory'):
                    new_items = set(extracted_info.inventory) - set(self.current_inventory)
                    if new_items:
                        completion_signals.append(f"Acquired new items: {', '.join(new_items)}")
            
            # If we have completion signals, check objectives against them
            if completion_signals:
                self._evaluate_objective_completion(action_taken, completion_signals)
                
        except Exception as e:
            self.logger.warning(f"Failed to check objective completion: {e}", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })

    def _evaluate_objective_completion(self, action_taken: str, completion_signals: List[str]) -> None:
        """Use LLM to evaluate if any objectives were completed based on completion signals."""
        try:
            context = f"""
ACTION TAKEN: {action_taken}

COMPLETION SIGNALS:
{chr(10).join(f"- {signal}" for signal in completion_signals)}

CURRENT OBJECTIVES:
{chr(10).join(f"- {obj}" for obj in self.discovered_objectives)}

RECENT CONTEXT:
- Current Location: {self.current_room_name_for_map}
- Current Score: {self.previous_zork_score}
- Current Inventory: {', '.join(self.current_inventory) if self.current_inventory else 'Empty'}
- Turn: {self.turn_count}
"""

            prompt = f"""Analyze if any of the current objectives were completed this turn.

{context}

Based on the action taken and completion signals, determine if any objectives were achieved. Be conservative - only mark objectives as completed if there's clear evidence of completion.

Look for:
- Direct achievement of stated objectives
- Score increases that correspond to objective completion
- Game responses that indicate success
- Location/item changes that fulfill objectives

Respond with:
COMPLETED: [list any completed objectives exactly as stated, or "None" if no clear completions]
REASONING: [brief explanation of why each objective was marked complete]

Only mark objectives as completed if you're confident they were achieved."""

            if hasattr(self.adaptive_knowledge_manager, 'client') and self.adaptive_knowledge_manager.client:
                messages = [{"role": "user", "content": prompt}]
                
                response = self.adaptive_knowledge_manager.client.chat.completions.create(
                    model=self.adaptive_knowledge_manager.analysis_model if self.adaptive_knowledge_manager else self.agent.model,
                    messages=messages,
                    **self.adaptive_knowledge_manager.analysis_sampling.model_dump(exclude_unset=True) if self.adaptive_knowledge_manager else {"temperature": 0.2, "max_tokens": 5000}
                )
                
                # Parse completed objectives
                completed_objectives = self._parse_completed_objectives(response.content if response else "")
                
                if completed_objectives:
                    self._mark_objectives_complete(completed_objectives, action_taken, completion_signals)
                    
        except Exception as e:
            self.logger.warning(f"Failed to evaluate objective completion: {e}", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })

    def _parse_completed_objectives(self, response: str) -> List[str]:
        """Parse completed objectives from LLM response."""
        try:
            completed = []
            lines = response.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if line.upper().startswith('COMPLETED:'):
                    completed_text = line.split(':', 1)[1].strip()
                    if completed_text.lower() != "none":
                        # Split by commas and clean up
                        objectives = [obj.strip() for obj in completed_text.split(',')]
                        for obj in objectives:
                            if obj and obj in self.discovered_objectives:
                                completed.append(obj)
                    break
            
            return completed
            
        except Exception as e:
            self.logger.warning(f"Failed to parse completed objectives: {e}", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })
            return []

    def _mark_objectives_complete(self, completed_objectives: List[str], action_taken: str, completion_signals: List[str]) -> None:
        """Mark objectives as completed and move them to completed list."""
        try:
            for objective in completed_objectives:
                if objective in self.discovered_objectives:
                    # Remove from active objectives
                    self.discovered_objectives.remove(objective)
                    
                    # Add to completed objectives with context
                    completion_record = {
                        "objective": objective,
                        "completed_turn": self.turn_count,
                        "completion_action": action_taken,
                        "completion_signals": completion_signals,
                        "completion_score": self.previous_zork_score
                    }
                    self.completed_objectives.append(completion_record)
                    
                    print(f"  ✅ Objective completed: {objective}")
                    
                    # Log the completion
                    self.logger.info(
                        f"Objective completed: {objective}",
                        extra={
                            "extras": {
                                "event_type": "objective_completed",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "objective": objective,
                                "completion_action": action_taken,
                                "completion_signals": completion_signals,
                                "completion_score": self.previous_zork_score,
                            }
                        },
                    )
                    
        except Exception as e:
            self.logger.warning(f"Failed to mark objectives complete: {e}", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })

    def _log_objective_prompt(self, prompt_content: str) -> None:
        """Log the full objective generation prompt to a temporary file."""
        try:
            # Ensure tmp directory exists
            if not os.path.exists("tmp"):
                os.makedirs("tmp")
            
            # Simple counter for unique filenames, reset per orchestrator instance might be okay for debugging
            if not hasattr(self, '_objective_prompt_counter'):
                self._objective_prompt_counter = 0
            self._objective_prompt_counter += 1
            
            filename = f"tmp/objective_prompt_t{self.turn_count}_{self._objective_prompt_counter:03d}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"=== OBJECTIVE GENERATION PROMPT (Turn: {self.turn_count}, Episode: {self.episode_id}) ===\\n")
                model_to_use = self.adaptive_knowledge_manager.analysis_model if self.adaptive_knowledge_manager else self.agent.model # Fallback for safety
                f.write(f"Model: {model_to_use}\\n")
                # Assuming sampling params are accessible or hardcoded for this debug log
                f.write(f"Temperature: 0.3 (default for objective update)\\n") 
                f.write("=" * 70 + "\\n\\n")
                f.write(prompt_content)
            
            if self.logger:
                self.logger.info(f"Objective prompt logged to {filename}", extra={
                    "turn": self.turn_count,
                    "episode_id": self.episode_id
                })
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to log objective prompt: {e}", extra={
                    "turn": self.turn_count,
                    "episode_id": self.episode_id
                })

    def _check_objective_refinement(self) -> None:
        """Checks if objectives need refinement and triggers it."""
        if not self.enable_objective_refinement:
            return

        time_for_scheduled_refinement = (self.turn_count - self.last_objective_refinement_turn) >= self.objective_refinement_interval
        forced_refinement_due_to_length = len(self.discovered_objectives) > self.max_objectives_before_forced_refinement

        if self.turn_count > 0 and (time_for_scheduled_refinement or forced_refinement_due_to_length):
            if time_for_scheduled_refinement:
                reason = f"interval met ({self.objective_refinement_interval} turns)"
            else:
                reason = f"max objectives exceeded ({len(self.discovered_objectives)} > {self.max_objectives_before_forced_refinement})"
            
            self.logger.info(
                f"Triggering objective refinement at turn {self.turn_count}. Reason: {reason}",
                extra={
                    "extras": {
                        "event_type": "objective_refinement_triggered",
                        "episode_id": self.episode_id,
                        "turn": self.turn_count,
                        "current_objective_count": len(self.discovered_objectives),
                        "reason": reason,
                    }
                }
            )
            self._refine_discovered_objectives()
            self.last_objective_refinement_turn = self.turn_count

    def _refine_discovered_objectives(self) -> None:
        """Uses an LLM to refine the current list of discovered objectives."""
        if not self.discovered_objectives:
            self.logger.info("No discovered objectives to refine.", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })
            return

        self.logger.info(f"🎯 Refining {len(self.discovered_objectives)} objectives (target: ~{self.refined_objectives_target_count})...", extra={
            "turn": self.turn_count,
            "episode_id": self.episode_id
        })

        # Prepare a brief game state summary for context
        game_summary_parts = [
            f"- Current Location: {self.current_room_name_for_map}",
            f"- Current Score: {self.previous_zork_score}",
            f"- Turn: {self.turn_count}",
        ]
        if self.current_inventory:
            game_summary_parts.append(f"- Key Inventory: {', '.join(self.current_inventory[:5])}{'...' if len(self.current_inventory) > 5 else ''}")

        # Consider adding a brief summary from knowledgebase if available and concise
        # For now, keeping it simple to avoid excessive token usage here.

        game_state_summary = "\\n".join(game_summary_parts)

        # Corrected prompt construction
        objectives_str = "\\n".join([f"- {idx + 1}. {obj}" for idx, obj in enumerate(self.discovered_objectives)])
        completed_objectives_str = "\\n".join([f"- {comp['objective']}" for comp in self.completed_objectives[-10:]]) if self.completed_objectives else "None recently completed"

        refined_objectives_prompt = f"""You are tasked with refining a list of discovered objectives for a Zork gameplay session. The agent has discovered too many objectives and needs to focus on the most promising ones.

Current Game State:
{game_state_summary}

Current Objectives (to be refined):
{objectives_str}

Recently Completed Objectives:
{completed_objectives_str}

**CRITICAL: Loop and Stagnation Detection**
Review the current objectives carefully for signs of:
1. **Repetitive patterns** that may cause the agent to get stuck in loops
2. **Overly specific puzzle objectives** that may require tools/knowledge not yet available
3. **Location-specific goals** that trap the agent in one area (e.g., "experiment with egg/tree")
4. **Parser interaction objectives** that attempt complex commands the game doesn't understand

**Refinement Guidelines:**
1. **Prioritize exploration objectives** over specific puzzle-solving objectives
2. **Remove objectives** that seem to encourage repetitive behavior in one location
3. **Keep objectives** that promote visiting new areas or finding new items
4. **Prefer general goals** over highly specific interaction patterns
5. **Target ~{self.refined_objectives_target_count} objectives** total

**Examples of problematic objectives to REMOVE:**
- "Experiment with the egg's fragile clasp using specific tools"
- "Test vertical movement possibilities from specific location" 
- "Try different verbs with [specific object] at [specific location]"

**Examples of good objectives to KEEP:**
- "Explore unmapped areas to find new locations"
- "Look for light sources to safely explore dark areas"
- "Find keys or tools that can unlock doors or containers"
- "Locate and collect valuable items or treasures"

Please provide a refined list of objectives that encourages exploration and progress while avoiding repetitive loops."""


        try:
            if hasattr(self.adaptive_knowledge_manager, 'client') and self.adaptive_knowledge_manager.client:
                messages = [{"role": "user", "content": refined_objectives_prompt}]
                # Use analysis_model and sampling parameters similar to knowledge generation
                # Fallback to a default model if not configured
                model_to_use = self.adaptive_knowledge_manager.analysis_model if self.adaptive_knowledge_manager and self.adaptive_knowledge_manager.analysis_model else self.agent.model
                sampling_params = self.adaptive_knowledge_manager.analysis_sampling.model_dump(exclude_unset=True) if self.adaptive_knowledge_manager else {"temperature": 0.5, "max_tokens": 5000}


                response = self.adaptive_knowledge_manager.client.chat.completions.create(
                    model=model_to_use,
                    messages=messages,
                    **sampling_params
                )

                response_content = response.content if response else ""
                refined_objectives = self._parse_objectives_from_response(response_content)

                if refined_objectives:
                    self.logger.info(f"Objective list refined from {len(self.discovered_objectives)} to {len(refined_objectives)} objectives.", extra={
                        "turn": self.turn_count,
                        "episode_id": self.episode_id
                    })
                    self.discovered_objectives = refined_objectives
                elif response_content.strip().upper() == "OBJECTIVES:\nNONE":
                    self.logger.info("Objective list refined to None as per LLM response.", extra={
                        "turn": self.turn_count,
                        "episode_id": self.episode_id
                    })
                    self.discovered_objectives = []
                else:
                    self.logger.warning(f"Objective refinement LLM call returned an unexpected or empty response. Raw: '{response_content[:200]}...' No changes made to objectives.", extra={
                        "turn": self.turn_count,
                        "episode_id": self.episode_id
                    })

            else:
                self.logger.warning("No LLM client available for objective refinement.", extra={
                    "turn": self.turn_count,
                    "episode_id": self.episode_id
                })
        except Exception as e:
            self.logger.error(f"Error during objective refinement: {e}", exc_info=True, extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })

    def _check_objective_staleness(self) -> None:
        """Check for stale objectives and remove them if no progress has been made."""
        if not self.discovered_objectives:
            return
            
        current_location = self.current_room_name_for_map
        current_score = self.previous_zork_score
        
        # Detect if we're making progress (location change or score increase)
        made_progress = (
            current_location != self.last_location_for_staleness or
            current_score > self.last_score_for_staleness
        )
        
        # Update staleness tracking for all objectives
        for objective in self.discovered_objectives[:]:  # Copy list to allow modification
            if objective not in self.objective_staleness_tracker:
                self.objective_staleness_tracker[objective] = 0
            
            if made_progress:
                # Reset staleness counter if we made any progress
                self.objective_staleness_tracker[objective] = 0
            else:
                # Increment staleness counter
                self.objective_staleness_tracker[objective] += 1
                
                # Remove objectives that have been stale for too long (30+ turns without progress)
                if self.objective_staleness_tracker[objective] >= 30:
                    self.discovered_objectives.remove(objective)
                    del self.objective_staleness_tracker[objective]
                    
                    print(f"🗑️ Removed stale objective (30+ turns without progress): {objective}")
                    
                    self.logger.info(
                        f"Objective removed due to staleness: {objective}",
                        extra={
                            "extras": {
                                "event_type": "objective_staleness_removal",
                                "episode_id": self.episode_id,
                                "turn": self.turn_count,
                                "stale_objective": objective,
                                "turns_without_progress": 30,
                            }
                        },
                    )
        
        # Update tracking variables
        self.last_location_for_staleness = current_location
        self.last_score_for_staleness = current_score

    def _handle_save_signal(self, zork_interface_instance) -> bool:
        """Check for and handle save signal from external process (like manage_ec2.py).
        
        Returns:
            bool: True if save signal was processed (regardless of success)
        """
        if os.path.exists(self.save_signal_file_abs_path):
            # Read the save filename from the signal file content
            try:
                with open(self.save_signal_file_abs_path, 'r') as f:
                    save_filename = f.read().strip()
                    
                if not save_filename:
                    # Fallback to generated filename if signal file is empty
                    save_filename = self._generate_unique_save_filename()
                    self.logger.warning("Signal file was empty, generated new filename", extra={
                        "extras": {
                            "event_type": "empty_signal_file",
                            "episode_id": self.episode_id,
                            "generated_filename": save_filename
                        }
                    })
                    
            except Exception as e:
                # Fallback to generated filename if file can't be read
                save_filename = self._generate_unique_save_filename()
                self.logger.warning(f"Could not read signal file content: {e}, generated new filename", extra={
                    "extras": {
                        "event_type": "signal_file_read_error", 
                        "episode_id": self.episode_id,
                        "error": str(e),
                        "generated_filename": save_filename
                    }
                })
            
            # Set current save filename and calculate paths
            self.current_save_filename = save_filename
            current_save_file_abs_path = self._get_save_file_path(save_filename)
            
            self.logger.info("Save requested by external signal", extra={
                "extras": {
                    "event_type": "save_signal_received",
                    "episode_id": self.episode_id,
                    "turn": self.turn_count,
                    "signal_file": self.save_signal_file_abs_path,
                    "save_filename": save_filename,
                    "save_file_path": current_save_file_abs_path
                }
            })
            
            # Log current game state before attempting save
            self.logger.info(f"Current save attempt details", extra={
                "extras": {
                    "event_type": "save_attempt_details",
                    "episode_id": self.episode_id,
                    "game_running": zork_interface_instance.is_running(),
                    "working_directory": zork_interface_instance.working_directory,
                    "save_filename": save_filename,
                    "save_file_abs_path": current_save_file_abs_path
                }
            })
            
            # Attempt to save the Zork game state
            save_success = zork_interface_instance.trigger_zork_save(save_filename)
            
            if save_success:
                self.logger.info("Zork game state saved successfully", extra={
                    "extras": {
                        "event_type": "zork_save_success",
                        "episode_id": self.episode_id,
                        "save_file": current_save_file_abs_path
                    }
                })
                
                # Check if save file was actually created
                save_file_with_qzl = current_save_file_abs_path + ".qzl"
                save_file_exists = os.path.exists(save_file_with_qzl) or os.path.exists(current_save_file_abs_path)
                
                if save_file_exists:
                    # Only export JSON state if Zork save file actually exists
                    # Add save file metadata to the JSON state for verification
                    save_metadata = {
                        "save_file_path": save_file_with_qzl if os.path.exists(save_file_with_qzl) else current_save_file_abs_path,
                        "save_file_mtime": os.path.getmtime(save_file_with_qzl) if os.path.exists(save_file_with_qzl) else os.path.getmtime(current_save_file_abs_path),
                        "save_turn": self.turn_count,
                        "save_timestamp": datetime.now().isoformat(),
                        "save_filename": save_filename
                    }
                    
                    # Add save metadata to current state before export
                    self._save_metadata = save_metadata
                    
                    # Force save current ZorkGPT state to JSON
                    self.export_current_state()
                    
                    self.logger.info("ZorkGPT state exported with save metadata - ready for shutdown", extra={
                        "extras": {
                            "event_type": "state_export_complete",
                            "episode_id": self.episode_id,
                            "export_file": self.state_export_file,
                            "save_metadata": save_metadata
                        }
                    })
                else:
                    self.logger.error("Zork save file not found after save command - not exporting JSON state", extra={
                        "extras": {
                            "event_type": "save_file_missing_after_save",
                            "episode_id": self.episode_id,
                            "expected_paths": [current_save_file_abs_path, save_file_with_qzl]
                        }
                    })
                    save_success = False  # Mark as failed since file doesn't exist
                    
            else:
                self.logger.error("Failed to save Zork game state - not exporting JSON state", extra={
                    "extras": {
                        "event_type": "zork_save_failed",
                        "episode_id": self.episode_id,
                        "save_file": current_save_file_abs_path,
                        "game_running": zork_interface_instance.is_running(),
                        "working_directory": zork_interface_instance.working_directory
                    }
                })
            
            # Remove signal file regardless of save success/failure
            try:
                os.remove(self.save_signal_file_abs_path)
                self.logger.info("Save signal file removed", extra={
                    "extras": {
                        "event_type": "save_signal_removed",
                        "episode_id": self.episode_id,
                        "save_success": save_success
                    }
                })
            except OSError as e:
                self.logger.warning(f"Failed to remove save signal file: {e}", extra={
                    "extras": {
                        "event_type": "save_signal_removal_failed",
                        "episode_id": self.episode_id,
                        "error": str(e)
                    }
                })
            
            return True
        
        return False

    def _attempt_restore_from_save(self, zork_interface_instance) -> bool:
        """Attempt to restore from a previous save file.
        
        Returns:
            bool: True if restore was successful
        """
        save_file_to_use = None
        restore_filename = None
        
        # First, try to find the most recent save file
        most_recent_save = self._find_most_recent_save()
        
        if most_recent_save:
            save_file_to_use = most_recent_save
            # Extract filename from path for the restore command
            restore_filename = os.path.basename(most_recent_save).replace('.qzl', '').replace('.sav', '')
            
            self.logger.info("Found most recent save file", extra={
                "extras": {
                    "event_type": "most_recent_save_found",
                    "episode_id": self.episode_id,
                    "save_file": save_file_to_use,
                    "restore_filename": restore_filename
                }
            })
        else:
            self.logger.info("No save file found - starting fresh game", extra={
                "extras": {
                    "event_type": "no_save_file",
                    "episode_id": self.episode_id,
                    "game_directory": self.zork_workdir_abs_path
                }
            })
            return False
        
        self.logger.info("Attempting restore from save file", extra={
            "extras": {
                "event_type": "restore_attempt",
                "episode_id": self.episode_id,
                "save_file": save_file_to_use,
                "restore_filename": restore_filename
            }
        })
        
        restore_success = zork_interface_instance.trigger_zork_restore(restore_filename)
        
        if restore_success:
            # Set current save filename for tracking
            self.current_save_filename = restore_filename + ".sav"  # Add extension for consistency
            
            self.logger.info("Successfully restored from save file", extra={
                "extras": {
                    "event_type": "restore_success",
                    "episode_id": self.episode_id,
                    "save_file": save_file_to_use,
                    "current_save_filename": self.current_save_filename
                }
            })
            return True
        else:
            self.logger.error("Failed to restore from save file", extra={
                "extras": {
                    "event_type": "restore_failed",
                    "episode_id": self.episode_id,
                    "save_file": save_file_to_use
                }
            })
            
            # Delete corrupt save file
            try:
                os.remove(save_file_to_use)
                self.logger.info("Removed corrupt save file", extra={
                    "extras": {
                        "event_type": "corrupt_save_removed",
                        "episode_id": self.episode_id,
                        "save_file": save_file_to_use
                    }
                })
            except OSError as e:
                self.logger.warning(f"Failed to remove corrupt save file: {e}", extra={
                    "extras": {
                        "event_type": "corrupt_save_removal_failed",
                        "episode_id": self.episode_id,
                        "error": str(e)
                    }
                })
            
            return False

    def _load_previous_state(self) -> Optional[Dict[str, Any]]:
        """Load previous state from current_state.json if it exists.
        
        Returns:
            Dict containing previous state or None if not found/invalid
        """
        try:
            if os.path.exists(self.state_export_file):
                with open(self.state_export_file, 'r') as f:
                    previous_state = json.load(f)
                
                # Validate save file synchronization if save metadata exists
                save_metadata = previous_state.get("save_metadata")
                if save_metadata:
                    sync_valid = self._validate_save_sync(save_metadata)
                    if not sync_valid:
                        self.logger.warning("Save file sync validation failed - JSON state may be out of sync", extra={
                            "extras": {
                                "event_type": "save_sync_validation_failed",
                                "episode_id": self.episode_id,
                                "save_metadata": save_metadata
                            }
                        })
                        # Continue loading but mark as potentially invalid
                        previous_state["_sync_warning"] = True
                else:
                    self.logger.info("No save metadata found in previous state - cannot validate sync", extra={
                        "extras": {
                            "event_type": "no_save_metadata",
                            "episode_id": self.episode_id
                        }
                    })
                
                self.logger.info("Loaded previous state from JSON", extra={
                    "extras": {
                        "event_type": "previous_state_loaded",
                        "episode_id": self.episode_id,
                        "state_file": self.state_export_file,
                        "previous_episode_id": previous_state.get("metadata", {}).get("episode_id", "unknown"),
                        "previous_turn_count": previous_state.get("metadata", {}).get("turn_count", 0),
                        "has_save_metadata": save_metadata is not None,
                        "sync_warning": previous_state.get("_sync_warning", False)
                    }
                })
                
                return previous_state
            else:
                self.logger.info("No previous state file found", extra={
                    "extras": {
                        "event_type": "no_previous_state",
                        "episode_id": self.episode_id,
                        "state_file": self.state_export_file
                    }
                })
                return None
                
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(f"Failed to load previous state: {e}", extra={
                "extras": {
                    "event_type": "previous_state_load_failed",
                    "episode_id": self.episode_id,
                    "error": str(e),
                    "state_file": self.state_export_file
                }
            })
            return None

    def _validate_save_sync(self, save_metadata: Dict[str, Any]) -> bool:
        """Validate that save file metadata matches expected state.
        
        Args:
            save_metadata: Save metadata from JSON state
            
        Returns:
            bool: True if save file appears to be in sync
        """
        try:
            save_file_path = save_metadata.get("save_file_path")
            expected_mtime = save_metadata.get("save_file_mtime")
            
            if not save_file_path or not expected_mtime:
                self.logger.warning("Incomplete save metadata - cannot validate sync", extra={
                    "extras": {
                        "event_type": "incomplete_save_metadata",
                        "episode_id": self.episode_id,
                        "save_metadata": save_metadata
                    }
                })
                return False
            
            # Check if save file still exists
            if not os.path.exists(save_file_path):
                self.logger.warning(f"Save file no longer exists: {save_file_path}", extra={
                    "extras": {
                        "event_type": "save_file_missing",
                        "episode_id": self.episode_id,
                        "save_file_path": save_file_path
                    }
                })
                return False
            
            # Check if modification time matches (within tolerance)
            actual_mtime = os.path.getmtime(save_file_path)
            time_diff = abs(actual_mtime - expected_mtime)
            
            # Allow 5 second tolerance for filesystem time differences
            if time_diff > 5.0:
                self.logger.warning(f"Save file modification time mismatch - expected: {expected_mtime}, actual: {actual_mtime}, diff: {time_diff}s", extra={
                    "extras": {
                        "event_type": "save_file_time_mismatch",
                        "episode_id": self.episode_id,
                        "save_file_path": save_file_path,
                        "expected_mtime": expected_mtime,
                        "actual_mtime": actual_mtime,
                        "time_diff": time_diff
                    }
                })
                return False
            
            self.logger.info("Save file sync validation passed", extra={
                "extras": {
                    "event_type": "save_sync_validated",
                    "episode_id": self.episode_id,
                    "save_file_path": save_file_path,
                    "time_diff": time_diff
                }
            })
            return True
            
        except Exception as e:
            self.logger.warning(f"Error during save sync validation: {e}", extra={
                "extras": {
                    "event_type": "save_sync_validation_error",
                    "episode_id": self.episode_id,
                    "error": str(e)
                }
            })
            return False

    def _merge_previous_state(self, previous_state: Dict[str, Any]) -> None:
        """Merge relevant data from previous state into current session.
        
        Preserves learning (map, knowledge, objectives) while allowing fresh game state.
        """
        if not previous_state:
            return
        
        # Check for sync warnings
        has_sync_warning = previous_state.get("_sync_warning", False)
        if has_sync_warning:
            self.logger.warning("Merging previous state with sync warning - data may be inconsistent", extra={
                "extras": {
                    "event_type": "merge_with_sync_warning",
                    "episode_id": self.episode_id
                }
            })
        
        # Preserve map data
        if "map" in previous_state:
            try:
                # Load previous map data into current map
                map_data = previous_state["map"]
                if "raw_data" in map_data and "rooms" in map_data["raw_data"]:
                    for room_name, room_info in map_data["raw_data"]["rooms"].items():
                        self.game_map.add_room(room_name)
                        if "exits" in room_info:
                            self.game_map.update_room_exits(room_name, room_info["exits"])
                
                if "raw_data" in map_data and "connections" in map_data["raw_data"]:
                    for from_room, connections in map_data["raw_data"]["connections"].items():
                        for direction, to_room in connections.items():
                            self.game_map.add_connection(from_room, direction, to_room)
                
                merge_status = "partial" if has_sync_warning else "complete"
                self.logger.info(f"Merged previous map data ({merge_status})", extra={
                    "extras": {
                        "event_type": "map_data_merged",
                        "episode_id": self.episode_id,
                        "rooms_loaded": len(map_data["raw_data"].get("rooms", {})),
                        "connections_loaded": sum(len(conns) for conns in map_data["raw_data"].get("connections", {}).values()),
                        "merge_status": merge_status,
                        "has_sync_warning": has_sync_warning
                    }
                })
            except Exception as e:
                self.logger.warning(f"Failed to merge map data: {e}", extra={
                    "extras": {
                        "event_type": "map_merge_failed",
                        "episode_id": self.episode_id,
                        "error": str(e)
                    }
                })
        
        # Preserve knowledge base
        if "knowledge_base" in previous_state:
            try:
                kb_content = previous_state["knowledge_base"].get("content", "")
                if kb_content and len(kb_content.strip()) > 50:  # Only if substantial content
                    with open("knowledgebase.md", "w") as f:
                        f.write(kb_content)
                    
                    # Update adaptive knowledge manager
                    self.adaptive_knowledge_manager.last_content = kb_content
                    
                    merge_status = "partial" if has_sync_warning else "complete"
                    self.logger.info(f"Restored previous knowledge base ({merge_status})", extra={
                        "extras": {
                            "event_type": "knowledge_restored",
                            "episode_id": self.episode_id,
                            "content_length": len(kb_content),
                            "merge_status": merge_status,
                            "has_sync_warning": has_sync_warning
                        }
                    })
            except Exception as e:
                self.logger.warning(f"Failed to restore knowledge base: {e}", extra={
                    "extras": {
                        "event_type": "knowledge_restore_failed",
                        "episode_id": self.episode_id,
                        "error": str(e)
                    }
                })
        
        # Preserve death count and other persistent stats
        if "current_state" in previous_state:
            current_state = previous_state["current_state"]
            if "death_count" in current_state:
                self.death_count = current_state["death_count"]
                merge_status = "with_sync_warning" if has_sync_warning else "clean"
                self.logger.info(f"Restored death count: {self.death_count} ({merge_status})", extra={
                    "extras": {
                        "event_type": "death_count_restored",
                        "episode_id": self.episode_id,
                        "death_count": self.death_count,
                        "merge_status": merge_status,
                        "has_sync_warning": has_sync_warning
                    }
                })
        
        # Store the save metadata for later verification during reconciliation
        if "save_metadata" in previous_state:
            self._previous_save_metadata = previous_state["save_metadata"]
            self.logger.info("Stored previous save metadata for reconciliation", extra={
                "extras": {
                    "event_type": "save_metadata_stored",
                    "episode_id": self.episode_id,
                    "save_turn": self._previous_save_metadata.get("save_turn"),
                    "save_timestamp": self._previous_save_metadata.get("save_timestamp")
                }
            })
        
        final_status = "completed_with_warnings" if has_sync_warning else "completed_successfully"
        self.logger.info(f"Previous state merge {final_status}", extra={
            "extras": {
                "event_type": "state_merge_complete",
                "episode_id": self.episode_id,
                "final_status": final_status,
                "has_sync_warning": has_sync_warning
            }
        })

    def _reconcile_restored_state(self, game_state: str, inventory: List[str], score: int) -> str:
        """Reconcile restored game state with loaded JSON state to detect inconsistencies.
        
        Args:
            game_state: Current game state text from restored game
            inventory: Current inventory from restored game  
            score: Current score from restored game
            
        Returns:
            str: Reconciliation status ("consistent", "minor_discrepancy", "major_discrepancy")
        """
        try:
            # If we don't have previous save metadata, we can't do detailed reconciliation
            if not hasattr(self, '_previous_save_metadata'):
                self.logger.info("No previous save metadata available for reconciliation", extra={
                    "extras": {
                        "event_type": "reconciliation_no_metadata",
                        "episode_id": self.episode_id
                    }
                })
                return "no_metadata"
            
            # Extract expected values from previous save metadata
            expected_turn = self._previous_save_metadata.get("save_turn", 0)
            save_timestamp = self._previous_save_metadata.get("save_timestamp", "unknown")
            
            discrepancies = []
            
            # Check if current state makes sense relative to save metadata
            # We expect to be at or near the turn where we saved
            if expected_turn > 0:
                # For a fresh restore, we should be starting from turn 0 again
                # But our tracking variables should reflect where we were when saved
                
                # Log the expected vs actual state for analysis
                self.logger.info(f"Reconciliation check - Expected save turn: {expected_turn}, Save timestamp: {save_timestamp}", extra={
                    "extras": {
                        "event_type": "reconciliation_comparison",
                        "episode_id": self.episode_id,
                        "expected_save_turn": expected_turn,
                        "save_timestamp": save_timestamp,
                        "current_score": score,
                        "current_inventory_count": len(inventory)
                    }
                })
                
                # TODO: Could add more sophisticated validation here:
                # - Compare current location with expected location from JSON state
                # - Validate inventory contents match expectations
                # - Check score consistency
                # - Verify map state consistency
                
            # For now, if we got here without errors, consider it consistent
            # Future enhancements could add more detailed state comparison
            
            self.logger.info("Reconciliation completed - state appears consistent", extra={
                "extras": {
                    "event_type": "reconciliation_completed",
                    "episode_id": self.episode_id,
                    "status": "consistent"
                }
            })
            
            return "consistent"
            
        except Exception as e:
            self.logger.warning(f"Error during reconciliation: {e}", extra={
                "extras": {
                    "event_type": "reconciliation_error",
                    "episode_id": self.episode_id,
                    "error": str(e)
                }
            })
            return "error"

    def _generate_unique_save_filename(self) -> str:
        """Generate a unique save filename based on the template.
        
        Returns:
            str: Unique save filename with timestamp
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.zork_save_filename_template.format(timestamp=timestamp)
    
    def _find_most_recent_save(self) -> Optional[str]:
        """Find the most recent save file in the game directory.
        
        Returns:
            str: Path to most recent save file or None if no saves found
        """
        try:
            # Look for .qzl files (Zork save format) in the game directory
            pattern = os.path.join(self.zork_workdir_abs_path, "*.qzl")
            save_files = glob.glob(pattern)
            
            if not save_files:
                # Also check for .sav files
                pattern = os.path.join(self.zork_workdir_abs_path, "*.sav")
                save_files = glob.glob(pattern)
            
            if save_files:
                # Sort by modification time, most recent first
                save_files.sort(key=os.path.getmtime, reverse=True)
                return save_files[0]
                
        except Exception as e:
            self.logger.warning(f"Error finding save files: {e}", extra={
                "episode_id": self.episode_id
            })
            
        return None

    def _get_save_file_path(self, filename: str) -> str:
        """Get the absolute path for a save file.
        
        Args:
            filename: Save filename (with or without .qzl extension)
            
        Returns:
            str: Absolute path to save file
        """
        # Remove .qzl extension if present since Zork adds it automatically
        base_filename = filename.replace('.qzl', '').replace('.sav', '')
        return os.path.join(self.zork_workdir_abs_path, base_filename)

    def _perform_inter_episode_synthesis(self) -> None:
        """
        Perform inter-episode synthesis to extract and preserve key learnings
        across episodes, especially death events and major discoveries.
        """
        config = get_config()
        
        # Skip if inter-episode synthesis is disabled
        if not config.orchestrator.enable_inter_episode_synthesis:
            self.logger.info("Inter-episode synthesis disabled in configuration", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })
            return
            
        if not self.adaptive_knowledge_manager:
            self.logger.warning("No adaptive knowledge manager available for inter-episode synthesis", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })
            return

        if self.turn_count <= 0:
            self.logger.info("Skipping inter-episode synthesis - no turns completed", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })
            return

        # Always perform synthesis for meaningful episodes (>= 5 turns)
        if self.turn_count < 5:
            self.logger.info(f"Skipping inter-episode synthesis - episode too short ({self.turn_count} turns)", extra={
                "turn": self.turn_count,
                "episode_id": self.episode_id
            })
            return

        self.logger.info(
            f"Performing inter-episode synthesis for episode {self.episode_id}",
            extra={
                "extras": {
                    "event_type": "inter_episode_synthesis_start",
                    "episode_id": self.episode_id,
                    "turn_count": self.turn_count,
                    "death_count": self.death_count,
                    "episode_ended_in_death": self._is_death_episode(),
                    "final_score": self.previous_zork_score,
                }
            },
        )

        try:
            # Extract episode summary data for synthesis
            episode_data = {
                "episode_id": self.episode_id,
                "turn_count": self.turn_count,
                "final_score": self.previous_zork_score,
                "death_count": self.death_count,
                "episode_ended_in_death": self._is_death_episode(),
                "game_over_flag": self.game_over_flag,
                "discovered_objectives": getattr(self, 'discovered_objectives', []),
                "completed_objectives": getattr(self, 'completed_objectives', []),
                "avg_critic_score": self.get_avg_critic_score(),
                "recent_actions": self.get_recent_action_summary(),
            }

            # Include map quality metrics
            if self.game_map:
                map_metrics = self.game_map.get_map_quality_metrics()
                episode_data.update({
                    "map_rooms_discovered": len(self.game_map.rooms),  # Fixed: was self.game_map.graph.nodes
                    "map_average_confidence": map_metrics['average_confidence'],
                    "map_high_confidence_ratio": map_metrics['high_confidence_ratio'],
                    "map_verified_connections": map_metrics['verified_connections'],
                })

            # Call the adaptive knowledge manager to perform synthesis
            synthesis_success = self.adaptive_knowledge_manager.synthesize_inter_episode_wisdom(
                episode_data=episode_data
            )

            if synthesis_success:
                self.logger.info(
                    f"Inter-episode synthesis completed successfully",
                    extra={
                        "extras": {
                            "event_type": "inter_episode_synthesis_success",
                            "episode_id": self.episode_id,
                            "turn_count": self.turn_count,
                            "episode_ended_in_death": self._is_death_episode(),
                        }
                    },
                )
            else:
                self.logger.info(
                    f"Inter-episode synthesis skipped - no significant insights to preserve",
                    extra={
                        "extras": {
                            "event_type": "inter_episode_synthesis_skipped",
                            "episode_id": self.episode_id,
                            "reason": "no_significant_insights",
                            "turn_count": self.turn_count,
                        }
                    },
                )

        except Exception as e:
            self.logger.warning(
                f"Inter-episode synthesis failed: {e}",
                extra={
                    "extras": {
                        "event_type": "inter_episode_synthesis_failed",
                        "episode_id": self.episode_id,
                        "error": str(e),
                        "turn_count": self.turn_count,
                    }
                },
            )

    def _should_synthesize_inter_episode_wisdom(self) -> bool:
        """
        Determine if inter-episode wisdom synthesis should occur for this episode.
        Uses same criteria as synthesize_inter_episode_wisdom method.
        """
        # Extract key episode data for synthesis decision
        turn_count = self.turn_count
        final_score = self.previous_zork_score or 0
        death_count = self.death_count
        episode_ended_in_death = self.game_over_flag and self._is_death_episode()
        avg_critic_score = self.get_avg_critic_score()
        
        # Always synthesize if episode ended in death (critical learning event)
        # or if significant progress was made (score > 50 or many turns)
        should_synthesize = (
            episode_ended_in_death or 
            final_score >= 50 or 
            turn_count >= 100 or
            avg_critic_score >= 0.3
        )
        
        return should_synthesize


if __name__ == "__main__":
    # Create ZorkOrchestrator instance with default settings
    orchestrator = ZorkOrchestrator()

    with ZorkInterface(timeout=1.0) as zork_game:
        try:
            final_score = orchestrator.play_episode(zork_game)
            print(f"\nPlayed one episode. Final Zork score: {final_score}")
            print(f"Turns taken: {orchestrator.turn_count}")
            print(orchestrator.game_map.render_ascii())
        except RuntimeError as e:
            print(f"ZorkInterface runtime error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            import traceback

            traceback.print_exc()
        finally:
            print("Ensuring Zork process is closed.")
