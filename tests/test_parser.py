from agentops_lite.parser import AgentLogParser


def test_parser_detects_core_event_types():
    log = "\n".join(
        [
            "Task understanding: fix the login bug",
            "Plan: inspect files and patch validation",
            "read file: app/auth.py",
            "apply_patch: update password validation",
            "run command: pytest tests/test_auth.py",
            "failed tests: assertion error",
            "retry: adjust the assertion and rerun",
            "test passed: 3 passed",
            "final summary: completed the fix",
        ]
    )
    events, metrics = AgentLogParser().parse(log)
    event_types = {event.event_type for event in events}

    assert "planning" in event_types
    assert "file_read" in event_types
    assert "file_write" in event_types
    assert "command_run" in event_types
    assert "error" in event_types
    assert "retry" in event_types
    assert "test_run" in event_types
    assert "final_answer" in event_types
    assert metrics.total_log_lines == 9


def test_parser_counts_diff_added_removed_lines_and_files():
    diff = "\n".join(
        [
            "diff --git a/app/auth.py b/app/auth.py",
            "--- a/app/auth.py",
            "+++ b/app/auth.py",
            "@@ -1,3 +1,4 @@",
            "-old line",
            "+new line",
            "+another new line",
            " unchanged",
        ]
    )
    _, metrics = AgentLogParser().parse("final summary", diff)

    assert metrics.diff_added_lines == 2
    assert metrics.diff_removed_lines == 1
    assert metrics.files_touched == 1
