from __future__ import annotations

import argparse
import glob
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from rich.panel import Panel
from rich.table import Table

from .evaluator import RuleBasedEvaluator
from .llm_reviewer import llm_review_agent_run
from .models import AgentRun
from .parser import AgentLogParser
from .reporter import ReportGenerator
from .utils import get_console, load_yaml_file, read_json, read_text, slugify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="AgentOps Lite", description="Analyze AI coding agent runs locally.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze one agent run and generate reports.")
    analyze.add_argument("--agent", required=True, help="Agent name, e.g. Codex or Cursor.")
    analyze.add_argument("--model", required=True, help="Model name, e.g. gpt-5-codex.")
    analyze.add_argument("--task", required=True, help="Task YAML path.")
    analyze.add_argument("--log", required=True, help="Agent log path.")
    analyze.add_argument("--diff", default=None, help="Diff path.")
    analyze.add_argument("--out", required=True, help="Output base path without extension.")
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


def _handle_analyze(args) -> int:
    task_path = Path(args.task)
    log_path = Path(args.log)
    diff_path = Path(args.diff) if args.diff else None
    output_base = Path(args.out)

    task = load_yaml_file(task_path)
    log_text = read_text(log_path)
    diff_text = read_text(diff_path) if diff_path else None

    parser = AgentLogParser()
    events, metrics = parser.parse(log_text, diff_text)

    run = AgentRun(
        run_id=args.run_id or _build_run_id(args.agent, task.get("task_name", task_path.stem)),
        agent_name=args.agent,
        model_name=args.model,
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
    root = Path(__file__).resolve().parent.parent
    task = root / "examples" / "tasks" / "bugfix_login.yaml"
    log = root / "examples" / "logs" / "codex_bugfix_login.txt"
    diff = root / "examples" / "diffs" / "codex_bugfix_login.diff"
    output_base = Path(args.out)
    result = _handle_analyze(
        argparse.Namespace(
            agent="Codex",
            model="gpt-5-codex",
            task=str(task),
            log=str(log),
            diff=str(diff),
            out=str(output_base),
            run_id=None,
            use_llm_reviewer=False,
        )
    )
    if result == 0:
        get_console().print(f"Open {Path(output_base).with_suffix('.html')} to view the report")
    return result


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
