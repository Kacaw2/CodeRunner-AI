# Memory Module Comparison: CodeRunner-AI vs Claude Code and Codex

Date: 2026-06-03

This document preserves the memory-module analysis from the current conversation. It compares the current CodeRunner-AI `memory/` implementation with the memory and instruction patterns used by Claude Code and Codex.

## Conclusion

CodeRunner-AI already has a usable memory foundation, but it is closer to "business profile plus conversation-summary prompt injection" than to the layered, auditable, editable memory systems used by Claude Code and Codex.

The current implementation can support tutoring and generation personalization, but the governance boundary is weak: rules, preferences, summaries, and inferred user state are all flattened into prompt text.

## Current CodeRunner-AI Memory Layers

### Short-Term Memory

`MemoryService.compact_messages()` compresses long conversations when message count exceeds the threshold. It is called from the shared base agent paths:

- `agents/base.py`: sync `_invoke_with_mcp_tools()`
- `agents/base.py`: streaming `_stream_with_mcp_tools()`

Behavior:

- Keeps the system message.
- Keeps the latest messages.
- Summarizes older history through the LLM.
- Falls back to simple truncation-style summary if compression fails.

### Mid-Term Memory

`AIConversation.summary` stores generated conversation summaries. `_maybe_generate_summary()` in `app/api/v1/ai.py` triggers async summary generation when the conversation has enough messages and no summary exists.

`MemoryService.get_memory_context()` then pulls recent prior conversation summaries and excludes the current in-progress conversation to avoid echoing the current session back into the prompt.

### Long-Term Profile Memory

`StudentProfile` and `TeacherPreference` are the persistent business-profile stores.

Student profile fields include:

- `error_patterns`
- `knowledge_map`
- `recent_topics`
- `recent_questions`
- `current_hint_level`
- `learning_summary`
- `preferred_language`

Teacher preference fields include:

- `preferred_difficulty`
- `preferred_language`
- `preferred_topics`
- `style_notes`
- `class_weak_areas`
- `class_level`

### Preference Learning

`memory/preference.py` learns teacher preferences from generation history:

- `learn_from_generation()` updates language, difficulty, and topic preferences.
- `refresh_teacher_style_summary()` uses recent generated drafts to write `style_notes`.
- `analyze_class_weak_areas()` aggregates weak areas across classroom student profiles.

## Claude Code Comparison

Claude Code separates persistent instructions and auto memory.

### Persistent Instructions

Claude Code uses `CLAUDE.md` files at multiple scopes:

- Managed policy.
- User instructions.
- Project instructions.
- Local private instructions.

These files are explicit, readable, and intentionally scoped. They are used for things that should be known every session: build commands, project conventions, workflow rules, and architecture facts.

### Auto Memory

Claude Code auto memory stores project learnings in a project memory directory, with a concise `MEMORY.md` index and optional topic files. It is local, editable, and auditable. The first part of `MEMORY.md` is loaded at session start; detailed topic files are read on demand.

### Key Difference

Claude Code treats memory as visible project working state, not just hidden prompt construction.

## Codex Comparison

Codex also separates durable guidance from generated memories.

### Durable Rules

Codex uses `AGENTS.md` and related project instruction discovery for required team guidance. These files are loaded through a defined precedence chain and should hold rules that must reliably apply.

### Generated Memories

Codex memories are local generated state under the Codex home directory. They can capture stable preferences, recurring workflows, tech stacks, project conventions, and known pitfalls. Codex documentation explicitly treats memories as helpful recall, not the only source for rules that must always apply.

### Skills

Codex skills use progressive disclosure: the agent sees the skill name, description, and path first, then loads full instructions only when relevant. This avoids stuffing every workflow into the prompt every time.

### Key Difference

Codex separates:

- Always-on team/project rules.
- Optional generated recall.
- On-demand workflows.

CodeRunner-AI currently has no equivalent separation.

## Main Gaps in CodeRunner-AI

### 1. Rules and Memory Are Not Separated

The current system injects profiles, preferences, and recent summaries into system context strings. It does not clearly distinguish:

- Must-follow platform rules.
- User-editable preferences.
- Model-inferred profile data.
- Conversation summaries that are only weak context.

For a mature agent platform, these should have different storage, editability, trust levels, and prompt placement.

### 2. Missing Audit and Edit Surface

Claude Code and Codex both expose memory as inspectable local state or user-controllable behavior. CodeRunner-AI exposes profile endpoints, but there is no clear record of:

- Which memory snippets were injected into a given agent run.
- Where each snippet came from.
- When it was updated.
- Whether the user can delete or override it.
- Whether it was inferred by the model or explicitly set by a user.

### 3. Student Long-Term Profile Is Incomplete

`MemoryService.update_student_profile()` mainly rebuilds `error_patterns` and `recent_questions` from recent submissions. But `learning_summary`, `knowledge_map`, and `current_hint_level` are read during prompt construction and do not have an obvious robust automatic write path.

This creates fields that look mature in the schema but may stay empty or stale in real use.

### 4. Stream Path Consistency Risk

The shared base agent paths call `MemoryService.compact_messages()`, but `GeneratorAgent.stream()` assembles its own message list and does not call that compaction helper. Long generator conversations may bypass the same memory compaction behavior used elsewhere.

### 5. Narrow Test Coverage

Existing focused tests cover:

- Recent conversation summaries are replayed while excluding the current conversation.
- Teacher preference learning creates and updates basic preference fields.

Missing coverage includes:

- Async summary trigger behavior.
- Student profile refresh behavior.
- Prompt injection boundaries and length budgets.
- Memory deletion/edit/override behavior.
- Generator streaming memory consistency.
- Sensitive data redaction before memory injection or persistence.

## Recommended Target Shape

Split the memory module into four clearer boundaries.

### ProfileMemory

Business profiles for students and teachers.

Expected properties:

- User-visible.
- Editable or resettable.
- Records source and update time.
- Separates explicit user settings from inferred model summaries.

### SessionSummaryMemory

Cross-conversation summaries.

Expected properties:

- Excludes the current conversation.
- Has token/length budget.
- Has age and relevance controls.
- Stores source conversation IDs.

### InstructionMemory

This should not be hidden DB-learned memory. Rules that must be followed should live in checked-in docs, agent definitions, policy config, or explicit project instructions.

Expected properties:

- Versioned.
- Reviewable.
- Stable.
- Not silently inferred.

### MemoryAudit

Every agent run should be able to show what memory was injected.

Expected record:

- `run_id` or trace ID.
- Memory type.
- Source object/table.
- Snippet length.
- Update timestamp.
- Whether the snippet was explicit, inferred, or summarized.

## Recommended Execution Order

1. Add regression coverage and implementation for `GeneratorAgent.stream()` using `MemoryService.compact_messages()`.
2. Change `MemoryService.get_memory_context()` to return structured memory blocks, not only a flat string.
3. Add a memory-injection budget and audit record linked to agent traces.
4. Add metadata to memory entries: `source`, `scope`, `confidence`, `expires_at`, `user_editable`, and `sensitive`.
5. Implement or remove unpopulated student fields such as `learning_summary`, `knowledge_map`, and `current_hint_level`.
6. Add user-facing APIs for viewing, editing, resetting, and deleting profile memory.
7. Keep must-follow agent/platform rules out of inferred memory and put them into versioned docs or definitions.

## Prior Verification

The focused memory tests were run during this conversation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agents.py::TestMemorySummaryReplay tests\test_agent_features.py::TestPreferenceLearner -q
```

Result:

```text
4 passed
```

No source files were changed during the analysis pass.

## References

- Claude Code memory: https://code.claude.com/docs/en/memory
- Codex memories: https://developers.openai.com/codex/memories
- Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- Codex skills: https://developers.openai.com/codex/skills
