from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import AgentEvaluation, AgentRun
from .utils import dedupe_text_list


def llm_review_agent_run(run: AgentRun, existing: AgentEvaluation | None = None) -> AgentEvaluation | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_REVIEWER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    system_prompt = (
        "You are reviewing an AI coding agent run. "
        "Return only JSON with keys strengths, weaknesses, failure_reasons, improvement_suggestions. "
        "Each value must be a list of short Chinese phrases."
    )
    user_payload = {
        "run": run.model_dump(),
        "existing_evaluation": existing.model_dump() if existing else None,
    }
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
            ],
            "temperature": 0.2,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception:
        return None

    strengths = dedupe_text_list(parsed.get("strengths", []))
    weaknesses = dedupe_text_list(parsed.get("weaknesses", []))
    failure_reasons = dedupe_text_list(parsed.get("failure_reasons", []))
    improvement_suggestions = dedupe_text_list(parsed.get("improvement_suggestions", []))
    if not any([strengths, weaknesses, failure_reasons, improvement_suggestions]):
        return None

    evaluation = existing or AgentEvaluation()
    if strengths:
        evaluation.strengths = strengths
    if weaknesses:
        evaluation.weaknesses = weaknesses
    if failure_reasons:
        evaluation.failure_reasons = failure_reasons
    if improvement_suggestions:
        evaluation.improvement_suggestions = improvement_suggestions
    return evaluation

