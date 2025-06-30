# Fix for Agent Using Adjectives in Commands

## Problem
The agent was using adjectives in commands like "take large egg" and "open hinged egg", which caused parser errors like "I don't know the word 'hinged'". This was happening because the agent prompt explicitly told the agent to "Use adjectives" when dealing with multiple similar objects.

## Root Cause
In the agent.md file:
- Line 148 said: "Use adjectives. If only one object matches a general noun (e.g., one 'key' in the room), the parser will likely understand `take key`."
- Line 377 said: "Use adjectives when multiple similar objects exist"

## Solution
Modified agent.md to emphasize that the parser CANNOT handle adjectives and the agent should use simple VERB NOUN commands:

1. Added a critical rule at the very beginning of the prompt (after line 1):
   ```
   **MOST CRITICAL RULE - NO ADJECTIVES IN COMMANDS:**
   The Zork parser CANNOT understand adjectives in commands. You MUST use simple VERB NOUN format:
   - ✓ CORRECT: `take egg`, `open door`, `examine tree`
   - ✗ WRONG: `take large egg`, `open wooden door`, `examine large tree`
   - ONLY use adjectives when game asks "Which one do you mean?"
   ```

2. Added a new section in "Interacting with the World" (line 141):
   ```
   **CRITICAL COMMAND RULE - NO ADJECTIVES:**
   The Zork parser has severe limitations with adjectives. You MUST follow this hierarchy:
   1. **ALWAYS start with simple VERB NOUN:** `take egg`, `open door`, `examine tree`
   2. **NEVER use adjectives unless asked:** Do NOT say `take large egg` or `open wooden door`
   3. **Only add adjectives when prompted:** If the game asks "Which door do you mean?" THEN use `wooden door`
   4. **Parser fails with adjectives:** Commands like `take jeweled egg`, `examine large tree`, `open hinged egg` will FAIL
   5. **Simple is ALWAYS better:** `take egg` > `take large egg`, `open door` > `open wooden door`
   ```

3. Modified line 148 from:
   - OLD: "Use adjectives. If only one object matches a general noun..."
   - NEW: "ALWAYS try simple VERB NOUN commands WITHOUT adjectives first (e.g., `take egg`, `open door`, `examine tree`). The parser often struggles with adjectives."

4. Added to "Gameplay Strategy & Mindset" section (line 196):
   ```
   2.  **CRITICAL - Command Format Strategy:**
       - **NEVER use adjectives in commands** - The parser fails with "I don't know the word" errors
       - **Always use simple VERB NOUN** - `take egg` NOT `take large egg`, `open door` NOT `open wooden door`
       - **Examples of CORRECT commands:** `take egg`, `open door`, `examine tree`, `take lamp`
       - **Examples of WRONG commands:** `take jeweled egg`, `open hinged egg`, `examine large tree`
       - **Only use adjectives when game asks** - Wait for "Which one do you mean?" prompts
   ```

5. Modified the parser understanding section (line 262):
   - OLD: "Adjectives: Sometimes required when there are multiple objects with the same name"
   - NEW: "Adjectives: ONLY use when the game specifically asks 'Which one do you mean?' Otherwise, the parser will fail with 'I don't know the word' errors."

6. Updated the summary at line 377:
   - OLD: "Use adjectives when multiple similar objects exist"
   - NEW: "AVOID adjectives unless game asks 'Which one do you mean?'"

## Expected Result
The agent should now:
- Always try simple VERB NOUN commands first (e.g., "take egg" instead of "take large egg")
- Only use adjectives when the game specifically prompts for clarification
- Avoid parser errors caused by unrecognized adjective words