from __future__ import annotations

import argparse
import glob
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from rich.panel import Panel
from rich.table import Table

from .evaluator import RuleBasedEvaluator
from .ingest import (
    UNSUPPORTED_FORMAT_NOTES,
    DiscoveredSession,
    discover_sessions,
    session_to_task,
)
from .llm_reviewer import llm_review_agent_run
from .models import AgentRun
from .parser import AgentLogParser
from .reporter import ReportGenerator
from .utils import get_console, load_yaml_file, read_json, read_text, slugify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentops-lite",
        description="Analyze AI coding agent runs locally. Discovers Cursor, Claude Code, and Codex logs when you do not pass YAML.",
    )
    subparsers = parser.add_subparsers(dest="command")

    analyze = subparsers.add_parser("analyze", help="Analyze one agent run and generate reports.")
    analyze.add_argument("--agent", default=None, help="Agent name, e.g. Codex or Cursor.")
    analyze.add_argument("--model", default=None, help="Model name, e.g. gpt-5-codex.")
    analyze.add_argument("--task", default=None, help="Task YAML path. Optional when --log is a discovered session.")
    analyze.add_argument("--log", default=None, help="Agent log path. Optional when auto-ingesting.")
    analyze.add_argument("--diff", default=None, help="Diff path.")
    analyze.add_argument("--out", default="outputs/report", help="Output base path without extension.")
    analyze.add_argument("--run-id", default=None, help="Optional run identifier.")
    analyze.add_argument("--use-llm-reviewer", action="store_true", help="Optionally enhance qualitative fields.")
    analyze.set_defaults(func=_handle_analyze)

    compare = subparsers.add_parser("compare", help="Compare multiple JSON analysis outputs.")
    compare.add_argument("inputs", nargs="+", help="Analyze JSON files or glob patterns.")
    compare.add_argument("--out", required=True, help="Comparison HTML output path.")
    compare.set_defaults(func=_handle_compare)

    sample = subparsers.add_parser("sample", help="Run the built-in sample analysis.")
    sample.add_argument("--out", default="outputs/sample_report", help="Output base path.")
    sample.set_defaults(func=_handle_sample)

    ingest = subparsers.add_parser("ingest", help="Find local Cursor / Claude Code / Codex logs and analyze the latest one.")
    ingest.add_argument("--source", choices=["cursor", "claude", "codex", "all"], default="all")
    ingest.add_argument("--dir", dest="extra_dirs", action="append", default=[], help="Extra file or directory to scan.")
    ingest.add_argument("--list", action="store_true", help="List discovered sessions without writing a report.")
    ingest.add_argument("--out", default="outputs/latest_report", help="Output base path.")
    ingest.add_argument("--use-llm-reviewer", action="store_true")
    ingest.set_defaults(func=_handle_ingest)

    parser.set_defaults(func=_handle_default)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except FileNotFoundError as exc:
        get_console().print(f"[red]File not found:[/red] {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - friendly guard
        get_console().print(f"[red]Error:[/red] {exc}")
        return 1


def _handle_default(args) -> int:
    get_console().print("No command given; auto-ingesting the latest local agent log.")
    return _handle_ingest(
        argparse.Namespace(
            source="all",
            extra_dirs=[],
            list=False,
            out="outputs/latest_report",
            use_llm_reviewer=False,
        )
    )


def _handle_analyze(args) -> int:
    if not args.log and not args.task:
        return _handle_ingest(
            argparse.Namespace(
                source="all",
                extra_dirs=[],
                list=False,
                out=args.out,
                use_llm_reviewer=args.use_llm_reviewer,
            )
        )
    if not args.log:
        raise FileNotFoundError("Provide --log, or run `agentops-lite` / `agentops-lite ingest` to auto-discover sessions.")

    log_path = Path(args.log)
    log_text = read_text(log_path)
    notes: list[str] = []
    if log_path.suffix.lower() in {".jsonl", ".json"}:
        from .ingest import json_bytes_to_log

        converted, notes, meta = json_bytes_to_log(log_text, source=args.agent or "custom")
        if converted.strip():
            log_text = converted
        agent_name = args.agent or "custom"
        model_name = args.model or meta.get("model") or "unknown"
        task_name_hint = meta.get("title")
    else:
        agent_name = args.agent or "custom"
        model_name = args.model or "unknown"
        task_name_hint = None

    if args.task:
        task = load_yaml_file(args.task)
        task_path = Path(args.task)
    else:
        task = {
            "task_name": task_name_hint or log_path.stem,
            "task_type": "auto_ingested",
            "task_description": f"Analyzed log {log_path} without a task YAML file.",
        }
        task_path = log_path

    diff_path = Path(args.diff) if args.diff else None
    diff_text = read_text(diff_path) if diff_path else None
    output_base = Path(args.out)

    parser = AgentLogParser()
    events, metrics = parser.parse(log_text, diff_text)

    run = AgentRun(
        run_id=args.run_id or _build_run_id(agent_name, str(task.get("task_name", task_path.stem))),
        agent_name=agent_name,
        model_name=model_name,
        task_name=str(task.get("task_name", task_path.stem)),
        task_type=str(task.get("task_type", "unknown")),
        task_description=str(task.get("task_description", "")),
        log_path=str(log_path),
        diff_path=str(diff_path) if diff_path else None,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        raw_log=log_text,
        raw_diff=diff_text,
        events=events,
        metrics=metrics,
    )

    evaluator = RuleBasedEvaluator()
    run.evaluation = evaluator.evaluate(run)

    if args.use_llm_reviewer:
        reviewed = llm_review_agent_run(run, run.evaluation)
        if reviewed is None:
            get_console().print("[yellow]LLM reviewer unavailable, falling back to rule-based evaluation.[/yellow]")
        else:
            run.evaluation = reviewed

    reporter = ReportGenerator()
    paths = reporter.generate_all(run, output_base)
    _print_summary(run, paths["markdown"], paths["html"], Path(output_base).with_suffix(".json"))
    if notes:
        get_console().print("[yellow]Parse notes:[/yellow]")
        for note in notes[:12]:
            get_console().print(f"- {note}")
    return 0


def _handle_compare(args) -> int:
    inputs = _expand_inputs(args.inputs)
    if not inputs:
        raise FileNotFoundError("No JSON inputs matched the provided paths or globs.")
    runs = [AgentRun.from_dict(read_json(path)) for path in inputs]
    reporter = ReportGenerator()
    html_text = reporter.build_comparison_html(runs)
    out_path = Path(args.out)
    if out_path.suffix.lower() != ".html":
        out_path = out_path.with_suffix(".html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")
    _print_comparison_summary(runs, out_path)
    return 0


def _handle_sample(args) -> int:
    examples = _examples_dir()
    task = examples / "tasks" / "bugfix_login.yaml"
    log = examples / "logs" / "codex_bugfix_login.txt"
    diff = examples / "diffs" / "codex_bugfix_login.diff"
    if not task.exists() or not log.exists():
        raise FileNotFoundError(f"Bundled sample files were not found under {examples}")
    return _handle_analyze(
        argparse.Namespace(
            agent="Codex",
            model="gpt-5-codex",
            task=str(task),
            log=str(log),
            diff=str(diff),
            out=str(args.out),
            run_id=None,
            use_llm_reviewer=False,
        )
    )


def _handle_ingest(args) -> int:
    sources = None if args.source == "all" else [args.source]
    roots = {"cursor": [], "claude": [], "codex": []} if args.extra_dirs else None
    sessions = discover_sessions(sources=sources, extra_dirs=args.extra_dirs, roots=roots)
    usable = [item for item in sessions if item.status == "ok" and item.log_text.strip()]
    skipped = [item for item in sessions if item.status != "ok"]

    console = get_console()
    if args.list or not usable:
        _print_ingest_table(sessions)
        if skipped:
            console.print("[yellow]Some files were found but not parsed:[/yellow]")
            for item in skipped[:12]:
                note = item.notes[0] if item.notes else item.status
                console.print(f"- {item.path}: {note}")
        if not usable:
            console.print("[yellow]No parseable agent logs were found in common local paths.[/yellow]")
            console.print("Pass a log explicitly: agentops-lite analyze --agent Codex --model unknown --task TASK.yaml --log LOG.txt")
            console.print("Unsupported formats:")
            for note in UNSUPPORTED_FORMAT_NOTES:
                console.print(f"- {note}")
            return 0 if args.list else 1
        if args.list:
            return 0

    session = usable[0]
    return _analyze_session(session, Path(args.out), use_llm_reviewer=args.use_llm_reviewer)


def _analyze_session(session: DiscoveredSession, output_base: Path, use_llm_reviewer: bool = False) -> int:
    task = session_to_task(session)
    parser = AgentLogParser()
    events, metrics = parser.parse(session.log_text, None)
    agent_name = session.source.title() if session.source != "claude" else "Claude Code"
    model_name = session.model_name or "unknown"
    run = AgentRun(
        run_id=_build_run_id(agent_name, task["task_name"]),
        agent_name=agent_name,
        model_name=model_name,
        task_name=task["task_name"],
        task_type=task["task_type"],
        task_description=task["task_description"],
        log_path=str(session.path),
        started_at=datetime.fromtimestamp(session.mtime, tz=timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        raw_log=session.log_text,
        events=events,
        metrics=metrics,
    )
    run.evaluation = RuleBasedEvaluator().evaluate(run)
    if use_llm_reviewer:
        reviewed = llm_review_agent_run(run, run.evaluation)
        if reviewed is not None:
            run.evaluation = reviewed
    paths = ReportGenerator().generate_all(run, output_base)
    _print_summary(run, paths["markdown"], paths["html"], Path(output_base).with_suffix(".json"))
    if session.notes:
        get_console().print("[yellow]Parse notes:[/yellow]")
        for note in session.notes[:12]:
            get_console().print(f"- {note}")
    return 0


def _print_ingest_table(sessions: list[DiscoveredSession]) -> None:
    console = get_console()
    table = Table(title="Discovered local agent sessions")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Modified")
    table.add_column("Path")
    if not sessions:
        console.print("No candidate files found.")
        return
    for item in sessions[:30]:
        table.add_row(item.source, item.status, item.modified_iso, str(item.path))
    console.print(table)


def _examples_dir() -> Path:
    here = Path(__file__).resolve().parent
    bundled = here / "data"
    if (bundled / "tasks" / "bugfix_login.yaml").exists():
        return bundled
    return here.parent / "examples"


def _expand_inputs(inputs: Iterable[str]) -> list[Path]:
    results: list[Path] = []
    for item in inputs:
        matches = [Path(path) for path in glob.glob(item)]
        if matches:
            results.extend(matches)
            continue
        path = Path(item)
        if path.exists():
            results.append(path)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in results:
        normalized = str(path.resolve())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(path)
    return unique


def _print_summary(run: AgentRun, markdown_path: Path, html_path: Path, json_path: Path) -> None:
    console = get_console()
    score_table = Table()
    score_table.add_column("Metric", style="cyan", no_wrap=True)
    score_table.add_column("Value", style="white")
    score_table.add_row("Completion", f"{run.evaluation.completion_score}/100")
    score_table.add_row("Code quality", f"{run.evaluation.code_quality_score}/100")
    score_table.add_row("Reliability", f"{run.evaluation.reliability_score}/100")
    score_table.add_row("Cost efficiency", f"{run.evaluation.cost_efficiency_score}/100")
    score_table.add_row("Overall", f"{run.evaluation.overall_score}/100")

    artifact_table = Table()
    artifact_table.add_column("Artifact", style="cyan", no_wrap=True)
    artifact_table.add_column("Path", style="white")
    artifact_table.add_row("Markdown", str(markdown_path))
    artifact_table.add_row("HTML", str(html_path))
    artifact_table.add_row("JSON", str(json_path))

    console.print(
        Panel(
            f"[bold]{run.agent_name}[/bold] | {run.model_name}\n"
            f"Run ID: {run.run_id}\n"
            f"Task: {run.task_name} ({run.task_type})\n"
            f"Overall score: [bold]{run.evaluation.overall_score}/100[/bold]",
            title="AgentOps Lite",
            border_style="cyan",
        )
    )
    console.print(score_table)
    console.print(artifact_table)
    console.print(f"[green]Report files written successfully.[/green] Open {html_path} to review the HTML report.")


def _print_comparison_summary(runs: list[AgentRun], out_path: Path) -> None:
    console = get_console()
    sorted_runs = sorted(runs, key=lambda run: run.evaluation.overall_score, reverse=True)
    winner = sorted_runs[0]
    table = Table(title="Comparison Summary")
    table.add_column("Rank", style="cyan", no_wrap=True)
    table.add_column("Agent", style="white")
    table.add_column("Model", style="white")
    table.add_column("Overall", style="green", justify="right")
    table.add_column("Completion", justify="right")
    table.add_column("Reliability", justify="right")
    for index, run in enumerate(sorted_runs, start=1):
        table.add_row(
            str(index),
            run.agent_name,
            run.model_name,
            f"{run.evaluation.overall_score}",
            f"{run.evaluation.completion_score}",
            f"{run.evaluation.reliability_score}",
        )
    console.print(
        Panel(
            f"Winner: [bold]{winner.agent_name}[/bold] / {winner.model_name}\n"
            f"Overall score: [bold]{winner.evaluation.overall_score}/100[/bold]\n"
            f"Report: {out_path}",
            title="Comparison Complete",
            border_style="green",
        )
    )
    console.print(table)


def _build_run_id(agent: str, task_name: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{slugify(agent)}-{slugify(task_name)}-{timestamp}"
