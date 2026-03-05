"""End-to-end A/B test with COMPLEX tasks on a SMALL model.

Core hypothesis: skill-memory helps weaker models execute more complete workflows
by reminding them of steps that are easy to forget (testing, validation, cleanup).

For each task, we define "critical steps" — best-practice actions that the skill
teaches but a bare LLM might skip. We then check whether the agent actually
performed these steps in its execution trace.

Requires: configured ~/.leafbot/config.json with API key
Run:  pytest tests/test_skill_memory_e2e.py -v -s --run-e2e
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from leafbot.agent.loop import AgentLoop
from leafbot.agent.memory import MemoryStore
from leafbot.bus.queue import MessageBus
from leafbot.providers.litellm_provider import LiteLLMProvider

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
    {
        "task": "Build and test a CSV report generator from raw data",
        "steps": [
            "Create a raw data file (JSON or text) with sample records",
            "Write a Python script that reads, transforms, and writes a CSV report",
            "Run the script to generate the CSV",
            "Read the CSV output to verify correctness",
            "Write and run unit tests for the transformation logic",
        ],
        "tools": ["write_file", "write_file", "exec", "read_file", "write_file", "exec"],
        "tags": ["csv", "report", "generator", "data", "transform", "python", "test", "output"],
    },
    {
        "task": "Create a file search utility with pattern matching and results output",
        "steps": [
            "Create a test directory structure with various files",
            "Write a Python script that searches files by pattern/extension",
            "Run the search script and capture results",
            "Write results to an output file",
            "Read and verify the output file contains expected matches",
        ],
        "tools": ["exec", "write_file", "exec", "write_file", "read_file"],
        "tags": ["file", "search", "pattern", "directory", "find", "utility", "glob", "match"],
    },
    {
        "task": "Build a log parser that extracts error statistics from log files",
        "steps": [
            "Create a sample log file with mixed INFO/WARN/ERROR entries",
            "Write a Python parser script that counts errors by category",
            "Run the parser and display statistics",
            "Write statistics to a summary output file",
            "Read the summary to verify accuracy",
            "Write and run tests for the parsing logic",
        ],
        "tools": ["write_file", "write_file", "exec", "write_file", "read_file", "write_file", "exec"],
        "tags": ["log", "parser", "error", "statistics", "analysis", "summary", "count", "extract"],
    },
    {
        "task": "Create a markdown document generator from structured data",
        "steps": [
            "Create a JSON data file with structured content (title, sections, items)",
            "Write a Python script that converts JSON to formatted markdown",
            "Run the script to generate the markdown file",
            "Read the generated markdown to verify formatting",
            "Write and run tests for edge cases (empty sections, special chars)",
        ],
        "tools": ["write_file", "write_file", "exec", "read_file", "write_file", "exec"],
        "tags": ["markdown", "generator", "document", "json", "convert", "format", "template", "report"],
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
    {
        "query": (
            "I have some sales data I need to process. First, create a JSON file "
            "called sales.json with 8 records, each having 'product', 'quantity', "
            "and 'price' fields. Then write a Python script that reads it, "
            "calculates total revenue per product, and writes the results to "
            "report.csv. Run the script, then read report.csv to show me the results. "
            "Finally, write a test file that tests the calculation logic and run it."
        ),
        "critical_steps": [
            ("Created sales.json data file", "sales.json"),
            ("Wrote processing script", "csv"),
            ("Ran the script", "exec"),
            ("Read/verified report.csv", "read_file"),
            ("Wrote test file", "test"),
            ("Ran tests", "assert"),
        ],
        "min_tool_calls": 5,
    },
    {
        "query": (
            "Create a test directory structure: make a directory called 'project' "
            "with subdirectories 'src', 'docs', and 'tests'. Put a .py file in src, "
            "a .md file in docs, and a .txt file in tests. Then write a Python script "
            "called find_files.py that recursively lists all files in 'project' "
            "grouped by extension. Run the script and save its output to results.txt. "
            "Then read results.txt to verify it found all the files."
        ),
        "critical_steps": [
            ("Created directory structure", "mkdir"),
            ("Created sample files", "write_file"),
            ("Wrote search script", "find_files"),
            ("Ran the script", "exec"),
            ("Saved output to results.txt", "results.txt"),
            ("Read and verified results", "read_file"),
        ],
        "min_tool_calls": 5,
    },
    {
        "query": (
            "Create a sample log file called app.log with about 20 lines mixing "
            "INFO, WARNING, and ERROR entries (make some errors repeat like "
            "'ConnectionError' and 'TimeoutError'). Then write a Python script "
            "called log_parser.py that reads app.log, counts occurrences of each "
            "error type, and writes a summary to error_report.txt. "
            "Run the parser, then read error_report.txt to show me the results. "
            "Also write a test to verify the parsing works correctly and run it."
        ),
        "critical_steps": [
            ("Created app.log file", "app.log"),
            ("Wrote parser script", "log_parser"),
            ("Ran the parser", "exec"),
            ("Saved error_report.txt", "error_report"),
            ("Read and showed report", "read_file"),
            ("Wrote and ran tests", "test"),
        ],
        "min_tool_calls": 5,
    },
    {
        "query": (
            "Create a JSON file called pages.json with structured data: "
            "a title, an author, and 3 sections each with a heading and a list "
            "of bullet points. Then write a Python script called md_generator.py "
            "that reads pages.json and generates a properly formatted markdown "
            "file called output.md. Run the script, then read output.md to verify "
            "the markdown formatting is correct. Write a test for the generator "
            "logic and run it."
        ),
        "critical_steps": [
            ("Created pages.json", "pages.json"),
            ("Wrote generator script", "md_generator"),
            ("Ran the script", "exec"),
            ("Read output.md", "read_file"),
            ("Verified markdown format", "output.md"),
            ("Wrote and ran tests", "test"),
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
    from leafbot.config.loader import load_config
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
    """Check which patterns appear in the execution trace (tool calls + results only)."""
    tool_trace = ""
    for m in all_messages:
        for tc in m.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_trace += f"{fn.get('name', '')} {fn.get('arguments', '')}\n"
        if m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str):
                tool_trace += content + "\n"
    tool_trace_lower = tool_trace.lower()
    tool_str = " ".join(tools_used).lower()

    full_trace = tool_trace
    for m in all_messages:
        content = m.get("content", "")
        if isinstance(content, str):
            full_trace += content + "\n"
    full_trace_lower = full_trace.lower()

    return [
        pattern.lower() in tool_trace_lower
        or pattern.lower() in tool_str
        or pattern.lower() in full_trace_lower
        for pattern in patterns
    ]


def _tool_trace_contains(tools_used: list[str], all_messages: list[dict], patterns: list[str]) -> list[bool]:
    """Strict check: only count patterns found in actual tool calls and their results."""
    tool_trace = ""
    for m in all_messages:
        for tc in m.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_trace += f"{fn.get('name', '')} {fn.get('arguments', '')}\n"
        if m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str):
                tool_trace += content + "\n"
    tool_trace_lower = tool_trace.lower()
    tool_str = " ".join(tools_used).lower()

    return [
        pattern.lower() in tool_trace_lower or pattern.lower() in tool_str
        for pattern in patterns
    ]


def _analyze_trace(all_messages: list[dict]) -> dict:
    """Extract efficiency metrics from the execution trace."""
    error_retries = 0
    first_plan_tools = 0
    first_assistant_seen = False
    prev_failed_tools: set[str] = set()

    for m in all_messages:
        if m.get("role") == "assistant" and not first_assistant_seen:
            first_assistant_seen = True
            first_plan_tools = len(m.get("tool_calls", []))

        if m.get("role") == "tool":
            content = str(m.get("content", "")).lower()
            tool_name = m.get("name", "")
            if any(kw in content for kw in ("error", "traceback", "exception", "errno", "failed")):
                prev_failed_tools.add(tool_name)
            else:
                prev_failed_tools.discard(tool_name)

        if m.get("role") == "assistant" and first_assistant_seen:
            for tc in m.get("tool_calls", []):
                fn = tc.get("function", {})
                if fn.get("name") in prev_failed_tools:
                    error_retries += 1

    return {
        "error_retries": error_retries,
        "first_plan_tools": first_plan_tools,
    }


async def _run_task(agent: AgentLoop, query: str) -> dict:
    messages = agent.context.build_messages(
        history=[],
        current_message=query,
        channel="test",
        chat_id="eval",
    )
    final_content, tools_used, all_messages, usage = await agent._run_agent_loop(messages)
    trace_analysis = _analyze_trace(all_messages)
    return {
        "final_content": final_content or "",
        "tools_used": tools_used,
        "tool_call_count": len(tools_used),
        "iterations": sum(1 for m in all_messages if m.get("role") == "assistant"),
        "all_messages": all_messages,
        "total_tokens": usage.get("total_tokens", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        **trace_analysis,
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
            strict_with = _tool_trace_contains(r_with["tools_used"], r_with["all_messages"], step_patterns)
            strict_without = _tool_trace_contains(r_without["tools_used"], r_without["all_messages"], step_patterns)

            results.append({
                "query": query[:80],
                "critical_steps": critical_steps,
                "with": r_with,
                "without": r_without,
                "checks_with": checks_with,
                "checks_without": checks_without,
                "strict_with": strict_with,
                "strict_without": strict_without,
                "score_with": sum(checks_with),
                "score_without": sum(checks_without),
                "strict_score_with": sum(strict_with),
                "strict_score_without": sum(strict_without),
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
            for label, d, checks, strict, score, sscore in [
                ("WITH", w, r["checks_with"], r["strict_with"], r["score_with"], r["strict_score_with"]),
                ("WITHOUT", wo, r["checks_without"], r["strict_without"], r["score_without"], r["strict_score_without"]),
            ]:
                print(f"\n  {label} skill-memory:")
                print(f"    Tools: {d['tools_used']}")
                print(f"    Iterations: {d['iterations']}, Tool calls: {d['tool_call_count']}")
                print(f"    Tokens: {d['total_tokens']:,} (prompt: {d['prompt_tokens']:,}, completion: {d['completion_tokens']:,})")
                print(f"    Error retries: {d['error_retries']}, First-plan tools: {d['first_plan_tools']}")
                print(f"    Critical steps (tool-only) ({sscore}/{r['total_steps']}):")
                for (name, _), passed in zip(r["critical_steps"], strict):
                    print(f"      {'✓' if passed else '✗'} {name}")

        # ── Aggregate ──
        n = len(results)
        total_steps_all = sum(r["total_steps"] for r in results)
        strict_hit_with = sum(r["strict_score_with"] for r in results)
        strict_hit_without = sum(r["strict_score_without"] for r in results)
        total_iter_with = sum(r["with"]["iterations"] for r in results)
        total_iter_without = sum(r["without"]["iterations"] for r in results)
        total_tokens_with = sum(r["with"]["total_tokens"] for r in results)
        total_tokens_without = sum(r["without"]["total_tokens"] for r in results)
        total_retries_with = sum(r["with"]["error_retries"] for r in results)
        total_retries_without = sum(r["without"]["error_retries"] for r in results)
        avg_first_plan_with = sum(r["with"]["first_plan_tools"] for r in results) / n
        avg_first_plan_without = sum(r["without"]["first_plan_tools"] for r in results) / n
        avg_iter_with = total_iter_with / n
        avg_iter_without = total_iter_without / n
        avg_tools_with = sum(r["with"]["tool_call_count"] for r in results) / n
        avg_tools_without = sum(r["without"]["tool_call_count"] for r in results) / n

        strict_pct_with = strict_hit_with / total_steps_all if total_steps_all else 0
        strict_pct_without = strict_hit_without / total_steps_all if total_steps_all else 0

        def _pct_delta(a: float, b: float) -> str:
            if b == 0:
                return "N/A"
            return f"{(a - b) / b:+.1%}"

        print(f"\n{'='*70}")
        print(f"AGGREGATE RESULTS ({n} complex tasks, {total_steps_all} critical steps)")
        print(f"{'─'*70}")
        print(f"{'Metric':<30s} {'WITH':>12s} {'WITHOUT':>12s} {'Delta':>10s}")
        print(f"{'─'*70}")
        print(f"{'Error retries':<30s} {total_retries_with:>12d} {total_retries_without:>12d} {_pct_delta(total_retries_with, total_retries_without):>10s}")
        print(f"{'Total tokens':<30s} {total_tokens_with:>12,} {total_tokens_without:>12,} {_pct_delta(total_tokens_with, total_tokens_without):>10s}")
        print(f"{'Avg first-plan tools':<30s} {avg_first_plan_with:>12.1f} {avg_first_plan_without:>12.1f} {_pct_delta(avg_first_plan_with, avg_first_plan_without):>10s}")
        print(f"{'Avg iterations':<30s} {avg_iter_with:>12.1f} {avg_iter_without:>12.1f} {_pct_delta(avg_iter_with, avg_iter_without):>10s}")
        print(f"{'Avg tool calls':<30s} {avg_tools_with:>12.1f} {avg_tools_without:>12.1f} {_pct_delta(avg_tools_with, avg_tools_without):>10s}")
        print(f"{'Critical steps (tool-only)':<30s} {strict_hit_with:>10d}/{total_steps_all} {strict_hit_without:>10d}/{total_steps_all} {strict_pct_with - strict_pct_without:>+9.1%}")
        print(f"{'─'*70}")

        # Per-task comparison
        print(f"\n  PER-TASK COMPARISON:")
        print(f"  {'#':<4s} {'Iter W/WO':<12s} {'Retries W/WO':<14s} {'Tokens W/WO':<22s} {'1st-plan W/WO':<14s}")
        iter_wins = iter_ties = iter_losses = 0
        retry_wins = retry_ties = retry_losses = 0
        for i, r in enumerate(results, 1):
            w, wo = r["with"], r["without"]
            iw, iwo = w["iterations"], wo["iterations"]
            rw, rwo = w["error_retries"], wo["error_retries"]
            tw, two = w["total_tokens"], wo["total_tokens"]
            fw, fwo = w["first_plan_tools"], wo["first_plan_tools"]
            idiff = iw - iwo
            if idiff < 0:
                iter_wins += 1
            elif idiff > 0:
                iter_losses += 1
            else:
                iter_ties += 1
            rdiff = rw - rwo
            if rdiff < 0:
                retry_wins += 1
            elif rdiff > 0:
                retry_losses += 1
            else:
                retry_ties += 1
            print(f"  {i:<4d} {iw:>3d}/{iwo:<3d} ({idiff:+d})  {rw:>3d}/{rwo:<3d} ({rdiff:+d})    {tw:>8,}/{two:<8,}  {fw:>3d}/{fwo:<3d}")
        print(f"\n  Iteration Win/Tie/Loss:  {iter_wins}/{iter_ties}/{iter_losses}")
        print(f"  Retry Win/Tie/Loss:      {retry_wins}/{retry_ties}/{retry_losses}")
        print(f"{'='*70}")
