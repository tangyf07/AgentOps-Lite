from agentops_lite.evaluator import RuleBasedEvaluator
from agentops_lite.models import AgentEvent, AgentMetrics, AgentRun


def make_run(errors=0, retries=0, tests=1):
    events = [
        AgentEvent(event_type="planning", content="plan"),
        AgentEvent(event_type="file_read", content="read"),
        AgentEvent(event_type="file_write", content="write"),
        AgentEvent(event_type="final_answer", content="done"),
    ]
    events.extend(AgentEvent(event_type="test_run", content="pytest") for _ in range(tests))
    events.extend(AgentEvent(event_type="error", content="error") for _ in range(errors))
    events.extend(AgentEvent(event_type="retry", content="retry") for _ in range(retries))
    return AgentRun(
        run_id="test-run",
        agent_name="Codex",
        model_name="gpt-test",
        task_name="Task",
        task_type="bug_fix",
        task_description="Fix bug",
        raw_log="log",
        events=events,
        metrics=AgentMetrics(
            total_log_lines=20,
            total_events=len(events),
            files_touched=2,
            commands_run=2,
            errors_found=errors,
            retries=retries,
            tests_detected=tests,
            diff_added_lines=4,
            diff_removed_lines=2,
        ),
    )


def test_scores_are_between_zero_and_100():
    evaluation = RuleBasedEvaluator().evaluate(make_run(errors=4, retries=2, tests=1))

    for score in [
        evaluation.completion_score,
        evaluation.code_quality_score,
        evaluation.reliability_score,
        evaluation.cost_efficiency_score,
        evaluation.overall_score,
    ]:
        assert 0 <= score <= 100


def test_test_run_improves_reliability():
    evaluator = RuleBasedEvaluator()
    with_tests = evaluator.evaluate(make_run(errors=0, retries=0, tests=1))
    without_tests = evaluator.evaluate(make_run(errors=0, retries=0, tests=0))

    assert with_tests.reliability_score > without_tests.reliability_score


def test_more_errors_lower_reliability():
    evaluator = RuleBasedEvaluator()
    low_error = evaluator.evaluate(make_run(errors=1, retries=0, tests=1))
    high_error = evaluator.evaluate(make_run(errors=6, retries=0, tests=1))

    assert high_error.reliability_score < low_error.reliability_score
