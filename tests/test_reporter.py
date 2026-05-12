from agentops_lite.models import AgentEvaluation, AgentEvent, AgentMetrics, AgentRun
from agentops_lite.reporter import ReportGenerator


def make_run():
    return AgentRun(
        run_id="report-run",
        agent_name="Codex",
        model_name="gpt-5-codex",
        task_name="Fix login",
        task_type="bug_fix",
        task_description="Fix empty password validation.",
        raw_log="final summary",
        events=[AgentEvent(event_type="final_answer", content="done", line_number=1, confidence=0.9)],
        metrics=AgentMetrics(total_log_lines=1, total_events=1, files_touched=1),
        evaluation=AgentEvaluation(
            completion_score=80,
            code_quality_score=75,
            reliability_score=90,
            cost_efficiency_score=100,
            overall_score=86,
            strengths=["Clear finish"],
            weaknesses=["Small sample"],
            failure_reasons=["No major failure"],
            improvement_suggestions=["Add more tests"],
        ),
    )


def test_markdown_and_html_files_are_generated(tmp_path):
    paths = ReportGenerator().generate_all(make_run(), tmp_path / "report")

    assert paths["markdown"].exists()
    assert paths["html"].exists()
    assert paths["json"].exists()


def test_reports_include_agent_model_and_overall_score(tmp_path):
    paths = ReportGenerator().generate_all(make_run(), tmp_path / "report")
    markdown = paths["markdown"].read_text(encoding="utf-8")
    html = paths["html"].read_text(encoding="utf-8")

    assert "Codex" in markdown
    assert "gpt-5-codex" in markdown
    assert "86" in markdown
    assert "Codex" in html
    assert "gpt-5-codex" in html
    assert "86" in html
