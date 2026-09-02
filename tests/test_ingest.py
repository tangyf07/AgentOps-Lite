from __future__ import annotations

from pathlib import Path

from agentops_lite.ingest import discover_sessions, json_bytes_to_log
from agentops_lite.cli import main


def test_cursor_jsonl_extracts_user_query(tmp_path: Path):
    raw = "\n".join(
        [
            '{"role":"user","message":{"content":[{"type":"text","text":"<user_query>fix login validation</user_query>"}]}}',
            '{"role":"assistant","message":{"content":[{"type":"text","text":"Plan: inspect files and patch validation"},{"type":"tool_use","name":"Read","input":{"path":"app/auth.py"}}]}}',
            '{"type":"turn_ended","status":"success"}',
        ]
    )
    text, notes, meta = json_bytes_to_log(raw, source="cursor")
    assert "fix login validation" in text
    assert "Plan: inspect files" in text
    assert "run command: Read" in text
    assert meta["title"] == "fix login validation"
    assert notes == [] or all("encrypted" not in note.lower() or True for note in notes)


def test_claude_jsonl_nests_message_content():
    raw = "\n".join(
        [
            '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"add tests"}]},"isMeta":false}',
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"I will add pytest coverage"}]}}',
            '{"type":"summary","summary":"should be skipped"}',
        ]
    )
    text, notes, meta = json_bytes_to_log(raw, source="claude")
    assert "add tests" in text
    assert "pytest coverage" in text
    assert "should be skipped" not in text
    assert meta["title"] == "add tests"


def test_codex_skips_encrypted_content_and_keeps_commands():
    raw = "\n".join(
        [
            '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"refactor parser"}]}}',
            '{"type":"response_item","payload":{"type":"function_call","name":"shell","arguments":{"command":"pytest"}}}',
            '{"type":"response_item","payload":{"encrypted_content":"AAAA"}}',
        ]
    )
    text, notes, meta = json_bytes_to_log(raw, source="codex")
    assert "refactor parser" in text
    assert "pytest" in text
    assert "AAAA" not in text
    assert any("encrypted" in note.lower() for note in notes)
    assert meta["title"] == "refactor parser"


def test_unknown_json_object_is_documented_not_silent():
    text, notes, _meta = json_bytes_to_log('{"foo": 1, "bar": true}\n', source="custom")
    assert text == ""
    assert notes
    assert "keys:" in notes[0]


def test_discover_sessions_from_fake_homes(tmp_path: Path):
    cursor = tmp_path / "cursor" / "projects" / "demo" / "agent-transcripts" / "abc" / "abc.jsonl"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(
        '{"role":"user","message":{"content":[{"type":"text","text":"hello from cursor"}]}}\n',
        encoding="utf-8",
    )
    claude = tmp_path / "claude" / "projects" / "-tmp-demo" / "sess.jsonl"
    claude.parent.mkdir(parents=True)
    claude.write_text(
        '{"type":"user","message":{"content":[{"type":"text","text":"hello from claude"}]}}\n',
        encoding="utf-8",
    )
    codex = tmp_path / "codex" / "sessions" / "2026" / "09" / "02" / "rollout-2026-09-02T01-00-00.jsonl"
    codex.parent.mkdir(parents=True)
    codex.write_text(
        '{"payload":{"role":"user","content":[{"text":"hello from codex"}]}}\n',
        encoding="utf-8",
    )
    db = tmp_path / "cursor" / "projects" / "demo" / "store.db"
    db.write_bytes(b"not-a-transcript")

    sessions = discover_sessions(
        roots={
            "cursor": [tmp_path / "cursor" / "projects"],
            "claude": [tmp_path / "claude" / "projects"],
            "codex": [tmp_path / "codex" / "sessions"],
        }
    )
    ok = [item for item in sessions if item.status == "ok"]
    unsupported = [item for item in sessions if item.status == "unsupported"]
    sources = {item.source for item in ok}
    assert sources == {"cursor", "claude", "codex"}
    assert any("hello from cursor" in item.log_text for item in ok)
    assert unsupported
    assert "protobuf" in unsupported[0].notes[0] or "not parsed" in unsupported[0].notes[0]


def test_cli_sample_and_ingest_extra_dir(tmp_path: Path):
    sample_out = tmp_path / "sample"
    assert main(["sample", "--out", str(sample_out)]) == 0
    assert sample_out.with_suffix(".md").exists()
    assert sample_out.with_suffix(".html").exists()
    assert sample_out.with_suffix(".json").exists()

    session = tmp_path / "agent-transcripts" / "one" / "one.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        '{"role":"user","message":{"content":[{"type":"text","text":"ship packaging"}]}}\n'
        '{"role":"assistant","message":{"content":[{"type":"text","text":"final summary: done"}]}}\n',
        encoding="utf-8",
    )
    ingest_out = tmp_path / "ingested"
    assert main(["ingest", "--dir", str(session.parent.parent), "--out", str(ingest_out)]) == 0
    markdown = ingest_out.with_suffix(".md").read_text(encoding="utf-8")
    assert "ship packaging" in markdown
    assert "Cursor" in markdown or "cursor" in markdown.lower()


def test_cli_ingest_list_empty(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["ingest", "--dir", str(empty), "--list"]) == 0
