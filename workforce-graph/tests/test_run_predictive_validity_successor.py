"""Exact-route tool harness for the predictive-validity successor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_predictive_validity_successor.py"
_spec = importlib.util.spec_from_file_location("run_predictive_validity_successor", SCRIPT)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _case() -> dict:
    expected = {
        "mission_id": "mission-1",
        "records": [{"id": "a", "value": 2}],
        "status": "ready",
    }
    input_payload = {"secret_case_value": "DO_NOT_LEAK_IN_INITIAL_PROMPT"}
    return {
        "case_id": "mission-1::dense_semantic_shift",
        "base_mission_id": "mission-1",
        "category": "record_preparation",
        "input_payload": input_payload,
        "input_sha256": runner.sha256_bytes(runner.canonical_bytes(input_payload)),
        "worked_example": {
            "input_payload": {"example_value": "EXAMPLE_ONLY"},
            "output_payload": {
                "mission_id": "example-mission",
                "records": [{"id": "example", "value": 7}],
                "status": "ready",
            },
        },
        "competence_gate": {
            "expected_sha256": runner.sha256_bytes(runner.canonical_bytes(expected))
        },
    }


def test_scaffolds_expose_shapes_but_never_case_or_answer_values() -> None:
    expected = {
        "mission_id": "mission-1",
        "records": [{"id": "alpha", "value": 42}],
        "status": "ready",
    }
    case = _case()
    for scaffold in runner.SCAFFOLDS:
        prompt = runner.initial_prompt(case, expected, scaffold)
        assert "DO_NOT_LEAK_IN_INITIAL_PROMPT" not in prompt
        assert "alpha" not in prompt
        assert "42" not in prompt
        assert "read_case" in prompt
        assert "mission_id" in prompt


def test_tool_contract_and_domain_outcome_are_separate(monkeypatch) -> None:
    case = _case()
    expected = {
        "mission_id": "mission-1",
        "records": [{"id": "a", "value": 2}],
        "status": "ready",
    }
    responses = iter(
        [
            {
                "id": "first",
                "model": runner.MODEL_ID,
                "provider": runner.PROVIDER,
                "_routed_via": {"platform": "openrouter", "model": runner.MODEL_ID},
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "read_case", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
            },
            {
                "id": "second",
                "model": runner.MODEL_ID,
                "provider": runner.PROVIDER,
                "_routed_via": {"platform": "openrouter", "model": runner.MODEL_ID},
                "usage": {"prompt_tokens": 30, "completion_tokens": 20},
                "choices": [{"message": {"role": "assistant", "content": json.dumps(expected)}}],
            },
        ]
    )
    monkeypatch.setattr(runner, "post_completion", lambda **_kwargs: next(responses))
    monkeypatch.setattr(
        runner,
        "domain_grade",
        lambda _case, deliverable: {
            "conformant": deliverable == expected,
            "failed_invariants": [],
        },
    )

    record = runner.run_case(
        case, expected, "worked_example_plus_recursive_shape", api_key="secret"
    )
    assert record["outcome"]["conformant"] is True
    assert record["tool_receipt"]["calls"] == 1
    assert record["route_receipt"]["models"] == [runner.MODEL_ID, runner.MODEL_ID]
    assert record["usage"]["prompt_tokens"] == 40
    assert record["deliverable"] == expected


def test_missing_tool_call_is_an_agent_failure_not_a_transport_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "post_completion",
        lambda **_kwargs: {
            "id": "first",
            "model": runner.MODEL_ID,
            "provider": runner.PROVIDER,
            "_routed_via": {"platform": "openrouter", "model": runner.MODEL_ID},
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            "choices": [{"message": {"role": "assistant", "content": "{}"}}],
        },
    )
    record = runner.run_case(_case(), {"mission_id": "mission-1"}, "worked_example", "secret")
    assert record["status"] == "agent_tool_contract_failure"
    assert record["outcome"] == {"conformant": False, "failed_invariants": ["tool-contract"]}
