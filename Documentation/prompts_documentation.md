# ZorkGPT Prompts Documentation

This document lists all prompts used in the ZorkGPT codebase and their respective locations.

## Table of Contents
1. [System Prompts (From Markdown Files)](#system-prompts-from-markdown-files)
2. [Inline Prompts in Python Files](#inline-prompts-in-python-files)

---

## System Prompts (From Markdown Files)

### 1. Agent System Prompt
**File:** [`agent.md`](Z:/ZorkGPT/agent.md:1-219)
**Purpose:** Main instruction set for the AI agent playing Zork
**Key Features:**
- Objective Development Framework for learning through play
- Strategic thinking process and prioritization system
- Critical exploration and navigation strategy
- Parser understanding and command formatting
- Anti-repetition rules and loop detection

### 2. Critic System Prompt
**File:** [`critic.md`](Z:/ZorkGPT/critic.md:1-114)
**Purpose:** Evaluates the quality of agent's proposed actions
**Key Features:**
- Relevance and contextual awareness evaluation
- Progress potential and goal orientation assessment
- Information gathering and exploration scoring
- Spatial awareness with tiered exit validation
- Repetition and stagnation avoidance scoring

### 3. Extractor System Prompt
**File:** [`extractor.md`](Z:/ZorkGPT/extractor.md:1-195)
**Purpose:** Extracts structured information from game text
**Key Features:**
- Location extraction with canonical naming
- Comprehensive exit detection including hidden passages
- Combat state persistence rules
- JSON output format specification

---

## Inline Prompts in Python Files

### 4. Episode Summary Prompt
**File:** [`zork_orchestrator.py:2193-2215`](Z:/ZorkGPT/zork_orchestrator.py:2193)
**Purpose:** Generates comprehensive gameplay summaries
**Usage Context:** Called when summarizing gameplay sessions
**Key Elements:**
- Major discoveries and progress
- Key items obtained and used
- Important locations visited
- Puzzles solved or attempted
- Deaths and causes
- Strategic insights learned
- Current objectives and next steps

### 5. Objective Discovery/Update Prompt
**File:** [`zork_orchestrator.py:2432-2469`](Z:/ZorkGPT/zork_orchestrator.py:2432)
**Purpose:** Discovers and maintains agent objectives based on gameplay
**Usage Context:** Called every 20 turns to update objectives
**Key Elements:**
- Score-increasing activities identification
- Recurring pattern recognition
- Environmental clue analysis
- Obstacle significance assessment
- Strategic item/location identification

### 6. Objective Completion Evaluation Prompt
**File:** [`zork_orchestrator.py:2767-2783`](Z:/ZorkGPT/zork_orchestrator.py:2767)
**Purpose:** Determines if objectives were completed
**Usage Context:** Evaluates objective completion each turn
**Key Elements:**
- Direct achievement detection
- Score increase correlation
- Success response recognition
- Location/item change fulfillment

### 7. Objective Refinement Prompt
**File:** [`zork_orchestrator.py:2971-3007`](Z:/ZorkGPT/zork_orchestrator.py:2971)
**Purpose:** Refines objectives to prevent loops and focus on promising goals
**Usage Context:** Called when objectives exceed threshold
**Key Elements:**
- Loop and stagnation detection
- Exploration prioritization
- Problematic objective removal
- General goal preference

### 8. Knowledge Quality Assessment Prompt
**File:** [`zork_strategy_generator.py:462-492`](Z:/ZorkGPT/zork_strategy_generator.py:462)
**Purpose:** Evaluates potential value of gameplay data for knowledge extraction
**Usage Context:** Pre-screens data before full analysis
**Key Elements:**
- Strategic value assessment
- Repetitive pattern detection
- Knowledge base impact evaluation
- Death event prioritization

### 9. Full Strategic Insights Analysis Prompt
**File:** [`zork_strategy_generator.py:591-620`](Z:/ZorkGPT/zork_strategy_generator.py:591)
**Purpose:** Extracts comprehensive strategic insights from gameplay
**Usage Context:** Analyzes gameplay for knowledge base updates
**Key Elements:**
- Game world mechanics discovery
- Strategic pattern identification
- Environmental knowledge extraction
- Danger recognition
- Efficiency insights
- Problem-solving patterns

### 10. Escape Strategy Analysis Prompt
**File:** [`zork_strategy_generator.py:660-670`](Z:/ZorkGPT/zork_strategy_generator.py:660)
**Purpose:** Identifies escape strategies from stuck situations
**Usage Context:** Triggered when repetitive behavior detected
**Key Elements:**
- Stuck situation analysis
- Escape discovery insights
- Location change patterns
- Score change indicators

### 11. Comprehensive Strategy Analysis Prompt
**File:** [`zork_strategy_generator.py:764-797`](Z:/ZorkGPT/zork_strategy_generator.py:764)
**Purpose:** Provides comprehensive strategic insights with persistent wisdom
**Usage Context:** Full analysis incorporating cross-episode knowledge
**Key Elements:**
- Persistent wisdom leverage
- Cross-episode validation
- Long-term strategic patterns
- Coordination with objectives system

### 12. Knowledge Consolidation Prompt
**File:** [`zork_strategy_generator.py:837-840`](Z:/ZorkGPT/zork_strategy_generator.py:837)
**Purpose:** Consolidates existing knowledge without new data
**Usage Context:** Improves knowledge base organization
**Key Elements:**
- AI-centric advice focus
- Human-centric content removal

### 13. Knowledge Base Merging Prompt
**File:** [`zork_strategy_generator.py:951-975`](Z:/ZorkGPT/zork_strategy_generator.py:951)
**Purpose:** Merges new insights with existing knowledge base
**Usage Context:** Integrates new discoveries into knowledge base
**Key Elements:**
- Contradiction resolution
- Redundancy removal
- Structure maintenance
- AI-focused language

### 14. New Knowledge Base Creation Prompt
**File:** [`zork_strategy_generator.py:1004-1035`](Z:/ZorkGPT/zork_strategy_generator.py:1004)
**Purpose:** Creates comprehensive strategy guide from insights
**Usage Context:** Initial knowledge base generation
**Key Elements:**
- Strategic discovery frameworks
- Objective discovery patterns
- Progress recognition methods
- Goal maintenance strategies
- Learning pattern identification

### 15. Knowledge Condensation Prompt
**File:** [`zork_strategy_generator.py:1111-1135`](Z:/ZorkGPT/zork_strategy_generator.py:1111)
**Purpose:** Condenses knowledge base while preserving critical information
**Usage Context:** Reduces knowledge base size for efficiency
**Key Elements:**
- No new strategy addition
- Critical information preservation
- Redundancy elimination
- Structure maintenance
- 50-70% size target

### 16. Persistent Wisdom Synthesis Prompt
**File:** [`zork_strategy_generator.py:1515-1557`](Z:/ZorkGPT/zork_strategy_generator.py:1515)
**Purpose:** Extracts cross-episode learnings for persistent wisdom
**Usage Context:** End of episode wisdom extraction
**Key Elements:**
- Death pattern analysis
- Critical environmental knowledge
- Strategic pattern synthesis
- Discovery insights
- Cross-episode learning

---

## Prompt Usage Patterns

### Frequency of Use
- **Agent Prompt:** Every turn (main gameplay)
- **Critic Prompt:** Every turn (action evaluation)
- **Extractor Prompt:** Every turn (information extraction)
- **Objective Prompts:** Every 20 turns or on-demand
- **Knowledge Prompts:** End of episode or periodic updates
- **Summary Prompts:** Periodic or on-demand

### Model Usage
- Most prompts use the configured `analysis_model` (typically GPT-4 or similar)
- Some use specialized models for specific tasks (e.g., extraction model)
- Temperature and sampling parameters vary by prompt type

### Token Management
- Prompts include context windows to manage token usage
- Recent history limited to last 8 turns for agent
- Knowledge base condensation targets 50-70% size reduction
- Strategic use of summaries to compress historical data

---

## Notes for Developers

1. **Prompt Modifications:** When modifying prompts, ensure consistency with the overall system architecture
2. **Token Limits:** Be mindful of context limits when adding to prompts
3. **Coordination:** Agent, Critic, and Extractor prompts must remain synchronized
4. **Testing:** Changes to prompts should be tested across multiple gameplay scenarios
5. **Documentation:** Update this document when adding or modifying prompts