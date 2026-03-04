# Skill Memory: Reusable Workflow Extraction for Nanobot

## Overview

Skill Memory extends Nanobot's memory system from two layers to three, adding automatic extraction and retrieval of reusable workflow patterns. When the agent successfully completes a multi-step task, the workflow is abstracted into a generic template and stored. When a similar task arrives later, relevant skills are retrieved and injected into the agent's context to guide execution.

### Before (Two-Layer Memory)

```
memory/
├── MEMORY.md     ← Long-term facts (semantic memory)
└── HISTORY.md    ← Event log (episodic memory)
```

### After (Three-Layer Memory)

```
memory/
├── MEMORY.md     ← Long-term facts (semantic memory)
├── HISTORY.md    ← Event log (episodic memory)
└── SKILLS.jsonl  ← Workflow patterns (skill memory)  ← NEW
```

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                   Skill Extraction                       │
│                                                         │
│  Task completed ──► Consolidation triggers              │
│                         │                               │
│                         ▼                               │
│               LLM analyzes conversation                 │
│                         │                               │
│                         ▼                               │
│              Extracts workflow pattern                   │
│            (generalized, no specifics)                   │
│                         │                               │
│                         ▼                               │
│              Deduplication check (Jaccard > 0.5)        │
│                         │                               │
│                    ┌────┴────┐                          │
│                    │ unique? │                          │
│                    └────┬────┘                          │
│                  yes/       \no                         │
│                   ▼          ▼                          │
│           Save to        Skip (log)                    │
│          SKILLS.jsonl                                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                   Skill Retrieval                        │
│                                                         │
│  New message ──► Extract query tokens                   │
│                         │                               │
│                         ▼                               │
│              Keyword match against                      │
│              skill tags + task descriptions              │
│                         │                               │
│                         ▼                               │
│              Return top-K most relevant                 │
│                         │                               │
│                         ▼                               │
│              Format as readable steps                   │
│                         │                               │
│                         ▼                               │
│              Inject into system prompt                  │
│              under "Learned Skills"                      │
└─────────────────────────────────────────────────────────┘
```

## Storage Format

Skills are stored in `memory/SKILLS.jsonl`, one JSON object per line:

```json
{"task": "Set up Python web API with REST endpoints", "steps": ["Create project directory structure", "Install web framework and dependencies", "Write application entry point with route handlers", "Add configuration for host and port", "Run and verify endpoints"], "tools": ["exec", "write_file", "exec"], "tags": ["python", "api", "web", "rest", "setup"], "recorded": "2025-03-04T10:30"}
```

### Skill Fields

| Field | Type | Description |
|-------|------|-------------|
| `task` | string | Abstract task description — generalized, no specific names or paths |
| `steps` | string[] | Ordered list of generalized steps |
| `tools` | string[] | Tool names used in the workflow |
| `tags` | string[] | Lowercase keywords for retrieval matching |
| `recorded` | string | ISO timestamp (auto-set on save) |

### Why JSONL

- Already used in the project (sessions are JSONL)
- Structured for keyword matching
- Append-friendly (no need to parse/rewrite full file)
- Human-readable and grep-able

## Implementation Details

### Files Changed

| File | Change | Lines |
|------|--------|-------|
| `nanobot/agent/memory.py` | Core skill memory logic | +128 |
| `nanobot/agent/context.py` | Thread query to skill retrieval | +4 |
| `nanobot/skills/memory/SKILL.md` | Documentation update | +5 |

### Key Methods (memory.py)

#### `load_skills() -> list[dict]`
Reads `SKILLS.jsonl` and returns all skills as a list of dicts. Silently skips malformed lines.

#### `save_skill(skill: dict) -> None`
Appends a skill to `SKILLS.jsonl` after deduplication. Auto-sets `recorded` timestamp.

#### `_is_duplicate_skill(new_skill: dict) -> bool`
Compares the new skill's tags against all existing skills using Jaccard similarity. Returns `True` if any existing skill has Jaccard > 0.5 (i.e., more than half the tags overlap).

```
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
```

#### `find_relevant_skills(query: str, top_k: int = 3) -> list[dict]`
Tokenizes the query, computes keyword overlap against each skill's tags + task description, returns the top-K most relevant skills sorted by score.

#### `get_skills_context(query: str, top_k: int = 3) -> str`
Calls `find_relevant_skills` (or returns the last K skills if no query), formats them as readable markdown with task name, tools, and numbered steps.

#### `get_memory_context(query: str = "") -> str`
Updated to include both long-term memory (MEMORY.md) and relevant skills in the output. The `query` parameter enables retrieval — when empty, falls back to most recent skills.

### Skill Extraction in Consolidation

Skill extraction piggybacks on the existing consolidation flow — **no extra LLM call**. The `save_memory` tool definition gains an optional `skill` field. The consolidation prompt is enhanced to:

1. Show existing skills (to avoid duplicates at the LLM level)
2. Ask the LLM to extract workflows when multi-step tool usage is detected
3. Require generalization (no specific filenames, URLs, or values)

The LLM returns `skill` as a JSON string. The handler:
1. Parses it (supports both string and dict formats from different providers)
2. Validates required fields (`task` and `steps`)
3. Delegates to `save_skill()` for deduplication and storage

### Skill Retrieval in Context Building

In `context.py`, `build_system_prompt` now passes the user's current message to `get_memory_context(query=current_message)`. This enables the keyword matching in `find_relevant_skills` to select contextually relevant skills rather than dumping all skills into the prompt.

## Design Decisions

### Single LLM Call
Skill extraction happens inside the existing consolidation call rather than a separate LLM invocation. This keeps the cost and latency unchanged for the common case (no skill detected), and adds zero overhead per-message.

### Keyword Matching over Embedding
Retrieval uses simple token overlap instead of vector similarity. Rationale:
- Zero new dependencies
- Fast enough for realistic skill counts (10-100)
- Avoids requiring an embedding model
- Can be upgraded to embedding-based retrieval later without changing the interface

### Jaccard Deduplication
Tags-based Jaccard similarity at threshold 0.5 provides a simple but effective guard against storing near-identical workflows. The LLM-level deduplication (showing existing skills in the prompt) serves as a first pass, and Jaccard serves as a second pass.

### Optional Skill Field
The `skill` field in `save_memory` is **not required**. This means:
- Existing consolidation behavior is completely unchanged
- The LLM only extracts a skill when it detects a genuine multi-step workflow
- Conversational sessions produce no skill output
- Full backward compatibility with older prompts/providers

## Example

### Extraction

User asks the agent to set up a Flask project. The agent runs:
1. `exec("mkdir myproject && cd myproject && pip install flask")`
2. `write_file("app.py", ...)`
3. `exec("python app.py &")`
4. `web_fetch("http://localhost:5000/health")`

During consolidation, the LLM extracts:

```json
{
  "task": "Set up Python web API with REST endpoints",
  "steps": [
    "Create project directory and install web framework",
    "Write application entry point with route handlers",
    "Start the application server",
    "Verify endpoints are responding"
  ],
  "tools": ["exec", "write_file", "exec", "web_fetch"],
  "tags": ["python", "api", "web", "rest", "flask", "setup", "server"]
}
```

### Retrieval

Later, the user asks: "Help me create a FastAPI project."

1. `find_relevant_skills("Help me create a FastAPI project")` tokenizes the query
2. Tokens `{"help", "me", "create", "a", "fastapi", "project"}` overlap with skill tags `{"python", "api", "web", ...}` and task tokens `{"set", "up", "python", "web", "api", ...}`
3. Overlap: `{"api", "python"}` → score = 2
4. The skill is injected into the system prompt:

```
## Learned Skills
Reusable workflow patterns from past tasks:

### Set up Python web API with REST endpoints
- Tools: exec, write_file, exec, web_fetch
- Steps:
  1. Create project directory and install web framework
  2. Write application entry point with route handlers
  3. Start the application server
  4. Verify endpoints are responding
```

5. The agent uses this as a reference to handle the FastAPI task.

## Future Improvements

These can be done as separate PRs:

1. **Workflow compression** — When SKILLS.jsonl grows large, merge similar skills
2. **Fix `tools_used` tracking** — Currently `loop.py` collects `tools_used` but discards it; persisting it to session messages would give consolidation better tool visibility
3. **Embedding-based retrieval** — Replace keyword matching with vector similarity for more accurate skill matching
4. **Skill evolution** — Allow the LLM to update existing skills when a better workflow is discovered for the same task
