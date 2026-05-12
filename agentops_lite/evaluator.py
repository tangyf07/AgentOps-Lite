from __future__ import annotations

from collections import Counter

from .models import AgentEvaluation, AgentRun
from .utils import clamp, round_half_up, unique_preserve_order


class RuleBasedEvaluator:
    def evaluate(self, run: AgentRun) -> AgentEvaluation:
        events = run.events
        metrics = run.metrics
        event_counts = Counter(event.event_type for event in events)

        completion_score = 0
        if event_counts.get("final_answer", 0):
            completion_score += 25
        if event_counts.get("file_write", 0):
            completion_score += 25
        if event_counts.get("test_run", 0):
            completion_score += 20
        if metrics.errors_found < 3:
            completion_score += 15
        if event_counts.get("planning", 0):
            completion_score += 15
        completion_score = clamp(completion_score)

        code_quality_score = 0
        if metrics.diff_added_lines and metrics.diff_removed_lines:
            code_quality_score += 30
        if metrics.tests_detected:
            code_quality_score += 25
        if metrics.errors_found <= metrics.retries + 1:
            code_quality_score += 20
        if metrics.files_touched <= 5:
            code_quality_score += 15
        if event_counts.get("file_read", 0):
            code_quality_score += 10
        code_quality_score = clamp(code_quality_score)

        reliability_score = 100
        reliability_score -= metrics.errors_found * 8
        reliability_score -= metrics.retries * 5
        if not metrics.tests_detected:
            reliability_score -= 25
        if metrics.human_interventions:
            reliability_score -= 15
        reliability_score = clamp(reliability_score)

        cost_efficiency_score = 100
        if metrics.total_log_lines > 300:
            cost_efficiency_score -= 20
        if metrics.retries > 3:
            cost_efficiency_score -= 20
        if metrics.errors_found > 5:
            cost_efficiency_score -= 20
        if metrics.commands_run > 15:
            cost_efficiency_score -= 15
        cost_efficiency_score = clamp(cost_efficiency_score)

        overall_score = clamp(
            round_half_up(
                (completion_score + code_quality_score + reliability_score + cost_efficiency_score) / 4
            )
        )

        return AgentEvaluation(
            completion_score=completion_score,
            code_quality_score=code_quality_score,
            reliability_score=reliability_score,
            cost_efficiency_score=cost_efficiency_score,
            overall_score=overall_score,
            strengths=self._build_strengths(run, completion_score, reliability_score, cost_efficiency_score),
            weaknesses=self._build_weaknesses(run, code_quality_score, reliability_score, cost_efficiency_score),
            failure_reasons=self._build_failure_reasons(run),
            improvement_suggestions=self._build_suggestions(run),
        )

    def _build_strengths(
        self,
        run: AgentRun,
        completion_score: int,
        reliability_score: int,
        cost_efficiency_score: int,
    ) -> list[str]:
        metrics = run.metrics
        events = run.events
        strengths: list[str] = []

        if completion_score >= 75:
            strengths.append("Clear completion signals were detected")
        if metrics.tests_detected:
            strengths.append("The workflow includes a test or verification step")
        if metrics.diff_added_lines and metrics.diff_removed_lines:
            strengths.append("The run produced concrete, traceable code changes")
        if reliability_score >= 80:
            strengths.append("The execution path is relatively stable")
        if cost_efficiency_score >= 80:
            strengths.append("The run stayed within a reasonable cost footprint")
        if 0 < metrics.files_touched <= 5:
            strengths.append("The change surface is focused")
        if any(event.event_type == "planning" for event in events):
            strengths.append("The agent planned before editing")
        if any(event.event_type == "file_read" for event in events):
            strengths.append("The agent read project context before making changes")
        if not strengths:
            strengths.append("The log still contains enough structure for review")

        return unique_preserve_order(strengths)[:5]

    def _build_weaknesses(
        self,
        run: AgentRun,
        code_quality_score: int,
        reliability_score: int,
        cost_efficiency_score: int,
    ) -> list[str]:
        metrics = run.metrics
        events = run.events
        weaknesses: list[str] = []

        if not metrics.tests_detected:
            weaknesses.append("No test run was detected")
        if metrics.errors_found:
            weaknesses.append(f"{metrics.errors_found} error signal(s) were detected")
        if metrics.retries:
            weaknesses.append(f"{metrics.retries} retry step(s) suggest rework during execution")
        if not any(event.event_type == "final_answer" for event in events):
            weaknesses.append("No explicit final summary was detected")
        if metrics.human_interventions:
            weaknesses.append("Human intervention appeared during the run")
        if code_quality_score < 70:
            weaknesses.append("Code quality signals are still weak")
        if reliability_score < 70:
            weaknesses.append("Reliability needs improvement")
        if cost_efficiency_score < 70:
            weaknesses.append("Cost efficiency can be improved")
        if not weaknesses:
            weaknesses.append("No major weakness was detected, but more evidence would help")

        return unique_preserve_order(weaknesses)[:5]

    def _build_failure_reasons(self, run: AgentRun) -> list[str]:
        metrics = run.metrics
        events = run.events
        reasons: list[str] = []

        if not any(event.event_type == "final_answer" for event in events):
            reasons.append("The final completion evidence is weak")
        if metrics.errors_found:
            reasons.append("Errors or failed tests appeared during execution")
        if not metrics.tests_detected:
            reasons.append("Missing test verification makes the result harder to trust")
        if metrics.human_interventions:
            reasons.append("Human intervention reduced automation quality")
        if metrics.retries > 2:
            reasons.append("Frequent retries suggest unstable intermediate steps")
        if not reasons:
            reasons.append("No obvious failure reason was detected")

        return unique_preserve_order(reasons)[:5]

    def _build_suggestions(self, run: AgentRun) -> list[str]:
        metrics = run.metrics
        events = run.events
        suggestions: list[str] = []

        if not metrics.tests_detected:
            suggestions.append("Add a minimal repeatable test command to complete the verification loop")
        if metrics.errors_found:
            suggestions.append("Record the error cause, fix action, and verification result more explicitly")
        if metrics.retries:
            suggestions.append("Capture the failure reason before retrying")
        if metrics.files_touched > 5:
            suggestions.append("Reduce the file surface area where possible")
        if not any(event.event_type == "planning" for event in events):
            suggestions.append("Add a short plan before editing code")
        if metrics.commands_run > 15:
            suggestions.append("Reduce repetitive command runs and consolidate checks")
        if metrics.human_interventions:
            suggestions.append("Turn manual intervention points into rules, scripts, or tests")
        if not suggestions:
            suggestions.append("Keep the current execution rhythm and keep enriching verification evidence")

        return unique_preserve_order(suggestions)[:6]
