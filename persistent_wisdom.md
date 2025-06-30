### Updated Persistent Wisdom for Zork

#### Death Avoidance Patterns
- **Troll Room (east exit)**: Moving east from the Troll Room causes instant death. This direction should be avoided until countermeasures are discovered.
- **Danger cue recognition**: Locations explicitly describing threats ("impenetrable forest," "boarded windows") signal irreversible danger. Treat these as hard boundaries without special equipment.

#### Critical Environmental Knowledge
- **Mailbox protocol**: The mailbox at "West of House" requires `open` before `take` reveals the leaflet. This nested interaction pattern may apply to other containers.
- **Dead-end signatures**: "The forest becomes impenetrable" indicates permanently blocked paths. Similar phrasing ("cannot proceed," "impossible") should halt exploration.
- **House access constraints**: Front/north house approaches are sealed (boarded doors/windows). Entry likely requires alternative paths like windows or rear entrances.

#### Strategic Principles
1. **Examination hierarchy**: 
   - Prioritize `examine` over interaction for new objects (prevents missed clues)
   - Re-examine locations after state changes (e.g., after opening mailbox)
2. **Movement protocol**: 
   - Test cardinal directions systematically (N→S→E→W→U→D) in new areas
   - Abandon directions after "impenetrable" descriptions to conserve turns
3. **Item criticality**: 
   - Collect documents immediately (leaflet likely contains essential clues)
   - Read collected texts within 3 turns of acquisition

#### Discovery Insights
- **Environmental storytelling**: Auditory cues ("chirping of a song bird") may indicate interactive elements or timed puzzles.
- **False interactives**: Some described objects (tree, leaf pile) have no function. Similar decorative elements should be deprioritized after initial examination.
- **Scoring pattern**: Objectives discovered but uncompleted (5 found, 0 completed) suggest multi-step puzzles requiring item combinations.

#### Cross-Episode Learning
- **Death memory**: Troll Room's east exit now joins the danger database. Future agents should:
  - Approach troll-related areas with extreme caution
  - Test combat commands (`attack`, `throw`) before movement in monster zones
- **Parser optimization**: Successful actions used simple VERB-NOUN syntax. Complex commands should be avoided until confirmed viable.

> **Wisdom Status**: First episode baseline established. Focus future sessions on leaflet utilization, house entry methods, and troll countermeasures.