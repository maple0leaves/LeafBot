"""Skill Memory evaluation suite — measures the *effect improvement* of having
skill-memory vs not having it, with quantifiable metrics for each dimension.

Core question answered: "Does skill-memory make the agent better?"

Metrics:
  1. Step Coverage — skill-memory provides N% of ideal workflow steps (vs 0% without)
  2. Information Gain — skill-memory adds N actionable guidance tokens to the prompt
  3. Retrieval Quality — Precision@K, Recall@K, MRR across ground-truth queries
  4. Deduplication — classification accuracy on known duplicate/unique pairs
  5. Robustness — edge cases in storage and parsing
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from leafbot.agent.context import ContextBuilder
from leafbot.agent.memory import MemoryStore

# ════════════════════════════════════════════════
# SKILL CORPUS (8 diverse workflow patterns)
# ════════════════════════════════════════════════

SKILL_CORPUS = [
    {
        "task": "Set up Python web API with REST endpoints",
        "steps": ["Install framework", "Write routes", "Start server", "Verify endpoints"],
        "tools": ["exec", "write_file", "exec", "web_fetch"],
        "tags": ["python", "api", "web", "rest", "setup", "server"],
    },
    {
        "task": "Deploy Docker container to cloud",
        "steps": ["Write Dockerfile", "Build image", "Push to registry", "Deploy to cloud"],
        "tools": ["write_file", "exec", "exec", "exec"],
        "tags": ["docker", "deploy", "cloud", "container", "devops"],
    },
    {
        "task": "Scrape website data and save to CSV",
        "steps": ["Fetch page HTML", "Parse data with selectors", "Write CSV file"],
        "tools": ["web_fetch", "exec", "write_file"],
        "tags": ["scrape", "web", "csv", "data", "parse", "html"],
    },
    {
        "task": "Set up GitHub Actions CI pipeline",
        "steps": ["Create workflow YAML", "Configure test step", "Add deploy step", "Push and verify"],
        "tools": ["write_file", "exec", "exec", "web_fetch"],
        "tags": ["github", "actions", "ci", "pipeline", "test", "deploy"],
    },
    {
        "task": "Create SQLite database with schema and seed data",
        "steps": ["Create DB file", "Define schema", "Insert seed data", "Query to verify"],
        "tools": ["exec", "exec", "exec", "exec"],
        "tags": ["sqlite", "database", "schema", "sql", "seed", "data"],
    },
    {
        "task": "Monitor server logs and send alerts",
        "steps": ["Tail log file", "Filter error patterns", "Send notification"],
        "tools": ["exec", "exec", "exec"],
        "tags": ["monitor", "logs", "alert", "server", "error", "notification"],
    },
    {
        "task": "Generate PDF report from data",
        "steps": ["Read data source", "Format content", "Render PDF", "Save file"],
        "tools": ["read_file", "exec", "exec", "write_file"],
        "tags": ["pdf", "report", "generate", "data", "format"],
    },
    {
        "task": "Set up Python virtual environment and install deps",
        "steps": ["Create venv", "Activate venv", "Install requirements", "Verify installation"],
        "tools": ["exec", "exec", "exec", "exec"],
        "tags": ["python", "venv", "virtualenv", "install", "dependencies", "setup"],
    },
]

# ════════════════════════════════════════════════
# GROUND TRUTH: 56 queries across 10 categories
# Each entry: (query, expected_skill_task_substrings, ideal_workflow_keywords)
#
# ideal_workflow_keywords: the key steps a good response SHOULD include.
# If skill-memory covers these, it proves the agent gets better guidance.
# ════════════════════════════════════════════════

RETRIEVAL_GROUND_TRUTH: list[tuple[str, list[str], list[str]]] = [
    # ── Web API / REST (8 queries) ──
    ("create a FastAPI web project", ["Python web API"], ["install", "routes", "server", "verify"]),
    ("build a REST API server with Python", ["Python web API"], ["install", "routes", "server", "verify"]),
    ("set up Flask REST endpoints", ["Python web API"], ["install", "routes", "server"]),
    ("create Python HTTP API with endpoints", ["Python web API"], ["install", "routes", "server"]),
    ("build web server with REST routes in Python", ["Python web API"], ["install", "routes", "server"]),
    ("set up API backend with Python", ["Python web API"], ["install", "routes", "server"]),
    ("create a web API project from scratch", ["Python web API"], ["install", "routes", "server"]),
    ("build REST service with Python framework", ["Python web API"], ["install", "routes", "server"]),
    # ── Docker / Deploy (7 queries) ──
    ("deploy my app with Docker", ["Docker container"], ["dockerfile", "build", "push", "deploy"]),
    ("containerize and push to cloud", ["Docker container"], ["dockerfile", "build", "push"]),
    ("create Dockerfile and deploy to server", ["Docker container"], ["dockerfile", "build", "deploy"]),
    ("build Docker image and push to registry", ["Docker container"], ["build", "push", "registry"]),
    ("deploy container to production", ["Docker container"], ["build", "push", "deploy"]),
    ("dockerize my application", ["Docker container"], ["dockerfile", "build"]),
    ("container deployment to cloud infrastructure", ["Docker container"], ["build", "deploy", "cloud"]),
    # ── Scraping (6 queries) ──
    ("scrape product prices from a website", ["Scrape website"], ["fetch", "parse", "csv"]),
    ("fetch HTML and extract data to CSV", ["Scrape website"], ["fetch", "parse", "csv"]),
    ("crawl web page and save data", ["Scrape website"], ["fetch", "parse"]),
    ("extract table data from a web page", ["Scrape website"], ["fetch", "parse"]),
    ("scrape and download website content", ["Scrape website"], ["fetch", "parse"]),
    ("collect data from web pages into CSV", ["Scrape website"], ["fetch", "csv"]),
    # ── CI/CD (6 queries) ──
    ("set up CI/CD with GitHub Actions", ["GitHub Actions"], ["workflow", "test", "deploy"]),
    ("create a CI pipeline for testing", ["GitHub Actions"], ["workflow", "test"]),
    ("automate tests with GitHub Actions", ["GitHub Actions"], ["workflow", "test"]),
    ("create GitHub workflow for deploy", ["GitHub Actions"], ["workflow", "deploy"]),
    ("set up automated testing pipeline", ["GitHub Actions"], ["workflow", "test"]),
    ("configure CI pipeline with GitHub", ["GitHub Actions"], ["workflow", "test"]),
    # ── Database (6 queries) ──
    ("create a SQLite database with tables", ["SQLite database"], ["schema", "seed", "verify"]),
    ("insert seed data into SQL database", ["SQLite database"], ["schema", "seed"]),
    ("set up database schema and populate data", ["SQLite database"], ["schema", "seed"]),
    ("create SQL tables and insert test data", ["SQLite database"], ["schema", "seed"]),
    ("initialize database with schema", ["SQLite database"], ["schema"]),
    ("build SQLite DB with sample data", ["SQLite database"], ["schema", "seed"]),
    # ── Monitoring (5 queries) ──
    ("monitor error logs and alert me", ["Monitor server logs"], ["log", "filter", "notification"]),
    ("watch server logs for errors", ["Monitor server logs"], ["log", "filter"]),
    ("set up log monitoring with alerts", ["Monitor server logs"], ["log", "filter", "notification"]),
    ("track error patterns in server logs", ["Monitor server logs"], ["log", "filter"]),
    ("alert when server errors occur", ["Monitor server logs"], ["error", "notification"]),
    # ── PDF (5 queries) ──
    ("generate a PDF report from CSV", ["PDF report"], ["read", "format", "render"]),
    ("create a report document from data", ["PDF report"], ["read", "format"]),
    ("export data to PDF format", ["PDF report"], ["read", "render"]),
    ("build PDF document from dataset", ["PDF report"], ["read", "format", "render"]),
    ("produce a formatted PDF report", ["PDF report"], ["format", "render"]),
    # ── Venv (5 queries) ──
    ("set up Python venv and install packages", ["virtual environment"], ["venv", "install", "verify"]),
    ("install dependencies in a virtualenv", ["virtual environment"], ["venv", "install"]),
    ("create Python virtual environment", ["virtual environment"], ["venv"]),
    ("set up isolated Python env with deps", ["virtual environment"], ["venv", "install"]),
    ("initialize venv and install requirements", ["virtual environment"], ["venv", "install", "requirements"]),
    # ── Negative queries (8 queries, no match expected) ──
    ("help me with my homework", [], []),
    ("what time is it", [], []),
    ("tell me a joke", [], []),
    ("how are you today", [], []),
    ("translate this to French", [], []),
    ("recommend a good book", [], []),
    ("what is the capital of France", [], []),
    ("calculate 42 times 7", [], []),
]

# ════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════


def _populate_skills(store: MemoryStore) -> None:
    for skill in SKILL_CORPUS:
        with open(store.skills_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(skill, ensure_ascii=False) + "\n")


def _skill_matches(retrieved: list[dict], expected_substrings: list[str]) -> int:
    hits = 0
    for expected in expected_substrings:
        for skill in retrieved:
            if expected.lower() in skill.get("task", "").lower():
                hits += 1
                break
    return hits


def _step_coverage(retrieved: list[dict], ideal_keywords: list[str]) -> float:
    """What fraction of ideal workflow keywords are covered by retrieved skill steps?"""
    if not ideal_keywords:
        return 0.0
    all_step_text = " ".join(
        step.lower() for skill in retrieved for step in skill.get("steps", [])
    )
    covered = sum(1 for kw in ideal_keywords if kw.lower() in all_step_text)
    return covered / len(ideal_keywords)


# ════════════════════════════════════════════════
# 1. CORE: Effect Improvement — Step Coverage A/B
#    "With skill-memory, the agent gets N% of ideal
#     workflow guidance. Without it, it gets 0%."
# ════════════════════════════════════════════════


class TestEffectImprovement:
    """The central test: does skill-memory actually provide useful guidance
    that wouldn't exist without it?"""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> MemoryStore:
        s = MemoryStore(tmp_path)
        _populate_skills(s)
        return s

    @pytest.fixture()
    def empty_store(self, tmp_path: Path) -> MemoryStore:
        return MemoryStore(tmp_path)

    def test_step_coverage_with_vs_without(self, store: MemoryStore, tmp_path: Path) -> None:
        """A/B comparison: step coverage WITH skill-memory vs WITHOUT."""
        empty_store = MemoryStore(tmp_path / "empty_workspace")

        positive_queries = [(q, exp, ideal) for q, exp, ideal in RETRIEVAL_GROUND_TRUTH if ideal]

        coverage_with: list[float] = []
        coverage_without: list[float] = []

        for query, _, ideal_keywords in positive_queries:
            skills_found = store.find_relevant_skills(query, top_k=3)
            cov = _step_coverage(skills_found, ideal_keywords)
            coverage_with.append(cov)

            skills_empty = empty_store.find_relevant_skills(query, top_k=3)
            cov_empty = _step_coverage(skills_empty, ideal_keywords)
            coverage_without.append(cov_empty)

        avg_with = sum(coverage_with) / len(coverage_with)
        avg_without = sum(coverage_without) / len(coverage_without)

        print(f"\n{'='*60}")
        print(f"EFFECT IMPROVEMENT: Step Coverage A/B")
        print(f"  Positive queries evaluated: {len(positive_queries)}")
        print(f"  Avg step coverage WITH skill-memory:    {avg_with:.1%}")
        print(f"  Avg step coverage WITHOUT skill-memory: {avg_without:.1%}")
        print(f"  Absolute improvement: +{avg_with - avg_without:.1%}")
        print(f"{'='*60}")

        assert avg_without == 0.0, "Without skills, coverage should be 0%"
        assert avg_with >= 0.5, f"With skills, coverage should be ≥50%, got {avg_with:.1%}"

    def test_prompt_information_gain(self, tmp_path: Path) -> None:
        """Measure how much actionable information skill-memory adds to the prompt."""
        workspace_with = tmp_path / "with_skills"
        workspace_without = tmp_path / "without_skills"
        workspace_with.mkdir()
        workspace_without.mkdir()

        _populate_skills(MemoryStore(workspace_with))

        builder_with = ContextBuilder(workspace_with)
        builder_without = ContextBuilder(workspace_without)

        positive_queries = [q for q, exp, ideal in RETRIEVAL_GROUND_TRUTH if ideal]
        deltas: list[int] = []
        skill_token_counts: list[int] = []

        for query in positive_queries:
            prompt_with = builder_with.build_system_prompt(current_message=query)
            prompt_without = builder_without.build_system_prompt(current_message=query)
            deltas.append(len(prompt_with) - len(prompt_without))

            # Count actionable tokens in the injected skills section
            match = re.search(
                r"Reusable workflow patterns from past tasks:\n\n(.+)",
                prompt_with,
                re.DOTALL,
            )
            if match:
                skill_section = match.group(1)
                skill_token_counts.append(len(skill_section.split()))

        avg_delta = sum(deltas) / len(deltas) if deltas else 0
        avg_tokens = sum(skill_token_counts) / len(skill_token_counts) if skill_token_counts else 0
        queries_with_injection = sum(1 for d in deltas if d > 0)

        print(f"\n{'='*60}")
        print(f"EFFECT IMPROVEMENT: Prompt Information Gain")
        print(f"  Queries evaluated: {len(positive_queries)}")
        print(f"  Queries with skill injection: {queries_with_injection}/{len(positive_queries)}")
        print(f"  Avg prompt size delta: +{avg_delta:.0f} chars")
        print(f"  Avg actionable skill tokens: +{avg_tokens:.0f} tokens")
        print(f"{'='*60}")

        assert queries_with_injection >= len(positive_queries) * 0.8

    def test_per_category_coverage_breakdown(self, store: MemoryStore) -> None:
        """Break down step coverage by task category for detailed analysis."""
        categories: dict[str, list[float]] = {}

        for query, expected, ideal in RETRIEVAL_GROUND_TRUTH:
            if not expected:
                continue
            category = expected[0].split()[0]  # first word as category key
            skills = store.find_relevant_skills(query, top_k=3)
            cov = _step_coverage(skills, ideal)
            categories.setdefault(category, []).append(cov)

        print(f"\n{'='*60}")
        print(f"EFFECT IMPROVEMENT: Per-Category Step Coverage")
        total_queries = 0
        all_coverages: list[float] = []
        for cat, coverages in sorted(categories.items()):
            avg = sum(coverages) / len(coverages)
            total_queries += len(coverages)
            all_coverages.extend(coverages)
            print(f"  {cat:20s}: {avg:5.1%}  ({len(coverages)} queries)")
        overall = sum(all_coverages) / len(all_coverages) if all_coverages else 0
        print(f"  {'OVERALL':20s}: {overall:5.1%}  ({total_queries} queries)")
        print(f"{'='*60}")

        for cat, coverages in categories.items():
            avg = sum(coverages) / len(coverages)
            assert avg >= 0.3, f"Category '{cat}' coverage too low: {avg:.1%}"


# ════════════════════════════════════════════════
# 2. Retrieval Quality: Precision@K, Recall@K, MRR
# ════════════════════════════════════════════════


class TestRetrievalQuality:
    """Evaluate keyword-based skill retrieval against ground truth labels."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> MemoryStore:
        s = MemoryStore(tmp_path)
        _populate_skills(s)
        return s

    def test_precision_recall_at_3(self, store: MemoryStore) -> None:
        k = 3
        total_precision = 0.0
        total_recall = 0.0
        queries_with_expected = 0

        for query, expected, _ in RETRIEVAL_GROUND_TRUTH:
            if not expected:
                continue
            retrieved = store.find_relevant_skills(query, top_k=k)
            hits = _skill_matches(retrieved, expected)
            queries_with_expected += 1
            precision = hits / len(retrieved) if retrieved else 0.0
            recall = hits / len(expected)
            total_precision += precision
            total_recall += recall

        avg_precision = total_precision / queries_with_expected
        avg_recall = total_recall / queries_with_expected

        print(f"\n{'='*60}")
        print(f"Retrieval Quality (top_k={k}, {queries_with_expected} queries)")
        print(f"  Average Precision@{k}: {avg_precision:.1%}")
        print(f"  Average Recall@{k}:    {avg_recall:.1%}")
        print(f"{'='*60}")

        assert avg_precision >= 0.3
        assert avg_recall >= 0.9

    def test_mrr(self, store: MemoryStore) -> None:
        reciprocal_ranks: list[float] = []

        for query, expected, _ in RETRIEVAL_GROUND_TRUTH:
            if not expected:
                continue
            retrieved = store.find_relevant_skills(query, top_k=5)
            rr = 0.0
            for rank, skill in enumerate(retrieved, start=1):
                task = skill.get("task", "").lower()
                if any(e.lower() in task for e in expected):
                    rr = 1.0 / rank
                    break
            reciprocal_ranks.append(rr)

        mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0

        print(f"\n{'='*60}")
        print(f"Mean Reciprocal Rank ({len(reciprocal_ranks)} queries)")
        print(f"  MRR: {mrr:.3f}")
        print(f"{'='*60}")

        assert mrr >= 0.7

    def test_negative_queries_no_false_positives(self, store: MemoryStore) -> None:
        negative_queries = [q for q, exp, _ in RETRIEVAL_GROUND_TRUTH if not exp]
        false_positives = sum(
            1 for q in negative_queries if store.find_relevant_skills(q, top_k=3)
        )
        fp_rate = false_positives / len(negative_queries) if negative_queries else 0.0

        print(f"\n{'='*60}")
        print(f"Negative Query Filtering ({len(negative_queries)} queries)")
        print(f"  False positive rate: {fp_rate:.1%}")
        print(f"{'='*60}")

        assert fp_rate <= 0.3


# ════════════════════════════════════════════════
# 3. Deduplication Accuracy
# ════════════════════════════════════════════════

DEDUP_CASES: list[tuple[dict, bool]] = [
    # True duplicates
    ({"task": "Set up Python REST API with endpoints", "steps": ["Install", "Write", "Start"], "tags": ["python", "api", "web", "rest", "setup"]}, True),
    ({"task": "Deploy container to cloud infrastructure", "steps": ["Dockerfile", "Build", "Push"], "tags": ["docker", "deploy", "cloud", "container", "devops"]}, True),
    ({"task": "Scrape web page and export CSV", "steps": ["Fetch", "Parse"], "tags": ["scrape", "web", "csv", "data", "parse", "html"]}, True),
    ({"task": "Set up GitHub CI workflow", "steps": ["YAML", "Tests"], "tags": ["github", "actions", "ci", "pipeline", "test"]}, True),
    ({"task": "Create SQL database with seed", "steps": ["Schema", "Seed"], "tags": ["sqlite", "database", "schema", "sql", "seed", "data"]}, True),
    # Non-duplicates
    ({"task": "Train machine learning model", "steps": ["Prepare data", "Train", "Evaluate"], "tags": ["ml", "train", "model", "evaluate", "data"]}, False),
    ({"task": "Send email notifications", "steps": ["Configure SMTP", "Format message", "Send"], "tags": ["email", "smtp", "notification", "send"]}, False),
    ({"task": "Compress and upload backup", "steps": ["Tar files", "Upload to S3"], "tags": ["backup", "compress", "upload", "s3", "archive"]}, False),
    ({"task": "Resize and optimize images", "steps": ["Load image", "Resize", "Compress"], "tags": ["image", "resize", "optimize", "compress", "batch"]}, False),
    ({"task": "Parse JSON API and store results", "steps": ["Fetch API", "Parse JSON", "Store DB"], "tags": ["json", "api", "parse", "store", "fetch"]}, False),
    # Edge: partial overlap — below Jaccard 0.5 threshold
    ({"task": "Parse web page content", "steps": ["Fetch", "Parse"], "tags": ["web", "parse", "content", "beautifulsoup"]}, False),
    ({"task": "Python script automation", "steps": ["Write script", "Run"], "tags": ["python", "script", "automation", "run"]}, False),
]


class TestDeduplicationAccuracy:

    @pytest.fixture()
    def store(self, tmp_path: Path) -> MemoryStore:
        s = MemoryStore(tmp_path)
        _populate_skills(s)
        return s

    def test_dedup_classification(self, store: MemoryStore) -> None:
        tp = fn = tn = fp = 0

        for skill, expected_dup in DEDUP_CASES:
            actual = store._is_duplicate_skill(skill)
            if expected_dup:
                if actual: tp += 1
                else: fn += 1
            else:
                if actual: fp += 1
                else: tn += 1

        total = len(DEDUP_CASES)
        accuracy = (tp + tn) / total
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        print(f"\n{'='*60}")
        print(f"Deduplication Accuracy ({total} cases)")
        print(f"  TP={tp}  FN={fn}  TN={tn}  FP={fp}")
        print(f"  Accuracy:  {accuracy:.1%}")
        print(f"  Precision: {precision:.1%}")
        print(f"  Recall:    {recall:.1%}")
        print(f"  F1 Score:  {f1:.3f}")
        print(f"{'='*60}")

        assert accuracy >= 0.8
        assert f1 >= 0.8


# ════════════════════════════════════════════════
# 4. Storage Robustness
# ════════════════════════════════════════════════


class TestSkillStorageRobustness:

    def test_malformed_jsonl_lines_skipped(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        store.skills_file.parent.mkdir(parents=True, exist_ok=True)
        store.skills_file.write_text(
            '{"task":"valid","steps":["a"],"tags":["x"]}\n'
            "NOT VALID JSON\n"
            '{"task":"also valid","steps":["b"],"tags":["y"]}\n'
        )
        assert len(store.load_skills()) == 2

    def test_empty_skills_file(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        store.skills_file.parent.mkdir(parents=True, exist_ok=True)
        store.skills_file.write_text("")

        assert store.load_skills() == []
        assert store.find_relevant_skills("anything") == []
        assert store.get_skills_context("anything") == ""

    def test_skill_save_adds_timestamp(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        store.save_skill({"task": "Test task", "steps": ["step1"], "tags": ["test"]})
        assert "recorded" in store.load_skills()[0]

    def test_duplicate_skill_not_saved_twice(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        skill = {"task": "Test", "steps": ["a"], "tags": ["python", "api", "web", "rest"]}
        store.save_skill(skill)
        store.save_skill(skill)
        assert len(store.load_skills()) == 1

    def test_no_skills_file_returns_empty(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        assert store.load_skills() == []
        assert store.get_memory_context(query="test") == ""
