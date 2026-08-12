"""Run the preregistered predictive-validity successor through exact OpenRouter routing.

The agent must retrieve each frozen synthetic case through one local read-only function call.  A
tool-contract or JSON-output failure is an agent outcome; HTTP, route, or provider drift is not and
blocks finalization.  No automatic retries are made, keeping the preregistered request ceiling
auditable.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from workforce_graph.evidence.task4_phase2b_operators import (
    check_operator_output,
    derive_operator_output,
)

_builder_spec = importlib.util.spec_from_file_location(
    "build_predictive_validity_successor",
    Path(__file__).parent / "build_predictive_validity_successor.py",
)
builder = importlib.util.module_from_spec(_builder_spec)
_builder_spec.loader.exec_module(builder)

MODEL_ID = builder.MODEL_ID
PROVIDER = "Google AI Studio"
SCAFFOLDS = builder.SCAFFOLDS
DEFAULT_FRAME = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v3" / "frame.json"
DEFAULT_RAW_DIR = ROOT / "data" / "predictive_validity" / "raw"
DEFAULT_PILOT_LOG = DEFAULT_RAW_DIR / "PREDICTIVE_SUCCESSOR_v3_pilot.jsonl"
DEFAULT_PILOT = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v3" / "pilot.json"
DEFAULT_MAIN_LOG = DEFAULT_RAW_DIR / "PREDICTIVE_SUCCESSOR_v3_main.jsonl"
DEFAULT_MAIN = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v3" / "main.json"
TRANSPORT_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "").rstrip("/")
ENDPOINT = f"{TRANSPORT_BASE_URL}/chat/completions"
SYSTEM_PROMPT = """You perform one bounded synthetic support/back-office case.

You have exactly one read-only local tool, read_case. Call it exactly once before answering. Use
only the returned case. Do not claim network access, writes, approval, publication, communication,
or physical action. After the tool result, return only one JSON object with the requested schema;
no Markdown, prose wrapper, or invented values."""
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_case",
            "description": "Return the exact frozen local synthetic case for this run.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
]


class TransportOrRouteError(RuntimeError):
    """No outcome may be inferred from this request failure."""


def canonical_bytes(value: object) -> bytes:
    return builder.canonical_bytes(value)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else ["any JSON value"]
    return f"<{_type_name(value)}>"


def _guidance(expected: Mapping[str, Any], scaffold: str) -> str:
    keys = sorted(expected)
    if scaffold == "fields_only":
        return "Required top-level fields: " + ", ".join(keys)
    if scaffold == "top_level_types":
        schema = {key: f"<{_type_name(expected[key])}>" for key in keys}
    elif scaffold == "partial_recursive_shape":
        boundary = (len(keys) + 1) // 2
        schema = {
            key: _shape(expected[key]) if index < boundary else f"<{_type_name(expected[key])}>"
            for index, key in enumerate(keys)
        }
    elif scaffold == "recursive_shape":
        schema = _shape(dict(expected))
    else:
        raise ValueError(f"unknown scaffold: {scaffold}")
    return "Schema uses type placeholders, never answer values:\n" + json.dumps(
        schema, ensure_ascii=False, indent=2, sort_keys=True
    )


def _worked_example(case: Mapping[str, Any], expected: Mapping[str, Any], scaffold: str) -> str:
    example = case.get("worked_example")
    if not isinstance(example, dict):
        raise TypeError("case lacks its frozen category worked example")
    parts = [
        "A different frozen case from this category demonstrates the exact reusable semantics and serialization.",
        "Worked example case:\n"
        + json.dumps(example["input_payload"], ensure_ascii=False, indent=2, sort_keys=True),
        "Correct worked example answer:\n"
        + json.dumps(example["output_payload"], ensure_ascii=False, indent=2, sort_keys=True),
    ]
    if scaffold == "worked_example_plus_recursive_shape":
        parts.append(_guidance(expected, "recursive_shape"))
    elif scaffold != "worked_example":
        raise ValueError(f"unknown worked-example scaffold: {scaffold}")
    return "\n\n".join(parts)


def initial_prompt(case: Mapping[str, Any], expected: Mapping[str, Any], scaffold: str) -> str:
    return (
        f"Case id: {case['case_id']}\n"
        f"Category: {case['category']}\n"
        "Call read_case exactly once to obtain the case. Then solve it under its declared rules.\n\n"
        f"{_worked_example(case, expected, scaffold)}"
    )


def _seed(case_id: str, scaffold: str, stage: str) -> int:
    digest = sha256_bytes(f"{builder.INSTRUMENT_SEED}:{case_id}:{scaffold}:{stage}".encode())
    return int(digest[:8], 16)


def post_completion(*, payload: Mapping[str, Any], api_key: str, timeout: float = 180.0) -> dict:
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/dilp79/workforce-graph",
            "X-Title": "AllJobs predictive-validity successor",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise TransportOrRouteError(f"HTTP {error.code}: {detail}") from error
    except (TimeoutError, urllib.error.URLError) as error:
        raise TransportOrRouteError(f"{type(error).__name__}: {error}") from error
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise TransportOrRouteError("OpenRouter response was not JSON") from error
    if not isinstance(parsed, dict):
        raise TransportOrRouteError("OpenRouter response was not an object")
    return parsed


def _response_message(response: Mapping[str, Any]) -> dict[str, Any]:
    if response.get("model") != MODEL_ID:
        raise TransportOrRouteError(f"served model drift: {response.get('model')!r}")
    if response.get("provider") != PROVIDER:
        raise TransportOrRouteError(f"served provider drift: {response.get('provider')!r}")
    routed = response.get("_routed_via")
    if not isinstance(routed, dict) or routed.get("platform") != "openrouter":
        raise TransportOrRouteError(f"routed platform drift: {routed!r}")
    if routed.get("model") != MODEL_ID:
        raise TransportOrRouteError(f"routed model drift: {routed.get('model')!r}")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise TransportOrRouteError("response did not contain exactly one choice")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise TransportOrRouteError("response choice had no message object")
    return message


def _receipt(response: Mapping[str, Any]) -> dict[str, Any]:
    usage = response.get("usage") or {}
    return {
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "id": response.get("id"),
        "model": response.get("model"),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "provider": response.get("provider"),
        "routed_model": (response.get("_routed_via") or {}).get("model"),
        "routed_platform": (response.get("_routed_via") or {}).get("platform"),
    }


def _base_payload(
    messages: list[dict[str, Any]], *, case_id: str, scaffold: str, stage: str
) -> dict:
    return {
        "messages": messages,
        "model": MODEL_ID,
        "provider": {"allow_fallbacks": False, "order": [PROVIDER]},
        "seed": _seed(case_id, scaffold, stage),
        "temperature": 0,
        "tools": TOOLS,
    }


def _parse_json_object(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, str) or not content.strip():
        return None
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _empty_tool_arguments(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return json.loads(value) == {}
    except json.JSONDecodeError:
        return False


def domain_grade(case: Mapping[str, Any], deliverable: Mapping[str, Any]) -> dict[str, Any]:
    checked = check_operator_output(case["base_mission_id"], case["input_payload"], deliverable)
    return {
        "conformant": bool(checked.passed),
        "failed_invariants": list(checked.failed_invariant_ids),
    }


def _failure_record(
    case: Mapping[str, Any],
    scaffold: str,
    receipt: Mapping[str, Any],
    *,
    status: str,
    invariant: str,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "deliverable": None,
        "model_id": MODEL_ID,
        "outcome": {"conformant": False, "failed_invariants": [invariant]},
        "route_receipt": {
            "models": [receipt.get("model")],
            "platforms": [receipt.get("routed_platform")],
            "providers": [receipt.get("provider")],
            "routed_models": [receipt.get("routed_model")],
            "response_ids": [receipt.get("id")],
        },
        "scaffold": scaffold,
        "status": status,
        "tool_receipt": {"calls": 0},
        "usage": {
            "completion_tokens": receipt.get("completion_tokens", 0),
            "prompt_tokens": receipt.get("prompt_tokens", 0),
        },
    }


def run_case(
    case: Mapping[str, Any],
    expected: Mapping[str, Any],
    scaffold: str,
    api_key: str,
) -> dict[str, Any]:
    prompt = initial_prompt(case, expected, scaffold)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    first_payload = _base_payload(
        messages, case_id=case["case_id"], scaffold=scaffold, stage="tool"
    )
    first_payload.update({"max_tokens": 256, "tool_choice": "required"})
    first = post_completion(payload=first_payload, api_key=api_key)
    first_message = _response_message(first)
    first_receipt = _receipt(first)
    tool_calls = first_message.get("tool_calls")
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        return _failure_record(
            case,
            scaffold,
            first_receipt,
            status="agent_tool_contract_failure",
            invariant="tool-contract",
        )
    tool_call = tool_calls[0]
    function = tool_call.get("function") if isinstance(tool_call, dict) else None
    if (
        not isinstance(function, dict)
        or function.get("name") != "read_case"
        or not _empty_tool_arguments(function.get("arguments"))
        or not tool_call.get("id")
    ):
        return _failure_record(
            case,
            scaffold,
            first_receipt,
            status="agent_tool_contract_failure",
            invariant="tool-contract",
        )
    assistant_message = {
        "role": "assistant",
        "content": first_message.get("content"),
        "tool_calls": tool_calls,
    }
    messages.extend(
        [
            assistant_message,
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": "read_case",
                "content": json.dumps(
                    case["input_payload"], ensure_ascii=False, separators=(",", ":")
                ),
            },
        ]
    )
    second_payload = _base_payload(
        messages, case_id=case["case_id"], scaffold=scaffold, stage="final"
    )
    second_payload.update(
        {
            "max_tokens": 3000,
            "response_format": {"type": "json_object"},
            "tool_choice": "none",
        }
    )
    second = post_completion(payload=second_payload, api_key=api_key)
    second_message = _response_message(second)
    second_receipt = _receipt(second)
    deliverable = _parse_json_object(second_message.get("content"))
    outcome = (
        domain_grade(case, deliverable)
        if deliverable is not None
        else {"conformant": False, "failed_invariants": ["json-output-contract"]}
    )
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "deliverable": deliverable,
        "model_id": MODEL_ID,
        "outcome": outcome,
        "prompt_sha256": sha256_bytes(canonical_bytes(messages[:2])),
        "route_receipt": {
            "models": [first_receipt["model"], second_receipt["model"]],
            "platforms": [
                first_receipt["routed_platform"],
                second_receipt["routed_platform"],
            ],
            "providers": [first_receipt["provider"], second_receipt["provider"]],
            "routed_models": [
                first_receipt["routed_model"],
                second_receipt["routed_model"],
            ],
            "response_ids": [first_receipt["id"], second_receipt["id"]],
        },
        "scaffold": scaffold,
        "status": "answered",
        "tool_receipt": {
            "arguments": {},
            "calls": 1,
            "input_sha256": case["input_sha256"],
            "name": "read_case",
        },
        "usage": {
            "completion_tokens": first_receipt["completion_tokens"]
            + second_receipt["completion_tokens"],
            "prompt_tokens": first_receipt["prompt_tokens"] + second_receipt["prompt_tokens"],
        },
    }


def _load_frame(path: Path) -> dict[str, Any]:
    frame = json.loads(path.read_text(encoding="utf-8"))
    builder.validate_frame(frame)
    if frame["model_route"]["id"] != MODEL_ID:
        raise ValueError("frame model route drifted")
    if frame["model_route"]["transport"]["base_url"] != TRANSPORT_BASE_URL:
        raise ValueError("configured transport base URL drifted from the frame")
    return frame


def _expected(case: Mapping[str, Any]) -> dict[str, Any]:
    expected = derive_operator_output(case["base_mission_id"], case["input_payload"])
    if sha256_bytes(canonical_bytes(expected)) != case["competence_gate"]["expected_sha256"]:
        raise ValueError(f"expected output drifted for {case['case_id']}")
    return expected


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from error
        if not isinstance(record, dict):
            raise TypeError(f"{path}:{line_number}: record must be an object")
        records.append(record)
    return records


def _record_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("case_id")), str(record.get("scaffold"))


def _run(
    *,
    cases: list[dict[str, Any]],
    examples: Mapping[str, dict[str, Any]],
    scaffolds: list[str],
    output: Path,
    api_key: str,
    concurrency: int,
) -> None:
    existing = _load_records(output)
    settled = {_record_key(record) for record in existing}
    pending = [
        ({**case, "worked_example": examples[case["category"]]}, scaffold)
        for scaffold in scaffolds
        for case in cases
        if (case["case_id"], scaffold) not in settled
    ]
    click.echo(
        f"planned={len(cases) * len(scaffolds)} settled={len(settled)} pending={len(pending)}"
    )
    if not pending:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    counts = Counter()
    with output.open("a", encoding="utf-8") as handle:

        def work(item: tuple[dict[str, Any], str]) -> None:
            case, scaffold = item
            try:
                record = run_case(case, _expected(case), scaffold, api_key)
            except TransportOrRouteError as error:
                record = {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "deliverable": None,
                    "error": str(error),
                    "model_id": MODEL_ID,
                    "outcome": None,
                    "scaffold": scaffold,
                    "status": "transport_or_route_error",
                    "usage": None,
                }
            record["recorded_at"] = datetime.now(UTC).isoformat()
            with lock:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                counts[record["status"]] += 1
                completed = sum(counts.values())
                if completed % 10 == 0 or completed == len(pending):
                    click.echo(f"{completed}/{len(pending)} {dict(counts)}", err=True)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(work, pending))


def _artifact(
    *,
    phase: str,
    frame: Mapping[str, Any],
    records: list[dict[str, Any]],
    scaffold: str | None,
) -> dict[str, Any]:
    expected_count = 20 * len(SCAFFOLDS) if phase == "pilot" else 70
    expected_keys = (
        {(case["case_id"], candidate) for candidate in SCAFFOLDS for case in frame["pilot_cases"]}
        if phase == "pilot"
        else {(case["case_id"], scaffold) for case in frame["main_cases"]}
    )
    latest = {_record_key(record): record for record in records}
    if set(latest) != expected_keys or len(latest) != expected_count:
        raise ValueError(f"{phase} log is incomplete or contains off-frame records")
    if any(
        not isinstance((record.get("outcome") or {}).get("conformant"), bool)
        for record in latest.values()
    ):
        raise ValueError(f"{phase} contains transport/route outcomes and cannot be frozen")
    cases = {
        case["case_id"]: case
        for case in (frame["pilot_cases"] if phase == "pilot" else frame["main_cases"])
    }
    for record in latest.values():
        case = cases[record["case_id"]]
        receipt = record.get("route_receipt") or {}
        models = receipt.get("models")
        platforms = receipt.get("platforms")
        providers = receipt.get("providers")
        routed_models = receipt.get("routed_models")
        if (
            not isinstance(models, list)
            or not models
            or any(model != MODEL_ID for model in models)
            or not isinstance(providers, list)
            or len(providers) != len(models)
            or any(provider != PROVIDER for provider in providers)
            or platforms != ["openrouter"] * len(models)
            or routed_models != [MODEL_ID] * len(models)
        ):
            raise ValueError(f"{phase} record route/provider drifted")
        calls = (record.get("tool_receipt") or {}).get("calls")
        if record.get("status") == "agent_tool_contract_failure":
            if len(models) != 1 or calls != 0:
                raise ValueError(f"{phase} tool-contract failure receipt is malformed")
        elif len(models) != 2 or calls != 1:
            raise ValueError(f"{phase} answered record lacks exact two-call tool receipt")
        if (
            calls == 1
            and (record.get("tool_receipt") or {}).get("input_sha256") != case["input_sha256"]
        ):
            raise ValueError(f"{phase} tool receipt is detached from its frozen case")
    ordered = [latest[key] for key in sorted(latest)]
    prompt_tokens = sum(record["usage"]["prompt_tokens"] for record in ordered)
    completion_tokens = sum(record["usage"]["completion_tokens"] for record in ordered)
    artifact: dict[str, Any] = {
        "claim_ceiling": frame["claim_ceiling"],
        "frame_payload_sha256": frame["payload_sha256"],
        "model_id": MODEL_ID,
        "phase": phase,
        "records": ordered,
        "schema_version": f"alljobs.predictive-validity-successor-{phase}.v1",
        "selected_scaffold": scaffold,
        "usage": {
            "completion_tokens": completion_tokens,
            "estimated_cost_usd": round(
                prompt_tokens * 0.0000003 + completion_tokens * 0.0000025, 8
            ),
            "prompt_tokens": prompt_tokens,
            "requests": sum(
                len(record.get("route_receipt", {}).get("response_ids", [])) for record in ordered
            ),
        },
    }
    if phase == "pilot":
        artifact["pilot_decision"] = builder.select_scaffold(ordered)
    else:
        failures = sum(not record["outcome"]["conformant"] for record in ordered)
        artifact["instrument_range"] = {
            "decision": "ANALYZE" if 14 <= failures <= 28 else "HOLD_INSTRUMENT_RANGE_MISS",
            "failures": failures,
            "passes": 70 - failures,
            "target": [14, 28],
        }
    artifact["payload_sha256"] = builder.payload_hash(artifact)
    return artifact


@click.group()
def cli() -> None:
    """Run and freeze the successor pilot/main records."""


@cli.command("run-pilot")
@click.option("--frame", default=DEFAULT_FRAME, type=click.Path(path_type=Path))
@click.option("--output", default=DEFAULT_PILOT_LOG, type=click.Path(path_type=Path))
@click.option("--concurrency", default=8, show_default=True, type=click.IntRange(1, 16))
def run_pilot_command(frame: Path, output: Path, concurrency: int) -> None:
    frozen = _load_frame(frame)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise click.ClickException("OPENROUTER_API_KEY is not set")
    _run(
        cases=frozen["pilot_cases"],
        examples=frozen["category_worked_examples"],
        scaffolds=list(SCAFFOLDS),
        output=output,
        api_key=key,
        concurrency=concurrency,
    )


@cli.command("freeze-pilot")
@click.option("--frame", default=DEFAULT_FRAME, type=click.Path(path_type=Path))
@click.option("--input", "input_path", default=DEFAULT_PILOT_LOG, type=click.Path(path_type=Path))
@click.option("--output", default=DEFAULT_PILOT, type=click.Path(path_type=Path))
def freeze_pilot_command(frame: Path, input_path: Path, output: Path) -> None:
    frozen = _load_frame(frame)
    artifact = _artifact(
        phase="pilot", frame=frozen, records=_load_records(input_path), scaffold=None
    )
    result = builder.freeze_json(output, artifact)
    click.echo(
        f"{result}: {output} decision={artifact['pilot_decision']['decision']} "
        f"selected={artifact['pilot_decision']['selected_scaffold']}"
    )


@cli.command("run-main")
@click.option("--frame", default=DEFAULT_FRAME, type=click.Path(path_type=Path))
@click.option("--pilot", default=DEFAULT_PILOT, type=click.Path(path_type=Path))
@click.option("--output", default=DEFAULT_MAIN_LOG, type=click.Path(path_type=Path))
@click.option("--concurrency", default=8, show_default=True, type=click.IntRange(1, 16))
def run_main_command(frame: Path, pilot: Path, output: Path, concurrency: int) -> None:
    frozen = _load_frame(frame)
    pilot_artifact = json.loads(pilot.read_text(encoding="utf-8"))
    if pilot_artifact.get("payload_sha256") != builder.payload_hash(pilot_artifact):
        raise click.ClickException("pilot payload hash mismatch")
    if pilot_artifact.get("frame_payload_sha256") != frozen["payload_sha256"]:
        raise click.ClickException("pilot is not bound to this frame")
    decision = pilot_artifact.get("pilot_decision") or {}
    if decision.get("decision") != "PROCEED_MAIN" or not decision.get("selected_scaffold"):
        raise click.ClickException("pilot did not authorise the main run")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise click.ClickException("OPENROUTER_API_KEY is not set")
    _run(
        cases=frozen["main_cases"],
        examples=frozen["category_worked_examples"],
        scaffolds=[decision["selected_scaffold"]],
        output=output,
        api_key=key,
        concurrency=concurrency,
    )


@cli.command("freeze-main")
@click.option("--frame", default=DEFAULT_FRAME, type=click.Path(path_type=Path))
@click.option("--pilot", default=DEFAULT_PILOT, type=click.Path(path_type=Path))
@click.option("--input", "input_path", default=DEFAULT_MAIN_LOG, type=click.Path(path_type=Path))
@click.option("--output", default=DEFAULT_MAIN, type=click.Path(path_type=Path))
def freeze_main_command(frame: Path, pilot: Path, input_path: Path, output: Path) -> None:
    frozen = _load_frame(frame)
    pilot_artifact = json.loads(pilot.read_text(encoding="utf-8"))
    if pilot_artifact.get("payload_sha256") != builder.payload_hash(pilot_artifact):
        raise click.ClickException("pilot payload hash mismatch")
    scaffold = (pilot_artifact.get("pilot_decision") or {}).get("selected_scaffold")
    if not scaffold:
        raise click.ClickException("pilot did not select a scaffold")
    artifact = _artifact(
        phase="main",
        frame=frozen,
        records=_load_records(input_path),
        scaffold=scaffold,
    )
    result = builder.freeze_json(output, artifact)
    click.echo(
        f"{result}: {output} decision={artifact['instrument_range']['decision']} "
        f"failures={artifact['instrument_range']['failures']}"
    )


if __name__ == "__main__":
    cli()
