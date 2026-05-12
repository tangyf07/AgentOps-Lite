from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import AgentEvaluation, AgentEvent, AgentRun
from .utils import ensure_parent, read_text, render_html_template, render_template, write_text


class ReportGenerator:
    def __init__(self, template_dir: Path | None = None):
        self.template_dir = template_dir or Path(__file__).resolve().parent.parent / "templates"

    def generate_markdown(self, run: AgentRun, output_base: Path | str) -> Path:
        output_base = self._normalize_output_base(output_base)
        template_text = read_text(self.template_dir / "report.md.j2")
        return write_text(output_base.with_suffix(".md"), render_template(template_text, self._build_context(run)))

    def generate_html(self, run: AgentRun, output_base: Path | str) -> Path:
        output_base = self._normalize_output_base(output_base)
        template_text = read_text(self.template_dir / "report.html.j2")
        return write_text(output_base.with_suffix(".html"), render_html_template(template_text, self._build_context(run)))

    def generate_json(self, run: AgentRun, output_base: Path | str) -> Path:
        output_base = self._normalize_output_base(output_base)
        return write_text(output_base.with_suffix(".json"), run.model_dump_json())

    def generate_all(self, run: AgentRun, output_base: Path | str) -> dict[str, Path]:
        output_base = self._normalize_output_base(output_base)
        return {
            "markdown": self.generate_markdown(run, output_base),
            "html": self.generate_html(run, output_base),
            "json": self.generate_json(run, output_base),
        }

    def build_comparison_html(self, runs: list[AgentRun]) -> str:
        if not runs:
            return "<!doctype html><html><body><h1>No runs provided</h1></body></html>"
        runs = sorted(
            runs,
            key=lambda run: (
                -run.evaluation.overall_score,
                -run.evaluation.completion_score,
                -run.evaluation.reliability_score,
                run.run_id.lower(),
            ),
        )
        best_score = runs[0].evaluation.overall_score
        average_overall = round(sum(run.evaluation.overall_score for run in runs) / len(runs))
        average_reliability = round(sum(run.evaluation.reliability_score for run in runs) / len(runs))
        average_completion = round(sum(run.evaluation.completion_score for run in runs) / len(runs))
        average_quality = round(sum(run.evaluation.code_quality_score for run in runs) / len(runs))
        best_run = runs[0]
        lowest_run = runs[-1]
        best_completion = max(runs, key=lambda run: run.evaluation.completion_score)
        best_reliability = max(runs, key=lambda run: run.evaluation.reliability_score)
        best_efficiency = max(runs, key=lambda run: run.evaluation.cost_efficiency_score)
        rows = []
        for rank, run in enumerate(runs, start=1):
            row_class = "best" if run is best_run else ""
            grade, grade_label, grade_class = self._score_grade(run.evaluation.overall_score)
            delta = best_score - run.evaluation.overall_score
            rows.append(
                f"<tr class='{row_class}'>"
                f"<td>{rank}</td>"
                f"<td>{html.escape(run.agent_name)}</td>"
                f"<td>{html.escape(run.model_name)}</td>"
                f"<td>{html.escape(run.task_name)}</td>"
                f"<td><span class='tag {grade_class}'>Grade {grade}</span> {grade_label}</td>"
                f"<td>{run.evaluation.overall_score}</td>"
                f"<td>{run.evaluation.completion_score}</td>"
                f"<td>{run.evaluation.reliability_score}</td>"
                f"<td>{run.evaluation.cost_efficiency_score}</td>"
                f"<td><span class='delta'>{delta}</span></td>"
                f"<td><div class='bar'><span style='width:{run.evaluation.overall_score}%'></span></div></td>"
                "</tr>"
            )
        rows_html = "".join(rows)
        summary_cards = "".join(
            [
                f"<div class='mini-card'><span>Runs</span><strong>{len(runs)}</strong></div>",
                f"<div class='mini-card'><span>Average overall</span><strong>{average_overall}</strong></div>",
                f"<div class='mini-card'><span>Average reliability</span><strong>{average_reliability}</strong></div>",
                f"<div class='mini-card'><span>Best run</span><strong>{html.escape(best_run.agent_name)}</strong></div>",
            ]
        )
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentOps Lite Comparison</title>
  <style>
    :root {{ --bg:#f7f8fb; --ink:#1f2328; --muted:#687076; --line:#d9e1ec; --card:#fff; --accent:#2c5f9e; --good:#237a4b; --warn:#99670f; --bad:#b73a3a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter,Segoe UI,Arial,sans-serif; background:var(--bg); color:var(--ink); line-height:1.5; }}
    .wrap {{ max-width:1320px; margin:0 auto; padding:32px 24px 56px; }}
    .hero {{ display:grid; grid-template-columns:1fr auto; gap:24px; align-items:end; padding-bottom:20px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0; font-size:34px; letter-spacing:0; }}
    .sub {{ color:var(--muted); margin-top:8px; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:18px; }}
    .mini-card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }}
    .mini-card span {{ display:block; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
    .mini-card strong {{ display:block; margin-top:6px; font-size:28px; }}
    .score-pill {{ display:inline-flex; align-items:center; gap:8px; padding:8px 12px; border-radius:999px; background:#111; color:#fff; font-weight:700; }}
    .score-pill .tag {{ margin:0; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); box-shadow:0 8px 28px rgba(0,0,0,.06); border-radius:8px; overflow:hidden; }}
    th, td {{ text-align:left; padding:12px 14px; border-bottom:1px solid var(--line); vertical-align:middle; }}
    th {{ background:#eef2f7; color:#454545; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
    tr.best {{ background:#edf7ec; font-weight:700; }}
    .tag {{ display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:2px 8px; font-size:12px; font-weight:700; color:#fff; background:#687076; white-space:nowrap; }}
    .grade-a {{ background:var(--good); }}
    .grade-b {{ background:#3d7f5e; }}
    .grade-c {{ background:var(--accent); }}
    .grade-d {{ background:var(--warn); }}
    .grade-e {{ background:var(--bad); }}
    .delta {{ display:inline-flex; min-width:34px; justify-content:center; padding:2px 8px; border-radius:999px; background:#eef3f8; color:#344054; font-weight:700; }}
    .bar {{ width:100%; height:8px; background:#e7edf5; border-radius:999px; overflow:hidden; }}
    .bar span {{ display:block; height:100%; background:linear-gradient(90deg,#2c5f9e,#4f8dd8); border-radius:inherit; }}
    .note {{ margin-top:14px; color:var(--muted); }}
    .table-wrap {{ margin-top:18px; overflow:auto; border-radius:8px; }}
    @media (max-width: 980px) {{ .hero, .summary {{ grid-template-columns:1fr 1fr; }} }}
    @media (max-width: 640px) {{ .hero, .summary {{ grid-template-columns:1fr; }} h1 {{ font-size:28px; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div>
        <h1>AgentOps Lite Comparison</h1>
        <div class="sub">Sorted by overall score, with the strongest run highlighted at the top.</div>
      </div>
      <div class="score-pill"><span class="tag grade-a">Best</span> {best_score}</div>
    </section>
    <section class="summary">{summary_cards}</section>
    <section class="summary">
      <div class="mini-card"><span>Best completion</span><strong>{best_completion.evaluation.completion_score}</strong><small>{html.escape(best_completion.agent_name)} / {html.escape(best_completion.model_name)}</small></div>
      <div class="mini-card"><span>Best reliability</span><strong>{best_reliability.evaluation.reliability_score}</strong><small>{html.escape(best_reliability.agent_name)} / {html.escape(best_reliability.model_name)}</small></div>
      <div class="mini-card"><span>Best efficiency</span><strong>{best_efficiency.evaluation.cost_efficiency_score}</strong><small>{html.escape(best_efficiency.agent_name)} / {html.escape(best_efficiency.model_name)}</small></div>
      <div class="mini-card"><span>Average completion</span><strong>{average_completion}</strong><small>Across all compared runs</small></div>
    </section>
    <section class="summary">
      <div class="mini-card"><span>Average quality</span><strong>{average_quality}</strong><small>Code quality signal across runs</small></div>
      <div class="mini-card"><span>Average overall</span><strong>{average_overall}</strong><small>Overall score average</small></div>
      <div class="mini-card"><span>Average reliability</span><strong>{average_reliability}</strong><small>Reliability signal average</small></div>
      <div class="mini-card"><span>Winner</span><strong>{html.escape(best_run.agent_name)}</strong><small>{html.escape(best_run.model_name)}</small></div>
    </section>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Agent</th>
            <th>Model</th>
            <th>Task</th>
            <th>Band</th>
            <th>Overall</th>
            <th>Completion</th>
            <th>Reliability</th>
            <th>Cost Efficiency</th>
            <th>Delta</th>
            <th>Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
    <div class="note">Best run: {html.escape(best_run.run_id)} | Lowest run: {html.escape(lowest_run.run_id)} | Generated at {datetime.now(timezone.utc).isoformat()}</div>
  </div>
</body>
</html>"""

    def _normalize_output_base(self, output_base: Path | str) -> Path:
        path = Path(output_base)
        if path.suffix.lower() in {".md", ".html", ".json"}:
            path = path.with_suffix("")
        ensure_parent(path.with_suffix(".md"))
        return path

    def _build_context(self, run: AgentRun) -> dict[str, str]:
        evaluation = run.evaluation
        metrics = run.metrics
        grade, grade_label, grade_class = self._score_grade(evaluation.overall_score)
        risk_flags = self._risk_flags(run)
        next_action = self._next_action(run)
        lists_md = self._markdown_lists(
            {
                "strengths": evaluation.strengths,
                "weaknesses": evaluation.weaknesses,
                "failure_reasons": evaluation.failure_reasons,
                "improvement_suggestions": evaluation.improvement_suggestions,
            }
        )
        conclusion = self._build_conclusion(run)
        return {
            "title": "AgentOps Lite Report",
            "run_id": run.run_id,
            "agent_name": run.agent_name,
            "model_name": run.model_name,
            "task_name": run.task_name,
            "task_type": run.task_type,
            "task_description": run.task_description,
            "log_path": run.log_path or "",
            "diff_path": run.diff_path or "",
            "started_at": run.started_at or "",
            "finished_at": run.finished_at or "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_score": str(evaluation.overall_score),
            "score_grade": grade,
            "score_label": grade_label,
            "score_class": grade_class,
            "status_phrase": self._status_phrase(evaluation.overall_score),
            "score_rows_md": self._markdown_score_rows(evaluation),
            "metrics_table_md": self._markdown_metrics_table(metrics),
            "metric_highlights_md": self._markdown_metric_highlights(metrics),
            "timeline_md": self._markdown_timeline(run.events),
            "errors_md": self._markdown_errors_and_retries(run.events),
            "executive_summary_md": self._markdown_executive_summary(run, grade, grade_label, risk_flags, next_action),
            "artifact_md": self._markdown_artifacts(run),
            "risk_flags_md": self._markdown_risk_flags(risk_flags),
            "next_action_md": next_action,
            "strengths_md": lists_md["strengths"],
            "weaknesses_md": lists_md["weaknesses"],
            "failure_reasons_md": lists_md["failure_reasons"],
            "improvement_suggestions_md": lists_md["improvement_suggestions"],
            "conclusion": conclusion,
            "score_cards_html": self._html_score_cards(evaluation),
            "metric_cards_html": self._html_metric_cards(metrics),
            "artifact_html": self._html_artifacts(run),
            "risk_flags_html": self._html_risk_flags(risk_flags),
            "next_action_html": self._html_next_action(next_action),
            "summary_badges_html": self._html_summary_badges(evaluation, metrics),
            "metrics_table_html": self._html_metrics_table(metrics),
            "timeline_html": self._html_timeline(run.events),
            "errors_html": self._html_errors_and_retries(run.events),
            "strengths_html": self._html_list(evaluation.strengths),
            "weaknesses_html": self._html_list(evaluation.weaknesses),
            "failure_reasons_html": self._html_list(evaluation.failure_reasons),
            "improvement_suggestions_html": self._html_list(evaluation.improvement_suggestions),
            "conclusion_html": f"<p>{html.escape(conclusion)}</p>",
        }

    def _markdown_score_rows(self, evaluation: AgentEvaluation) -> str:
        return "\n".join(
            [
                "| Metric | Score |",
                "| --- | ---: |",
                f"| Overall | {evaluation.overall_score} |",
                f"| Completion | {evaluation.completion_score} |",
                f"| Code Quality | {evaluation.code_quality_score} |",
                f"| Reliability | {evaluation.reliability_score} |",
                f"| Cost Efficiency | {evaluation.cost_efficiency_score} |",
            ]
        )

    def _markdown_metrics_table(self, metrics) -> str:
        rows = ["| Metric | Value |", "| --- | ---: |"]
        for label, value in self._metric_rows(metrics):
            rows.append(f"| {label} | {value} |")
        return "\n".join(rows)

    def _markdown_metric_highlights(self, metrics) -> str:
        return "\n".join(
            [
                f"- Log lines: {metrics.total_log_lines}",
                f"- Events: {metrics.total_events}",
                f"- Files touched: {metrics.files_touched}",
                f"- Commands run: {metrics.commands_run}",
                f"- Errors found: {metrics.errors_found}",
                f"- Retries: {metrics.retries}",
            ]
        )

    def _markdown_timeline(self, events: list[AgentEvent]) -> str:
        rows = ["| Line | Event | Content |", "| ---: | --- | --- |"]
        for event in events:
            rows.append(f"| {event.line_number or ''} | {event.event_type} | {self._truncate_md(event.content)} |")
        return "\n".join(rows)

    def _markdown_errors_and_retries(self, events: list[AgentEvent]) -> str:
        filtered = [event for event in events if event.event_type in {"error", "retry", "test_run"}]
        if not filtered:
            return "- No explicit error or retry signals were detected."
        return "\n".join(f"- L{event.line_number or ''} [{event.event_type}] {event.content}" for event in filtered)

    def _markdown_lists(self, items: dict[str, list[str]]) -> dict[str, str]:
        return {key: "\n".join(f"- {item}" for item in values) if values else "- None" for key, values in items.items()}

    def _markdown_executive_summary(self, run: AgentRun, grade: str, grade_label: str, risk_flags: list[str], next_action: str) -> str:
        lines = [
            f"- Score band: {grade} ({grade_label})",
            f"- Status: {self._status_phrase(run.evaluation.overall_score)}",
            f"- Next best action: {next_action}",
            "- Risk flags:",
        ]
        if risk_flags:
            lines.extend(f"  - {flag}" for flag in risk_flags)
        else:
            lines.append("  - None")
        return "\n".join(lines)

    def _markdown_artifacts(self, run: AgentRun) -> str:
        return "\n".join(
            [
                f"- Log: {run.log_path or 'n/a'}",
                f"- Diff: {run.diff_path or 'n/a'}",
                f"- Started: {run.started_at or 'n/a'}",
                f"- Finished: {run.finished_at or 'n/a'}",
            ]
        )

    def _markdown_risk_flags(self, risk_flags: list[str]) -> str:
        return "\n".join(f"- {flag}" for flag in risk_flags) if risk_flags else "- None"

    def _build_conclusion(self, run: AgentRun) -> str:
        if run.evaluation.overall_score >= 85:
            return "This run shows strong execution quality and a clear finish."
        if run.evaluation.overall_score >= 70:
            return "This run is usable, but a few reliability and validation gaps remain."
        return "This run needs stronger validation, fewer retries, and a clearer completion path."

    def _truncate_md(self, value: str, limit: int = 120) -> str:
        value = value.replace("|", "\\|")
        return value if len(value) <= limit else value[: limit - 1] + "..."

    def _status_phrase(self, score: int) -> str:
        if score >= 90:
            return "Production-ready signal"
        if score >= 80:
            return "Strong run with minor gaps"
        if score >= 70:
            return "Usable run with verification gaps"
        if score >= 60:
            return "Fragile run that needs cleanup"
        return "High-risk run"

    def _score_grade(self, score: int) -> tuple[str, str, str]:
        if score >= 90:
            return "A", "Excellent", "grade-a"
        if score >= 80:
            return "B", "Strong", "grade-b"
        if score >= 70:
            return "C", "Usable", "grade-c"
        if score >= 60:
            return "D", "Fragile", "grade-d"
        return "E", "Needs work", "grade-e"

    def _risk_flags(self, run: AgentRun) -> list[str]:
        metrics = run.metrics
        flags: list[str] = []
        if not metrics.tests_detected:
            flags.append("No test run detected")
        if metrics.errors_found >= 3:
            flags.append(f"{metrics.errors_found} error signals detected")
        if metrics.retries >= 2:
            flags.append(f"{metrics.retries} retries recorded")
        if metrics.human_interventions:
            flags.append("Human intervention was required")
        if metrics.files_touched > 5:
            flags.append(f"Wide file surface ({metrics.files_touched} files)")
        if metrics.commands_run > 12:
            flags.append("Command churn is high")
        if not any(event.event_type == "final_answer" for event in run.events):
            flags.append("No explicit final summary")
        return flags[:6]

    def _next_action(self, run: AgentRun) -> str:
        metrics = run.metrics
        if not metrics.tests_detected:
            return "Add a minimal test command before the next edit."
        if metrics.errors_found:
            return "Reproduce the first failure cleanly and fix the root cause before retrying."
        if metrics.retries:
            return "Capture the failure reason before each retry and keep the diff smaller."
        if metrics.files_touched > 5:
            return "Trim the blast radius and keep the next pass focused on fewer files."
        return "Keep the workflow tight and preserve the current verification pattern."

    def _html_metric_cards(self, metrics) -> str:
        cards = [
            ("Log lines", metrics.total_log_lines),
            ("Events", metrics.total_events),
            ("Files", metrics.files_touched),
            ("Commands", metrics.commands_run),
            ("Errors", metrics.errors_found),
            ("Retries", metrics.retries),
        ]
        return "".join(
            f"<div class='metric-card'><div class='label'>{html.escape(label)}</div><div class='value'>{value}</div></div>"
            for label, value in cards
        )

    def _html_artifacts(self, run: AgentRun) -> str:
        return (
            "<dl class='artifacts'>"
            f"<div><dt>Log</dt><dd><code>{html.escape(run.log_path or 'n/a')}</code></dd></div>"
            f"<div><dt>Diff</dt><dd><code>{html.escape(run.diff_path or 'n/a')}</code></dd></div>"
            f"<div><dt>Started</dt><dd>{html.escape(run.started_at or 'n/a')}</dd></div>"
            f"<div><dt>Finished</dt><dd>{html.escape(run.finished_at or 'n/a')}</dd></div>"
            "</dl>"
        )

    def _html_risk_flags(self, risk_flags: list[str]) -> str:
        if not risk_flags:
            return "<p class='muted'>No obvious risk flags detected.</p>"
        items = "".join(f"<li>{html.escape(flag)}</li>" for flag in risk_flags)
        return f"<ul class='risk-list'>{items}</ul>"

    def _html_next_action(self, next_action: str) -> str:
        return f"<div class='callout'><strong>Next action</strong><p>{html.escape(next_action)}</p></div>"

    def _html_summary_badges(self, evaluation: AgentEvaluation, metrics) -> str:
        grade, label, grade_class = self._score_grade(evaluation.overall_score)
        badges = [
            f"<span class='tag {grade_class}'>Score {grade}</span>",
            f"<span class='tag grade-c'>{html.escape(label)}</span>",
            f"<span class='tag grade-b'>{html.escape(metrics.estimated_complexity.title())} complexity</span>",
            f"<span class='tag grade-d'>{html.escape(metrics.estimated_cost_level.title())} cost</span>",
        ]
        return "".join(badges)

    def _html_score_cards(self, evaluation: AgentEvaluation) -> str:
        cards = [
            ("Overall", evaluation.overall_score),
            ("Completion", evaluation.completion_score),
            ("Code Quality", evaluation.code_quality_score),
            ("Reliability", evaluation.reliability_score),
            ("Cost Efficiency", evaluation.cost_efficiency_score),
        ]
        return "".join(
            f"<div class='card'><div class='label'>{html.escape(label)}</div><div class='value'>{score}</div></div>"
            for label, score in cards
        )

    def _html_metrics_table(self, metrics) -> str:
        body = "".join(
            f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>"
            for label, value in self._metric_rows(metrics)
        )
        return f"<table class='table'><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{body}</tbody></table>"

    def _html_timeline(self, events: list[AgentEvent]) -> str:
        body = "".join(
            f"<tr><td>{event.line_number or ''}</td><td><span class='tag {html.escape(event.event_type)}'>{html.escape(event.event_type)}</span></td><td>{html.escape(event.content)}</td></tr>"
            for event in events
        )
        return f"<table class='table timeline'><thead><tr><th>Line</th><th>Event</th><th>Content</th></tr></thead><tbody>{body}</tbody></table>"

    def _html_errors_and_retries(self, events: list[AgentEvent]) -> str:
        filtered = [event for event in events if event.event_type in {"error", "retry", "test_run"}]
        if not filtered:
            return "<p>No explicit error or retry signals were detected.</p>"
        items = "".join(
            f"<li><span class='tag {html.escape(event.event_type)}'>{html.escape(event.event_type)}</span> "
            f"L{event.line_number or ''}: {html.escape(event.content)}</li>"
            for event in filtered
        )
        return f"<ul class='list'>{items}</ul>"

    def _html_list(self, values: Iterable[str]) -> str:
        values = list(values)
        if not values:
            return "<p>None</p>"
        return "<ul class='list'>" + "".join(f"<li>{html.escape(item)}</li>" for item in values) + "</ul>"

    def _metric_rows(self, metrics) -> list[tuple[str, object]]:
        return [
            ("Total log lines", metrics.total_log_lines),
            ("Total events", metrics.total_events),
            ("Files touched", metrics.files_touched),
            ("Commands run", metrics.commands_run),
            ("Errors found", metrics.errors_found),
            ("Retries", metrics.retries),
            ("Tests detected", metrics.tests_detected),
            ("Human interventions", metrics.human_interventions),
            ("Diff added lines", metrics.diff_added_lines),
            ("Diff removed lines", metrics.diff_removed_lines),
            ("Estimated complexity", metrics.estimated_complexity),
            ("Estimated cost level", metrics.estimated_cost_level),
        ]
