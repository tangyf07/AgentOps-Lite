from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .models import AgentEvent, AgentMetrics


@dataclass(frozen=True)
class _Rule:
    event_type: str
    patterns: tuple[re.Pattern[str], ...]
    confidence: float


def _compile(patterns: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "human_intervention",
        _compile(
            [
                "user asked",
                "manual intervention",
                "manual",
                "human",
                "用户要求",
                "人工修改",
                "人工介入",
                "我手动",
            ]
        ),
        0.96,
    ),
    _Rule("retry", _compile(["retry", "rerun", "again", "重新", "再次", "修复后", "重试", "再试"]), 0.91),
    _Rule("final_answer", _compile(["final", "done", "completed", "summary", "完成", "总结", "最终", "finished"]), 0.90),
    _Rule(
        "error",
        _compile(
            [
                r"\berror\b",
                r"\bexception\b",
                r"\btraceback\b",
                r"\bfailed\b",
                r"\bfailure\b",
                "报错",
                "失败",
                r"\bcannot\b",
                r"\bnot found\b",
                r"\binvalid\b",
                r"\btimeout\b",
            ]
        ),
        0.95,
    ),
    _Rule(
        "task_understanding",
        _compile(["task understanding", "understand the task", "任务理解", "需求理解", "I need to", "需要先", "先确认"]),
        0.88,
    ),
    _Rule("planning", _compile([r"\bplan\b", "todo", r"\bsteps\b", "approach", "计划", "步骤", "任务拆解", "outline", "strategy"]), 0.86),
    _Rule(
        "file_write",
        _compile(["apply_patch", r"\bedit\b", r"\bwrite\b", r"\bpatch\b", r"\bmodify\b", r"\bupdate\b", "创建文件", "修改文件", "新增文件", "保存文件"]),
        0.88,
    ),
    _Rule(
        "command_run",
        _compile(
            [
                "run command",
                "execute command",
                "执行命令",
                r"\bterminal\b",
                r"\bshell\b",
                r"\bbash\b",
                r"\bcommand\b",
                r"\bpowershell\b",
                r"\bpwsh\b",
                r"\bcmd\b",
                r"\bpython\b",
                r"\bnode\b",
                r"\bpnpm\b",
                r"\bnpm\b",
                r"\byarn\b",
                r"\buv\b",
                r"\bpip\b",
                r"\bgit\b",
                r"\bmake\b",
                r"\bcargo\b",
                r"\bbun\b",
                r"\bdeno\b",
                r"\brg\b",
                r"\bgrep\b",
                r"\bcat\b",
                r"\bls\b",
                r"^ps\s",
                r"^sh\s",
                r"^bash\s",
                r"^\$\s",
                r"^>\s",
            ]
        ),
        0.80,
    ),
    _Rule(
        "test_run",
        _compile(
            [
                r"\bnpm test\b",
                r"\bpytest\b",
                r"\bunittest\b",
                r"\bpnpm test\b",
                r"\byarn test\b",
                r"\bcargo test\b",
                r"\bgo test\b",
                r"\btest passed\b",
                r"\btests passed\b",
                r"\bpassed in\b",
                r"\btest result\b",
                r"\btest passed\b",
                "测试通过",
                "测试失败",
                "failed tests",
                "running tests",
            ]
        ),
        0.93,
    ),
    _Rule(
        "file_read",
        _compile(["read file", "open file", "查看文件", "读取文件", r"\bcat\b", r"\bgrep\b", r"\bsearch\b", "find in file", r"sed -n", r"\brg\b", r"\bls\b"]),
        0.84,
    ),
)


_COMMAND_PATTERNS = _compile(
    [
        "run command",
        "execute command",
        "执行命令",
        r"\bterminal\b",
        r"\bshell\b",
        r"\bbash\b",
        r"\bcommand\b",
        r"\bpowershell\b",
        r"\bpwsh\b",
        r"\bcmd\b",
        r"\bpython\b",
        r"\bnode\b",
        r"\bpnpm\b",
        r"\bnpm\b",
        r"\byarn\b",
        r"\buv\b",
        r"\bpip\b",
        r"\bgit\b",
        r"\bmake\b",
        r"\bcargo\b",
        r"\bbun\b",
        r"\bdeno\b",
        r"\brg\b",
        r"\bgrep\b",
        r"\bcat\b",
        r"\bls\b",
        r"^ps\s",
        r"^sh\s",
        r"^bash\s",
        r"^\$\s",
        r"^>\s",
    ]
)


def _clean_path(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


class AgentLogParser:
    def parse(self, log_text: str, diff_text: str | None = None) -> tuple[list[AgentEvent], AgentMetrics]:
        lines = log_text.splitlines()
        events = self._parse_events(lines)
        metrics = self._build_metrics(lines, events, diff_text)
        return events, metrics

    def _parse_events(self, lines: list[str]) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for index, line in enumerate(lines, start=1):
            content = line.strip()
            if not content:
                continue
            matched = self._match_rule(content)
            if matched is None:
                events.append(AgentEvent(event_type="unknown", content=content, line_number=index, confidence=0.2))
                continue
            events.append(
                AgentEvent(
                    event_type=matched.event_type,
                    content=content,
                    line_number=index,
                    confidence=matched.confidence,
                )
            )
        return events

    def _match_rule(self, content: str) -> _Rule | None:
        for rule in _RULES:
            if any(pattern.search(content) for pattern in rule.patterns):
                return rule
        return None

    def _build_metrics(self, lines: list[str], events: list[AgentEvent], diff_text: str | None) -> AgentMetrics:
        diff_added_lines, diff_removed_lines, files_touched = self._parse_diff(diff_text)
        commands_run = sum(1 for line in lines if any(pattern.search(line.strip()) for pattern in _COMMAND_PATTERNS))
        total_events = len(events)
        return AgentMetrics(
            total_log_lines=len(lines),
            total_events=total_events,
            files_touched=files_touched,
            commands_run=commands_run,
            errors_found=sum(1 for event in events if event.event_type == "error"),
            retries=sum(1 for event in events if event.event_type == "retry"),
            tests_detected=sum(1 for event in events if event.event_type == "test_run"),
            human_interventions=sum(1 for event in events if event.event_type == "human_intervention"),
            diff_added_lines=diff_added_lines,
            diff_removed_lines=diff_removed_lines,
            estimated_complexity=self._estimate_complexity(total_events),
            estimated_cost_level=self._estimate_cost_level(len(lines)),
        )

    def _parse_diff(self, diff_text: str | None) -> tuple[int, int, int]:
        if not diff_text:
            return 0, 0, 0

        added = 0
        removed = 0
        touched_files: set[str] = set()

        for line in diff_text.splitlines():
            if line.startswith("diff --git "):
                match = re.search(r"diff --git a/(.+?) b/(.+)$", line)
                if match:
                    touched_files.add(_clean_path(match.group(2)))
            elif line.startswith("+++ b/"):
                touched_files.add(_clean_path(line[6:]))
            elif line.startswith("--- a/"):
                touched_files.add(_clean_path(line[6:]))
            elif line.startswith("rename from "):
                touched_files.add(_clean_path(line[len("rename from ") :]))
            elif line.startswith("rename to "):
                touched_files.add(_clean_path(line[len("rename to ") :]))
            elif line.startswith("copy from "):
                touched_files.add(_clean_path(line[len("copy from ") :]))
            elif line.startswith("copy to "):
                touched_files.add(_clean_path(line[len("copy to ") :]))

            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1

        touched_files = {item for item in touched_files if item and item != "dev/null"}
        return added, removed, len(touched_files)

    @staticmethod
    def _estimate_complexity(total_events: int) -> str:
        if total_events < 10:
            return "low"
        if total_events < 30:
            return "medium"
        return "high"

    @staticmethod
    def _estimate_cost_level(total_log_lines: int) -> str:
        if total_log_lines < 100:
            return "low"
        if total_log_lines < 300:
            return "medium"
        return "high"
