"""End-to-end A/B test with COMPLEX tasks on a SMALL model.

Core hypothesis: skill-memory helps weaker models execute more complete workflows
by reminding them of steps that are easy to forget (testing, validation, cleanup).

For each task, we define "critical steps" — best-practice actions that the skill
teaches but a bare LLM might skip. We then check whether the agent actually
performed these steps in its execution trace.

Requires: configured ~/.nanobot/config.json with API key
Run:  pytest tests/test_skill_memory_e2e.py -v -s --run-e2e
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryStore
from nanobot.bus.queue import MessageBus
from nanobot.providers.litellm_provider import LiteLLMProvider

e2e = pytest.mark.e2e

# ════════════════════════════════════════════════
# Skills: encode best-practice workflows with
# steps that are easy to forget
# ════════════════════════════════════════════════

SKILL_CORPUS = [
    {
        "task": "Build Python package with module and automated tests",
        "steps": [
            "Create package directory with __init__.py",
            "Write the main module with functions",
            "Write unit test file using assert statements",
            "Run the tests to verify correctness",
            "Show test results to confirm all pass",
        ],
        "tools": ["exec", "write_file", "write_file", "write_file", "exec", "exec"],
        "tags": ["python", "package", "module", "test", "unittest", "build", "project"],
    },
    {
        "task": "Data processing pipeline: ingest, transform, export, validate",
        "steps": [
            "Create sample source data file",
            "Write processing script with error handling",
            "Run the processing script",
            "Read and validate the output file",
            "Print summary statistics to confirm correctness",
        ],
        "tools": ["write_file", "write_file", "exec", "read_file", "exec"],
        "tags": ["data", "pipeline", "transform", "csv", "json", "validate", "process", "export"],
    },
    {
        "task": "Create robust shell automation with logging and error handling",
        "steps": [
            "Write shell script with set -e for error handling",
            "Add logging with timestamps to a log file",
            "Create test fixtures (sample directories/files)",
            "Make script executable and run it",
            "Check log file to confirm execution",
            "Verify expected output files exist",
        ],
        "tools": ["write_file", "exec", "exec", "exec", "read_file", "exec"],
        "tags": ["shell", "bash", "automation", "logging", "error", "handling", "backup", "script", "robust"],
    },
]

# ════════════════════════════════════════════════
# Complex test tasks
# ════════════════════════════════════════════════

COMPLEX_TASKS = [
    {
        "query": (
            "Build me a Python math utilities package: create a directory 'mathutils', "
            "write a module with functions for factorial and fibonacci, "
            "then write and run tests to make sure they work correctly."
        ),
        "critical_steps": [
            ("Created package dir", "mathutils"),
            ("Wrote module code", "factorial"),
            ("Wrote test file", "test"),
            ("Ran tests", "assert"),
            ("Tests passed / verified", "pass"),
        ],
        "min_tool_calls": 4,
    },
    {
        "query": (
            "Create a data processing pipeline: first generate a sample JSON file with "
            "5 user records (name, email, age), then write a Python script that reads it, "
            "filters users older than 25, and exports the result to a CSV file. "
            "After running it, show me the CSV contents to verify it's correct."
        ),
        "critical_steps": [
            ("Created sample JSON", "json"),
            ("Wrote processing script", "csv"),
            ("Ran the script", "exec"),
            ("Read/verified CSV output", "read_file"),
            ("Showed filtered results", "csv"),
        ],
        "min_tool_calls": 4,
    },
    {
        "query": (
            "Create a shell script called backup.sh that: "
            "1) takes a source directory as argument, "
            "2) creates a timestamped tar.gz archive of it, "
            "3) logs each step to backup.log with timestamps, "
            "4) uses set -e for error handling. "
            "Then create a test directory with some files, run the backup script on it, "
            "and show me the log file to confirm it worked."
        ),
        "critical_steps": [
            ("Script has error handling", "set -e"),
            ("Script has logging", "log"),
            ("Created test fixtures", "mkdir"),
            ("Made executable & ran", "chmod"),
            ("Verified log output", "log"),
            ("Archive was created", "tar"),
        ],
        "min_tool_calls": 5,
    },
]

# ════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════


def _populate_skills(workspace: Path) -> None:
    store = MemoryStore(workspace)
    for skill in SKILL_CORPUS:
        with open(store.skills_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(skill, ensure_ascii=False) + "\n")


def _make_provider() -> tuple[LiteLLMProvider, str]:
    from nanobot.config.loader import load_config
    config = load_config()
    model = config.agents.defaults.model
    p = config.get_provider(model)
    provider_name = config.get_provider_name(model)
    provider = LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )
    return provider, model


def _create_agent(provider: LiteLLMProvider, model: str, workspace: Path) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=workspace,
        model=model,
        max_iterations=20,
        temperature=0.0,
        max_tokens=4096,
    )


def _trace_contains(tools_used: list[str], all_messages: list[dict], patterns: list[str]) -> list[bool]:
    """Check which patterns appear in the execution trace."""
    trace_text = ""
    for m in all_messages:
        content = m.get("content", "")
        if isinstance(content, str):
            trace_text += content + "\n"
        for tc in m.get("tool_calls", []):
            fn = tc.get("function", {})
            trace_text += f"{fn.get('name', '')} {fn.get('arguments', '')}\n"
    trace_lower = trace_text.lower()
    tool_str = " ".join(tools_used).lower()

    return [
        pattern.lower() in trace_lower or pattern.lower() in tool_str
        for pattern in patterns
    ]


async def _run_task(agent: AgentLoop, query: str) -> dict:
    messages = agent.context.build_messages(
        history=[],
        current_message=query,
        channel="test",
        chat_id="eval",
    )
    final_content, tools_used, all_messages = await agent._run_agent_loop(messages)
    return {
        "final_content": final_content or "",
        "tools_used": tools_used,
        "tool_call_count": len(tools_used),
        "iterations": sum(1 for m in all_messages if m.get("role") == "assistant"),
        "all_messages": all_messages,
    }


# ════════════════════════════════════════════════
# E2E A/B Test
# ════════════════════════════════════════════════


@e2e
class TestSkillMemoryE2E:

    @pytest.fixture(scope="class")
    def provider_and_model(self):
        return _make_provider()

    def test_complex_tasks_ab(self, provider_and_model, tmp_path: Path) -> None:
        provider, model = provider_and_model

        ws_with = tmp_path / "with_skills"
        ws_with.mkdir()
        _populate_skills(ws_with)

        ws_without = tmp_path / "without_skills"
        ws_without.mkdir()

        agent_with = _create_agent(provider, model, ws_with)
        agent_without = _create_agent(provider, model, ws_without)

        loop = asyncio.new_event_loop()
        results: list[dict] = []

        for task in COMPLEX_TASKS:
            query = task["query"]
            critical_steps = task["critical_steps"]

            r_with = loop.run_until_complete(_run_task(agent_with, query))
            r_without = loop.run_until_complete(_run_task(agent_without, query))

            step_patterns = [pattern for _, pattern in critical_steps]
            checks_with = _trace_contains(r_with["tools_used"], r_with["all_messages"], step_patterns)
            checks_without = _trace_contains(r_without["tools_used"], r_without["all_messages"], step_patterns)

            results.append({
                "query": query[:80],
                "critical_steps": critical_steps,
                "with": r_with,
                "without": r_without,
                "checks_with": checks_with,
                "checks_without": checks_without,
                "score_with": sum(checks_with),
                "score_without": sum(checks_without),
                "total_steps": len(critical_steps),
                "completed_with": r_with["tool_call_count"] >= task["min_tool_calls"],
                "completed_without": r_without["tool_call_count"] >= task["min_tool_calls"],
            })

        loop.close()

        # ── Detailed report ──
        print(f"\n{'='*70}")
        print(f"COMPLEX TASK A/B: {model}")
        print(f"{'='*70}")

        for i, r in enumerate(results, 1):
            w, wo = r["with"], r["without"]
            print(f"\n{'─'*70}")
            print(f"[Task {i}] {r['query']}...")
            print(f"\n  WITH skill-memory:")
            print(f"    Tools: {w['tools_used']}")
            print(f"    Tool calls: {w['tool_call_count']}, Iterations: {w['iterations']}")
            print(f"    Critical step checklist ({r['score_with']}/{r['total_steps']}):")
            for (name, _), passed in zip(r["critical_steps"], r["checks_with"]):
                print(f"      {'✓' if passed else '✗'} {name}")

            print(f"\n  WITHOUT skill-memory:")
            print(f"    Tools: {wo['tools_used']}")
            print(f"    Tool calls: {wo['tool_call_count']}, Iterations: {wo['iterations']}")
            print(f"    Critical step checklist ({r['score_without']}/{r['total_steps']}):")
            for (name, _), passed in zip(r["critical_steps"], r["checks_without"]):
                print(f"      {'✓' if passed else '✗'} {name}")

        # ── Aggregate ──
        n = len(results)
        total_steps_all = sum(r["total_steps"] for r in results)
        total_hit_with = sum(r["score_with"] for r in results)
        total_hit_without = sum(r["score_without"] for r in results)
        avg_tools_with = sum(r["with"]["tool_call_count"] for r in results) / n
        avg_tools_without = sum(r["without"]["tool_call_count"] for r in results) / n

        pct_with = total_hit_with / total_steps_all if total_steps_all else 0
        pct_without = total_hit_without / total_steps_all if total_steps_all else 0

        print(f"\n{'='*70}")
        print(f"AGGREGATE RESULTS ({n} complex tasks, {total_steps_all} critical steps total)")
        print(f"                              WITH skill    WITHOUT skill")
        print(f"  Critical steps completed:   {total_hit_with:>5d}/{total_steps_all}        {total_hit_without:>5d}/{total_steps_all}")
        print(f"  Critical step rate:         {pct_with:>8.1%}        {pct_without:>8.1%}")
        print(f"  Improvement:                +{pct_with - pct_without:.1%}")
        print(f"  Avg tool calls:             {avg_tools_with:>8.1f}        {avg_tools_without:>8.1f}")
        print(f"{'='*70}")
