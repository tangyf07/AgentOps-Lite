from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


UNSUPPORTED_FORMAT_NOTES = [
    "Cursor IDE chat stored only in SQLite/protobuf (workspaceStorage state.vscdb, ~/.cursor/chats/*/store.db) is not parsed. Readable Cursor Agent JSONL under ~/.cursor/projects/*/agent-transcripts/ is supported.",
    "OpenCode history in ~/.local/share/opencode/opencode.db (SQLite) is not parsed.",
    "Codex encrypted_content / reasoning blobs are skipped; they are not decryptable locally.",
    "GitHub Copilot CLI session-state and Hermes state.db are not parsed.",
]


@dataclass
class DiscoveredSession:
    source: str
    path: Path
    mtime: float
    status: str = "ok"
    notes: list[str] = field(default_factory=list)
    title: str | None = None
    model_name: str | None = None
    log_text: str = ""

    @property
    def modified_iso(self) -> str:
        return datetime.fromtimestamp(self.mtime, tz=timezone.utc).isoformat()


def home_dir() -> Path:
    return Path.home()


def _unique_existing(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = str(path.expanduser())
        except OSError:
            continue
        key = resolved.lower()
        if key in seen:
            continue
        seen.add(key)
        candidate = Path(resolved)
        if candidate.exists():
            result.append(candidate)
    return result


def default_search_roots() -> dict[str, list[Path]]:
    home = home_dir()
    appdata = os.environ.get("APPDATA")
    local_appdata = os.environ.get("LOCALAPPDATA")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    xdg_data = os.environ.get("XDG_DATA_HOME")

    cursor_roots = [
        home / ".cursor" / "projects",
        Path(os.environ["CURSOR_HOME"]) / "projects" if os.environ.get("CURSOR_HOME") else None,
        Path(appdata) / "Cursor" if appdata else None,
        Path(local_appdata) / "Cursor" if local_appdata else None,
        home / "Library" / "Application Support" / "Cursor",
        Path(xdg) / "Cursor" if xdg else None,
    ]
    claude_roots = [
        Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" if os.environ.get("CLAUDE_CONFIG_DIR") else None,
        home / ".claude" / "projects",
        Path(xdg) / "claude" / "projects" if xdg else None,
    ]
    if os.environ.get("CLAUDE_CONFIG_DIRS"):
        for item in os.environ["CLAUDE_CONFIG_DIRS"].split(os.pathsep):
            if item.strip():
                claude_roots.append(Path(item.strip()) / "projects")
    codex_home = os.environ.get("CODEX_HOME") or os.environ.get("CODEX_DIR")
    codex_roots = [
        Path(codex_home) / "sessions" if codex_home else None,
        home / ".codex" / "sessions",
        Path(xdg_data) / "codex" / "sessions" if xdg_data else None,
        Path(appdata) / "Codex" / "sessions" if appdata else None,
    ]
    return {
        "cursor": _unique_existing(p for p in cursor_roots if p is not None),
        "claude": _unique_existing(p for p in claude_roots if p is not None),
        "codex": _unique_existing(p for p in codex_roots if p is not None),
    }


def discover_sessions(
    sources: Iterable[str] | None = None,
    extra_dirs: Iterable[Path | str] | None = None,
    roots: dict[str, list[Path]] | None = None,
) -> list[DiscoveredSession]:
    wanted = {item.lower() for item in (sources or ("cursor", "claude", "codex"))}
    search_roots = roots if roots is not None else default_search_roots()
    found: list[DiscoveredSession] = []

    if "cursor" in wanted:
        for root in search_roots.get("cursor", []):
            found.extend(_discover_cursor(root))
    if "claude" in wanted:
        for root in search_roots.get("claude", []):
            found.extend(_discover_claude(root))
    if "codex" in wanted:
        for root in search_roots.get("codex", []):
            found.extend(_discover_codex(root))

    for extra in extra_dirs or []:
        extra_path = Path(extra)
        if extra_path.is_file():
            found.append(_load_session("custom", extra_path))
        elif extra_path.is_dir():
            for path in _iter_files(extra_path, (".jsonl", ".json", ".txt", ".log", ".md")):
                found.append(_guess_and_load(path))

    found.sort(key=lambda item: item.mtime, reverse=True)
    return found


def _iter_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    results: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            results.append(path)
    return results


def _discover_cursor(root: Path) -> list[DiscoveredSession]:
    sessions: list[DiscoveredSession] = []
    if root.name == "projects" or (root / "projects").exists():
        project_root = root if root.name == "projects" else root / "projects"
        for path in _iter_files(project_root, (".jsonl", ".txt")):
            parts = {part.lower() for part in path.parts}
            if "agent-transcripts" in parts:
                sessions.append(_load_session("cursor", path))
        db_hits = list(root.rglob("state.vscdb")) + list(root.rglob("store.db"))
        for db_path in db_hits[:8]:
            sessions.append(
                DiscoveredSession(
                    source="cursor",
                    path=db_path,
                    mtime=db_path.stat().st_mtime,
                    status="unsupported",
                    notes=[
                        f"Found {db_path.name} but Cursor IDE chat protobuf/SQLite is not parsed. Use agent-transcripts JSONL instead."
                    ],
                )
            )
        return sessions
    for path in _iter_files(root, (".jsonl", ".txt")):
        sessions.append(_load_session("cursor", path))
    return sessions


def _discover_claude(root: Path) -> list[DiscoveredSession]:
    return [_load_session("claude", path) for path in _iter_files(root, (".jsonl",))]


def _discover_codex(root: Path) -> list[DiscoveredSession]:
    sessions: list[DiscoveredSession] = []
    for path in _iter_files(root, (".jsonl", ".json")):
        if path.name.startswith("rollout-") or path.suffix.lower() == ".jsonl":
            sessions.append(_load_session("codex", path))
    return sessions


def _guess_and_load(path: Path) -> DiscoveredSession:
    text = str(path).lower()
    if "agent-transcripts" in text or ".cursor" in text:
        source = "cursor"
    elif ".claude" in text:
        source = "claude"
    elif ".codex" in text or path.name.startswith("rollout-"):
        source = "codex"
    else:
        source = "custom"
    return _load_session(source, path)


def _load_session(source: str, path: Path) -> DiscoveredSession:
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        return DiscoveredSession(source=source, path=path, mtime=0, status="unreadable", notes=[str(exc)])
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return DiscoveredSession(source=source, path=path, mtime=mtime, status="unreadable", notes=[str(exc)])

    suffix = path.suffix.lower()
    notes: list[str] = []
    if suffix in {".jsonl", ".json"}:
        log_text, parse_notes, meta = json_bytes_to_log(raw, source=source)
        notes.extend(parse_notes)
        if not log_text.strip():
            return DiscoveredSession(
                source=source,
                path=path,
                mtime=mtime,
                status="unsupported",
                notes=notes or ["JSON log contained no extractable text fields."],
                title=meta.get("title"),
                model_name=meta.get("model"),
            )
        return DiscoveredSession(
            source=source,
            path=path,
            mtime=mtime,
            status="ok",
            notes=notes,
            title=meta.get("title"),
            model_name=meta.get("model"),
            log_text=log_text,
        )

    if not raw.strip():
        return DiscoveredSession(source=source, path=path, mtime=mtime, status="unsupported", notes=["File is empty."])
    return DiscoveredSession(
        source=source,
        path=path,
        mtime=mtime,
        status="ok",
        notes=notes,
        title=_first_line(raw),
        log_text=raw,
    )


def json_bytes_to_log(raw: str, source: str = "custom") -> tuple[str, list[str], dict[str, str | None]]:
    notes: list[str] = []
    records: list[Any] = []
    stripped = raw.strip()
    if stripped.startswith("["):
        try:
            loaded = json.loads(stripped)
            if isinstance(loaded, list):
                records = loaded
            elif isinstance(loaded, dict):
                records = [loaded]
            else:
                notes.append("JSON root was not an object or array.")
        except json.JSONDecodeError as exc:
            notes.append(f"Could not parse JSON array: {exc}. Documented instead of failing silently.")
            return "", notes, {}
    else:
        for index, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                notes.append(f"line {index}: not valid JSON; kept as plain text")
                records.append({"_plain": line})

    lines: list[str] = []
    meta: dict[str, str | None] = {"title": None, "model": None}
    skipped = 0
    for record in records:
        if isinstance(record, dict) and "_plain" in record:
            lines.append(str(record["_plain"]))
            continue
        extracted, record_meta = extract_record(record, source=source)
        if record_meta.get("title") and not meta["title"]:
            meta["title"] = record_meta["title"]
        if record_meta.get("model") and not meta["model"]:
            meta["model"] = record_meta["model"]
        if extracted:
            lines.extend(extracted)
        else:
            skipped += 1
            if skipped <= 8:
                keys = ", ".join(sorted(record.keys())) if isinstance(record, dict) else type(record).__name__
                notes.append(f"Skipped a {source} record with no known text fields (keys: {keys}).")
    if skipped > 8:
        notes.append(f"Skipped {skipped - 8} additional unparsed records.")
    if "encrypted_content" in raw:
        notes.append("Skipped Codex encrypted_content blobs; they are not readable locally.")
    return "\n".join(lines), notes, meta


def extract_record(record: Any, source: str) -> tuple[list[str], dict[str, str | None]]:
    meta: dict[str, str | None] = {"title": None, "model": None}
    if not isinstance(record, dict):
        text = _stringify(record)
        return ([text] if text else []), meta

    if record.get("isMeta") is True or record.get("type") in {"summary", "file-history-snapshot", "queue-operation"}:
        return [], meta

    model = _find_first_string(record, ("model", "model_name", "modelName"))
    if model:
        meta["model"] = model

    lines: list[str] = []
    role = str(record.get("role") or record.get("type") or record.get("kind") or "").strip()
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}

    if "encrypted_content" in record or (isinstance(payload, dict) and "encrypted_content" in payload):
        return [], meta

    if role == "turn_ended":
        status = record.get("status") or "ended"
        error = record.get("error")
        text = f"turn_ended: {status}" + (f" error={error}" if error else "")
        return [text], meta

    texts = _collect_texts(record)
    if not texts and payload:
        nested_role = str(payload.get("role") or payload.get("type") or role)
        nested_texts, nested_meta = extract_record(payload, source=source)
        if nested_meta.get("title") and not meta["title"]:
            meta["title"] = nested_meta["title"]
        if nested_meta.get("model") and not meta["model"]:
            meta["model"] = nested_meta["model"]
        if nested_texts:
            prefix = nested_role or source
            return [f"{prefix}: {item}" if not item.lower().startswith(prefix.lower()) else item for item in nested_texts], meta

    if not texts:
        return [], meta

    prefix = role or source
    formatted = []
    for item in texts:
        cleaned = _clean_user_query(item)
        if not cleaned:
            continue
        if not meta["title"] and prefix.lower() in {"user", "human"}:
            meta["title"] = _first_line(cleaned)
        formatted.append(f"{prefix}: {cleaned}" if prefix else cleaned)
    return formatted, meta


def _collect_texts(record: dict[str, Any]) -> list[str]:
    chunks: list[str] = []
    for key in ("content", "text", "message", "output", "arguments", "command", "input"):
        if key in record:
            chunks.extend(_flatten_content(record[key]))
    message = record.get("message")
    if isinstance(message, dict):
        chunks.extend(_flatten_content(message.get("content")))
        chunks.extend(_flatten_content(message.get("text")))
    tool = record.get("tool_use") or record.get("toolUse")
    if isinstance(tool, dict):
        name = tool.get("name") or "tool"
        chunks.append(f"run command: {name} {_stringify(tool.get('input'))}".strip())
    if record.get("type") == "tool_use" or record.get("name"):
        name = record.get("name")
        if name:
            chunks.append(f"run command: {name} {_stringify(record.get('input') or record.get('arguments'))}".strip())
    return [item for item in (_clean_user_query(chunk) for chunk in chunks) if item]


def _flatten_content(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_flatten_content(item))
        return items
    if isinstance(value, dict):
        kind = str(value.get("type") or "")
        if kind == "tool_use":
            name = value.get("name") or "tool"
            return [f"run command: {name} {_stringify(value.get('input'))}".strip()]
        if kind in {"tool_result", "function_call_output"}:
            return _flatten_content(value.get("content") or value.get("output") or value.get("text"))
        if "encrypted_content" in value:
            return []
        for key in ("text", "content", "input_text", "output_text", "value"):
            if key in value:
                nested = _flatten_content(value[key])
                if nested:
                    return nested
        name = value.get("name")
        if name:
            return [f"run command: {name} {_stringify(value.get('input') or value.get('arguments'))}".strip()]
        return []
    return [_stringify(value)]


def _clean_user_query(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    match = re.search(r"<user_query>\s*([\s\S]*?)\s*</user_query>", text)
    if match:
        return match.group(1).strip()
    return text


def _find_first_string(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    payload = record.get("payload")
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        dumped = json.dumps(value, ensure_ascii=False)
    except TypeError:
        dumped = str(value)
    if len(dumped) > 400:
        return dumped[:397] + "..."
    return dumped


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "untitled session"


def session_to_task(session: DiscoveredSession) -> dict[str, str]:
    title = session.title or session.path.stem
    return {
        "task_name": title,
        "task_type": "auto_ingested",
        "task_description": (
            f"Auto-ingested {session.source} session from {session.path}. "
            "No task YAML was provided."
        ),
    }
