from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml  # type: ignore
except Exception:  # pragma: no cover
    _yaml = None

try:
    from rich.console import Console as _RichConsole  # type: ignore
except Exception:  # pragma: no cover
    _RichConsole = None

try:
    from jinja2 import BaseLoader as _JinjaBaseLoader  # type: ignore
    from jinja2 import Environment as _JinjaEnvironment  # type: ignore
    from jinja2 import Template as _JinjaTemplate  # type: ignore
    from jinja2 import select_autoescape as _select_autoescape  # type: ignore
    from markupsafe import Markup as _Markup  # type: ignore
except Exception:  # pragma: no cover
    _JinjaBaseLoader = None
    _JinjaEnvironment = None
    _JinjaTemplate = None
    _select_autoescape = None
    _Markup = None


class PlainConsole:
    def print(self, *args: object, **_: object) -> None:
        cleaned = [re.sub(r"\[/?[a-zA-Z][^\]]*\]", "", str(arg)) for arg in args]
        print(*cleaned)


def get_console():
    if _RichConsole is not None:
        return _RichConsole()
    return PlainConsole()


def ensure_parent(path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def read_text(path: Path | str, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def write_text(path: Path | str, text: str, encoding: str = "utf-8") -> Path:
    target = ensure_parent(path)
    target.write_text(text, encoding=encoding)
    return target


def read_json(path: Path | str) -> Any:
    return json.loads(read_text(path))


def write_json(path: Path | str, data: Any) -> Path:
    return write_text(path, json.dumps(deep_dump(data), ensure_ascii=False, indent=2))


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "run"


def clamp(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, int(value)))


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "null", "Null", "NULL", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _simple_yaml_load(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    data: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if line.startswith(" ") or ":" not in line:
            i += 1
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        indent = len(line) - len(line.lstrip(" "))

        if value == "|":
            i += 1
            block_lines: list[str] = []
            while i < len(lines):
                candidate = lines[i]
                if not candidate.strip():
                    block_lines.append("")
                    i += 1
                    continue
                candidate_indent = len(candidate) - len(candidate.lstrip(" "))
                if candidate_indent <= indent:
                    break
                block_lines.append(candidate[indent + 2 :].rstrip())
                i += 1
            data[key] = "\n".join(block_lines).rstrip()
            continue

        if value == "":
            i += 1
            list_items: list[Any] = []
            nested: dict[str, Any] = {}
            while i < len(lines):
                candidate = lines[i]
                if not candidate.strip():
                    i += 1
                    continue
                candidate_indent = len(candidate) - len(candidate.lstrip(" "))
                if candidate_indent <= indent:
                    break
                candidate_stripped = candidate.strip()
                if candidate_stripped.startswith("- "):
                    list_items.append(_parse_scalar(candidate_stripped[2:]))
                elif ":" in candidate_stripped:
                    sub_key, sub_value = candidate_stripped.split(":", 1)
                    nested[sub_key.strip()] = _parse_scalar(sub_value.strip())
                i += 1
            data[key] = list_items if list_items else nested
            continue

        data[key] = _parse_scalar(value)
        i += 1
    return data


def load_yaml_text(text: str) -> dict[str, Any]:
    if _yaml is not None:
        loaded = _yaml.safe_load(text)
        return loaded or {}
    return _simple_yaml_load(text)


def load_yaml_file(path: Path | str) -> dict[str, Any]:
    return load_yaml_text(read_text(path))


def render_template(template_text: str, context: dict[str, Any]) -> str:
    if _JinjaTemplate is not None:
        return _JinjaTemplate(template_text).render(**context)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        value: Any = context
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part, "")
            else:
                value = getattr(value, part, "")
        return "" if value is None else str(value)

    return re.sub(r"{{\s*([\w.]+)\s*}}", replace, template_text)


def render_html_template(template_text: str, context: dict[str, Any]) -> str:
    if _JinjaEnvironment is not None and _JinjaBaseLoader is not None and _select_autoescape is not None:
        safe_context = {
            key: _Markup(value) if _Markup is not None and key.endswith("_html") and isinstance(value, str) else value
            for key, value in context.items()
        }
        environment = _JinjaEnvironment(loader=_JinjaBaseLoader(), autoescape=_select_autoescape(("html", "htm", "xml")))
        return environment.from_string(template_text).render(**safe_context)
    return render_template(template_text, context)


def unique_preserve_order(items: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def dedupe_text_list(items: list[str]) -> list[str]:
    return unique_preserve_order([item.strip() for item in items if item and item.strip()])


def deep_dump(value: Any) -> Any:
    if isinstance(value, list):
        return [deep_dump(item) for item in value]
    if isinstance(value, tuple):
        return [deep_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: deep_dump(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        try:
            return deep_dump(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict") and callable(value.dict):
        try:
            return deep_dump(value.dict())
        except Exception:
            pass
    return copy.deepcopy(value)
