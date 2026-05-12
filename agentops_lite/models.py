from __future__ import annotations

from copy import deepcopy
from typing import Any

try:  # Prefer real pydantic when available.
    import pydantic as _pydantic  # type: ignore

    _PydanticBaseModel = _pydantic.BaseModel
    _Field = _pydantic.Field

    class BaseModel(_PydanticBaseModel):  # type: ignore[misc]
        if not hasattr(_PydanticBaseModel, "model_dump"):

            def model_dump(self, *args, **kwargs):  # type: ignore[override]
                return self.dict(*args, **kwargs)

            @classmethod
            def model_validate(cls, data):  # type: ignore[override]
                return cls.parse_obj(data)

            def model_dump_json(self, *args, **kwargs):  # type: ignore[override]
                return self.json(*args, **kwargs)

    def Field(*args, **kwargs):
        return _Field(*args, **kwargs)

except Exception:  # pragma: no cover - fallback path

    class BaseModel:
        def __init__(self, **data: Any):
            annotations = getattr(self.__class__, "__annotations__", {})
            for name in annotations:
                if name in data:
                    value = data[name]
                elif hasattr(self.__class__, name):
                    value = deepcopy(getattr(self.__class__, name))
                else:
                    value = None
                setattr(self, name, value)
            for name, value in data.items():
                if name not in annotations:
                    setattr(self, name, value)

        @classmethod
        def model_validate(cls, data: Any):
            if isinstance(data, cls):
                return data
            if not isinstance(data, dict):
                raise TypeError(f"Expected mapping for {cls.__name__}, got {type(data)!r}")
            return cls(**data)

        def model_dump(self):
            return _dump_value(self.__dict__)

        def dict(self):  # pragma: no cover - compatibility
            return self.model_dump()

        def model_dump_json(self, *args, **kwargs):
            import json

            kwargs.setdefault("ensure_ascii", False)
            kwargs.setdefault("indent", 2)
            return json.dumps(self.model_dump(), *args, **kwargs)

        @classmethod
        def parse_obj(cls, obj):  # pragma: no cover - compatibility
            return cls.model_validate(obj)

    def Field(default=None, default_factory=None, **kwargs):  # type: ignore[override]
        if default_factory is not None:
            return default_factory()
        return default


def _dump_value(value: Any):
    if isinstance(value, list):
        return [_dump_value(item) for item in value]
    if isinstance(value, tuple):
        return [_dump_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump_value(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        try:
            return _dump_value(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict") and callable(value.dict):
        try:
            return _dump_value(value.dict())
        except Exception:
            pass
    return deepcopy(value)


class AgentEvent(BaseModel):
    event_type: str = "unknown"
    content: str = ""
    line_number: int | None = None
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, data: Any) -> "AgentEvent":
        if isinstance(data, cls):
            return data
        if data is None:
            return cls()
        return cls.model_validate(data)


class AgentMetrics(BaseModel):
    total_log_lines: int = 0
    total_events: int = 0
    files_touched: int = 0
    commands_run: int = 0
    errors_found: int = 0
    retries: int = 0
    tests_detected: int = 0
    human_interventions: int = 0
    diff_added_lines: int = 0
    diff_removed_lines: int = 0
    estimated_complexity: str = "low"
    estimated_cost_level: str = "low"

    @classmethod
    def from_dict(cls, data: Any) -> "AgentMetrics":
        if isinstance(data, cls):
            return data
        if data is None:
            return cls()
        return cls.model_validate(data)


class AgentEvaluation(BaseModel):
    completion_score: int = 0
    code_quality_score: int = 0
    reliability_score: int = 0
    cost_efficiency_score: int = 0
    overall_score: int = 0
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> "AgentEvaluation":
        if isinstance(data, cls):
            return data
        if data is None:
            return cls()
        return cls.model_validate(data)


class AgentRun(BaseModel):
    run_id: str = ""
    agent_name: str = ""
    model_name: str = ""
    task_name: str = ""
    task_type: str = ""
    task_description: str = ""
    log_path: str | None = None
    diff_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    raw_log: str = ""
    raw_diff: str | None = None
    events: list[AgentEvent] = Field(default_factory=list)
    metrics: AgentMetrics = Field(default_factory=AgentMetrics)
    evaluation: AgentEvaluation = Field(default_factory=AgentEvaluation)

    @classmethod
    def from_dict(cls, data: Any) -> "AgentRun":
        if isinstance(data, cls):
            return data
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise TypeError(f"Expected mapping for AgentRun, got {type(data)!r}")
        events = [AgentEvent.from_dict(item) for item in data.get("events", []) or []]
        metrics = AgentMetrics.from_dict(data.get("metrics"))
        evaluation = AgentEvaluation.from_dict(data.get("evaluation"))
        payload = dict(data)
        payload["events"] = events
        payload["metrics"] = metrics
        payload["evaluation"] = evaluation
        return cls.model_validate(payload)

