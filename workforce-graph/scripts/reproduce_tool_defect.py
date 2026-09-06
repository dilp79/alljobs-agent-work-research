"""Export and replay original synthetic tools-by-defects results without model calls.

export reads a private frozen run and emits only original cases, terminal answer text,
numeric/status projections and the frozen pure calculation source. replay needs that public
package only. Neither command imports a live runner, transport, credential helper or network API.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import re
from decimal import Decimal
from pathlib import Path

SCHEMA = "alljobs.tool-defect-public.v1"
CEILING = (
    "finite original synthetic template suite; final-answer grading and projected accounting "
    "replay, not live-provider reproduction, occupational coverage, invoice, ROI or equivalence"
)
SOURCE_MEMBERS = ("source/cases.py", "source/tools.py", "source/analysis_core.py")
PACKAGE_MEMBERS = ("replay_inputs.json", "source_receipts.json", *SOURCE_MEMBERS)
AGENT_FAILURES = {
    "TRIAL_BUDGET_EXHAUSTED",
    "INPUT_BUDGET_EXHAUSTED",
    "TRIAL_DEADLINE_EXCEEDED",
    "TOOL_CALL_BUDGET_EXHAUSTED",
    "REQUEST_BUDGET_EXHAUSTED",
    "MALFORMED_TOOL_CALL",
    "UNAUTHORIZED_TOOL_CALL",
}
CODE = re.compile(r"[A-Z][A-Z0-9_]{0,199}\Z")


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(canonical(value))


def strict_load(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate package JSON member")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)


def read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or symlinked input: {path.name}")
    return strict_load(path.read_bytes())


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"unexpected or missing {label} fields")


def finite_number(value, label, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"invalid {label}")
    if value < 0 or not math.isfinite(value) or (integer and type(value) is not int):
        raise ValueError(f"invalid {label}")
    return value


def money(value):
    if not isinstance(value, str):
        raise TypeError("money must be a decimal string")
    result = Decimal(value)
    if not result.is_finite() or result < 0:
        raise ValueError("invalid monetary amount")
    return result


def screen(data):
    # No lossy sanitization: anything outside this original-synthetic publication boundary holds.
    for marker in (b"/ho" + b"me/", b"/tmp/", b".run/", b"Bearer ", b"sk-or-", b"sk-proj-"):
        if marker in data:
            raise ValueError("private path or credential-like material in public projection")


def extract_function(raw, name):
    source = raw.decode()
    found = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(found) != 1:
        raise ValueError(f"missing or ambiguous frozen function {name}")
    return ast.get_source_segment(source, found[0]) + "\n"


def calculation_sources(snapshot):
    cases = snapshot["cases.py"]
    tools = snapshot["tools.py"]
    # Keep reviewed original source, with no transport/import-closure expansion.
    for raw, allowed in (
        (cases, {"__future__", "copy", "hashlib", "json", "random", "typing"}),
        (tools, {"__future__", "copy"}),
    ):
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node, ast.Import):
                if any(alias.name not in allowed for alias in node.names):
                    raise ValueError("unapproved frozen source import")
            elif isinstance(node, ast.ImportFrom) and node.module not in allowed:
                raise ValueError("unapproved frozen source import")
    functions = {
        "summarize": extract_function(snapshot["analysis.py"], "summarize"),
        "strict_json": extract_function(snapshot["runner.py"], "strict_json"),
    }
    core = (
        "# Original pure functions extracted from the hash-bound run source snapshot.\n"
        "import json\nimport math\nimport random\nfrom decimal import Decimal\n"
        "FAMILIES = ('reconciliation', 'record_preparation', 'formal_rules')\n\n"
        + functions["strict_json"]
        + "\n"
        + functions["summarize"]
    ).encode()
    return dict(zip(SOURCE_MEMBERS, (cases, tools, core), strict=True)), {
        name: sha(text.encode()) for name, text in functions.items()
    }


def load_calculators(sources):
    modules = []
    for name in ("source/cases.py", "source/analysis_core.py"):
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader=None))
        exec(compile(sources[name], name, "exec"), module.__dict__)  # noqa: S102 - verified frozen original code
        modules.append(module)
    return modules


def frozen_snapshot(run, config):
    records = dict(config["implementation_sha256"])
    records.setdefault("scripts/tool_defect.py", config["driver_sha256"])
    by_name = {}
    for relative, expected in records.items():
        name = Path(relative).name
        path = run / "source_snapshot" / name
        if name in by_name or path.is_symlink() or not path.is_file():
            raise ValueError("missing, duplicate or symlinked source snapshot")
        raw = path.read_bytes()
        if sha(raw) != expected:
            raise ValueError("frozen source snapshot hash mismatch")
        by_name[name] = raw
    return by_name


def projection_route(route):
    fields = (
        "request_model",
        "response_model",
        "routed_via",
        "provider",
        "reasoning",
        "input_usd_per_million",
        "output_usd_per_million",
        "price_source",
    )
    return {field: route[field] for field in fields}


def journal(run, case, config, record, stage):
    suffix = f".attempt-{record['attempt_index']}" if "attempt_index" in record else ""
    name = f"{case['case_id']}.request-{record['request_index']}{suffix}.{stage}.json"
    value = read(run / name)
    if value["configuration_sha256"] != config["sha256"] or value["case_sha256"] != digest(case):
        raise ValueError("journal configuration/case authority mismatch")
    return value


def project_trial(run, case, result, config):
    identities = ("case_id", "base_id", "family", "partition", "defective", "tools_available")
    if any(result[key] != case[key] for key in identities):
        raise ValueError("result case identity mismatch")
    if result["route"] != config["route"] or result["limits"] != config["limits"]:
        raise ValueError("result frozen treatment mismatch")
    attempts = []
    for record in result["receipts"]:
        reserved = journal(run, case, config, record, "request_reserved")
        if digest(reserved["payload"]) != reserved["payload_sha256"]:
            raise ValueError("request payload hash mismatch")
        if reserved["payload_sha256"] != record["payload_sha256"]:
            raise ValueError("receipt/request hash mismatch")
        response = record.get("response")
        if response is not None:
            captured = journal(run, case, config, record, "response_received")
            if captured["response"] != response:
                raise ValueError("response journal mismatch")
        if "unknown_billing_reserved_usd" in record:
            failed = journal(run, case, config, record, "request_failed")
            if failed["unknown_billing_reserved_usd"] != record["unknown_billing_reserved_usd"]:
                raise ValueError("failure journal reservation mismatch")
        metered = "accounted_cost_usd" in record
        usage = response.get("usage", {}) if response else {}
        attempts.append(
            {
                "turn": record["request_index"],
                "attempt": record.get("attempt_index", 0),
                "response_received": response is not None,
                "validated_usage": metered,
                "input_tokens": usage["prompt_tokens"] if metered else None,
                "output_tokens": usage["completion_tokens"] if metered else None,
                "accounted_cost_usd": record.get("accounted_cost_usd", "0"),
                "unknown_billing_reserved_usd": record.get("unknown_billing_reserved_usd"),
                "broker_cost_usd": str(usage.get("cost", 0)) if response else None,
                "input_reserve": reserved["input_reserve"],
                "output_allowance": reserved["payload"]["max_tokens"],
                "cost_reserve_usd": reserved["cost_reserve_usd"],
                "returned_model": response.get("model") if response else None,
                "returned_provider": response.get("provider") if response else None,
                "http_status": record.get("http_status"),
                "retry_scheduled": record.get("retry_scheduled", False),
                "retry_wait_seconds": record.get("retry_wait_seconds"),
                "request_payload_sha256": record["payload_sha256"],
                "response_sha256": digest(response) if response else None,
            }
        )
    outcome, failure = result["outcome"], result["failure_code"]
    if outcome in ("infrastructure_error", "incomplete"):
        kind = (
            "infrastructure_error"
            if outcome == "infrastructure_error"
            else "aggregate_budget_refusal"
        )
        if outcome == "incomplete" and failure != "PRE_REQUEST_BUDGET_REFUSAL":
            raise ValueError("unknown incomplete classification")
        text = None
    elif failure in AGENT_FAILURES:
        kind, text = "agent_failure", None
    elif failure in (None, "MALFORMED_OUTPUT_JSON", "EXACT_DECISION_STATE_MISMATCH"):
        kind = "final_answer"
        if not result["receipts"] or "response" not in result["receipts"][-1]:
            raise ValueError("exact final response unavailable")
        message = result["receipts"][-1]["response"]["choices"][0]["message"]
        if message.get("tool_calls"):
            raise ValueError("tool response is not a terminal answer")
        text = message.get("content")
        if text is not None and not isinstance(text, str):
            raise ValueError("unsupported final content shape")
    else:
        raise ValueError("unknown terminal classification")
    return {
        "case_id": case["case_id"],
        "kind": kind,
        "final_answer_text": text,
        "final_answer_sha256": sha(text.encode()) if text is not None else None,
        "failure_code": failure,
        "attempts": attempts,
        "tool_calls": [{"name": c["name"], "error": c["error"]} for c in result["tool_calls"]],
        "latency_ms": result["latency_ms"],
        "recorded": {
            key: result[key]
            for key in (
                "answer",
                "metrics",
                "outcome",
                "accounted_cost_usd",
                "input_tokens",
                "output_tokens",
                "requests",
                "agent_turns",
                "unknown_usage_attempts",
                "usage_tokens_complete",
            )
        },
        "private_result_sha256": digest(result),
    }


def project_run(run):
    config = read(run / "configuration.json")
    if digest({k: v for k, v in config.items() if k != "sha256"}) != config["sha256"]:
        raise ValueError("configuration hash mismatch")
    suite = read(run / "suite.json")
    if suite["sha256"] != config["suite_sha256"]:
        raise ValueError("suite/configuration mismatch")
    snapshot = frozen_snapshot(run, config)
    sources, functions = calculation_sources(snapshot)
    cases_module, core = load_calculators(sources)
    cases_module.verify_suite(suite)
    protocol_files = [
        p
        for p in (run / "source_snapshot").glob("*.md")
        if sha(p.read_bytes()) == config["protocol_sha256"]
    ]
    if len(protocol_files) != 1:
        raise ValueError("frozen protocol unavailable")
    plan_sha = None
    if suite["partition"] == "main":
        plan = read(run / "main-plan.json")
        if digest({k: v for k, v in plan.items() if k != "sha256"}) != plan["sha256"]:
            raise ValueError("main plan hash mismatch")
        if suite["pilot_freeze_sha256"] != plan["sha256"]:
            raise ValueError("main plan/suite mismatch")
        if plan["status"] != "FROZEN":
            raise ValueError("main plan is not frozen")
        for key in (
            "route",
            "limits",
            "budget_usd",
            "protocol_sha256",
            "implementation_sha256",
            "request_interval_seconds",
            "max_transient_retries",
        ):
            if plan[key] != config[key]:
                raise ValueError("main plan/configuration binding mismatch")
        if plan["case_inventory_sha256"] != digest(suite["cases"]):
            raise ValueError("main inventory mismatch")
        plan_sha = plan["sha256"]
    known = {c["case_id"] for c in suite["cases"]}
    if len(known) != len(suite["cases"]):
        raise ValueError("duplicate suite case")
    result_ids = {p.name.removesuffix(".result.json") for p in run.glob("*.result.json")}
    if result_ids - known:
        raise ValueError("unexpected result case")
    rows, raw_results = [], []
    for case in suite["cases"]:
        case_id = case["case_id"]
        if case_id not in result_ids:
            if list(run.glob(case_id + ".*")):
                raise ValueError("started case lacks final durable result")
            rows.append({"case_id": case_id, "kind": "not_started"})
            continue
        result = read(run / f"{case_id}.result.json")
        trial = read(run / f"{case_id}.trial.json")
        if trial["raw_result_checksum"] != digest(result):
            raise ValueError("TaskTrial/result checksum mismatch")
        if read(run / f"{case_id}.input.json") != case:
            raise ValueError("trial input differs from frozen suite")
        rows.append(project_trial(run, case, result, config))
        raw_results.append(result)
    package = {
        "schema_version": SCHEMA,
        "claim_ceiling": CEILING,
        "evidence_mode": config["evidence_mode"],
        "suite": suite,
        "design": {
            "route": projection_route(config["route"]),
            "limits": config["limits"],
            "budget_usd": config["budget_usd"],
            "request_interval_seconds": config["request_interval_seconds"],
            "max_transient_retries": config["max_transient_retries"],
        },
        "trials": rows,
    }
    receipts = {
        "schema_version": SCHEMA,
        "private_configuration_sha256": config["sha256"],
        "private_plan_sha256": plan_sha,
        "private_protocol_sha256": config["protocol_sha256"],
        "private_source_hashes": {name: sha(raw) for name, raw in snapshot.items()},
        "extracted_function_hashes": functions,
        "projection_is_identical_to_private_configuration": False,
        "provenance_ceiling": "opaque private-source hashes; public replay does not reconstruct raw transcripts or verify upstream invoices",
        "members": {
            "replay_inputs.json": sha(canonical(package)),
            **{name: sha(raw) for name, raw in sources.items()},
        },
    }
    summary, _ = calculate(package, sources)
    private_summary = core.summarize(raw_results, len(suite["cases"]))
    if summary != private_summary:
        raise ValueError("public/private analytical projection parity failed")
    recorded_summary = read(run / "summary.json")
    if recorded_summary != {
        **private_summary,
        "evidence_mode": config["evidence_mode"],
        "configuration_sha256": config["sha256"],
    }:
        raise ValueError("frozen private summary differs from full recomputation")
    receipts["private_summary_sha256"] = digest(recorded_summary)
    receipts["all_private_summary_fields_recomputed_equal"] = True
    return package, receipts, sources


def calculate(package, sources):
    exact_keys(
        package,
        ("schema_version", "claim_ceiling", "evidence_mode", "suite", "design", "trials"),
        "package",
    )
    if package["schema_version"] != SCHEMA or package["claim_ceiling"] != CEILING:
        raise ValueError("unknown package contract")
    if package["evidence_mode"] not in ("fixture", "live"):
        raise ValueError("unknown evidence mode")
    exact_keys(
        package["design"],
        ("route", "limits", "budget_usd", "request_interval_seconds", "max_transient_retries"),
        "design",
    )
    route = package["design"]["route"]
    exact_keys(
        route,
        (
            "request_model",
            "response_model",
            "routed_via",
            "provider",
            "reasoning",
            "input_usd_per_million",
            "output_usd_per_million",
            "price_source",
        ),
        "route",
    )
    input_rate = money(route["input_usd_per_million"])
    output_rate = money(route["output_usd_per_million"])

    def priced(inputs, outputs):
        return (inputs * input_rate + outputs * output_rate) / 1000000

    cases_module, core = load_calculators(sources)
    suite = package["suite"]
    cases_module.verify_suite(suite)
    ids = [r["case_id"] for r in package["trials"]]
    if len(set(ids)) != len(ids) or ids != [c["case_id"] for c in suite["cases"]]:
        raise ValueError("duplicate, missing or reordered planned case inventory")
    results, table = [], []
    for case, row in zip(suite["cases"], package["trials"], strict=True):
        if row["kind"] == "not_started":
            exact_keys(row, ("case_id", "kind"), "not-started")
            table.append(
                {
                    **{
                        key: case[key]
                        for key in ("case_id", "base_id", "family", "defective", "tools_available")
                    },
                    "kind": "not_started",
                    "exact_correct": None,
                }
            )
            continue
        exact_keys(
            row,
            (
                "case_id",
                "kind",
                "final_answer_text",
                "final_answer_sha256",
                "failure_code",
                "attempts",
                "tool_calls",
                "latency_ms",
                "recorded",
                "private_result_sha256",
            ),
            "trial",
        )
        answer = None
        text = row["final_answer_text"]
        if text is not None and not isinstance(text, str):
            raise ValueError("answer text must be string or null")
        if row["final_answer_sha256"] != (sha(text.encode()) if text is not None else None):
            raise ValueError("terminal text checksum mismatch")
        failure = row["failure_code"]
        if failure is not None and (not isinstance(failure, str) or not CODE.fullmatch(failure)):
            raise ValueError("unrecognized typed termination code")
        kind = row["kind"]
        if kind == "final_answer":
            try:
                answer = core.strict_json(text or "")
                metrics = cases_module.grade(case, answer)
                computed_failure = (
                    None if metrics["exact_correct"] else "EXACT_DECISION_STATE_MISMATCH"
                )
            except ValueError, TypeError:
                computed_failure = "MALFORMED_OUTPUT_JSON"
            metrics = cases_module.grade(case, answer)
            outcome = "pass" if metrics["exact_correct"] else "fail"
            if failure != computed_failure:
                raise ValueError("terminal parser classification mismatch")
        elif kind == "agent_failure":
            if failure not in AGENT_FAILURES or text is not None:
                raise ValueError("invalid agent failure")
            outcome, metrics = "fail", cases_module.grade(case, None)
        elif kind in ("infrastructure_error", "aggregate_budget_refusal"):
            if not failure or text is not None:
                raise ValueError("invalid unavailable outcome")
            if kind == "aggregate_budget_refusal" and failure != "PRE_REQUEST_BUDGET_REFUSAL":
                raise ValueError("invalid aggregate budget outcome")
            outcome = "incomplete" if kind == "aggregate_budget_refusal" else "infrastructure_error"
            metrics = {key: None for key in cases_module.grade(case, None)}
        else:
            raise ValueError("unknown trial kind")
        inputs = outputs = unknown = 0
        cost = Decimal(0)
        projected_receipts, seen_attempts = [], set()
        for attempt in row["attempts"]:
            exact_keys(
                attempt,
                (
                    "turn",
                    "attempt",
                    "response_received",
                    "validated_usage",
                    "input_tokens",
                    "output_tokens",
                    "accounted_cost_usd",
                    "unknown_billing_reserved_usd",
                    "broker_cost_usd",
                    "http_status",
                    "retry_scheduled",
                    "retry_wait_seconds",
                    "request_payload_sha256",
                    "response_sha256",
                    "input_reserve",
                    "output_allowance",
                    "cost_reserve_usd",
                    "returned_model",
                    "returned_provider",
                ),
                "attempt",
            )
            pair = (
                finite_number(attempt["turn"], "turn", integer=True),
                finite_number(attempt["attempt"], "attempt", integer=True),
            )
            if pair in seen_attempts:
                raise ValueError("duplicate request attempt")
            seen_attempts.add(pair)
            if any(
                type(attempt[key]) is not bool
                for key in ("response_received", "validated_usage", "retry_scheduled")
            ):
                raise ValueError("attempt flags require booleans")
            if attempt["validated_usage"]:
                if not attempt["response_received"]:
                    raise ValueError("usage without response")
                inputs += finite_number(attempt["input_tokens"], "input tokens", integer=True)
                outputs += finite_number(attempt["output_tokens"], "output tokens", integer=True)
                expected_cost = max(
                    priced(attempt["input_tokens"], attempt["output_tokens"]),
                    money(attempt["broker_cost_usd"])
                    if attempt["broker_cost_usd"] is not None
                    else Decimal(0),
                )
                if money(attempt["accounted_cost_usd"]) != expected_cost:
                    raise ValueError("metered cost/rates mismatch")
            elif attempt["input_tokens"] is not None or attempt["output_tokens"] is not None:
                raise ValueError("unknown usage must remain null")
            cost += money(attempt["accounted_cost_usd"])
            reserve = priced(
                finite_number(attempt["input_reserve"], "input reserve", integer=True),
                finite_number(attempt["output_allowance"], "output allowance", integer=True),
            )
            if money(attempt["cost_reserve_usd"]) != reserve:
                raise ValueError("request reservation/rates mismatch")
            receipt = {}
            if attempt["unknown_billing_reserved_usd"] is not None:
                unknown += 1
                if money(attempt["unknown_billing_reserved_usd"]) != reserve:
                    raise ValueError("unknown usage reservation mismatch")
                cost += money(attempt["unknown_billing_reserved_usd"])
                receipt["unknown_billing_reserved_usd"] = attempt["unknown_billing_reserved_usd"]
            if attempt["broker_cost_usd"] is not None:
                money(attempt["broker_cost_usd"])
                receipt["response"] = {"usage": {"cost": attempt["broker_cost_usd"]}}
            projected_receipts.append(receipt)
        finite_number(row["latency_ms"], "latency")
        for call in row["tool_calls"]:
            exact_keys(call, ("name", "error"), "tool count")
            if not isinstance(call["name"], str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]{0,99}", call["name"]
            ):
                raise ValueError("unrecognized projected tool")
            if call["error"] is not None and not re.fullmatch(r"[A-Za-z]+Error", call["error"]):
                raise ValueError("invalid projected tool error")
        result = {
            key: case[key]
            for key in ("case_id", "base_id", "family", "partition", "defective", "tools_available")
        }
        result.update(
            answer=answer,
            metrics=metrics,
            outcome=outcome,
            failure_code=failure,
            accounted_cost_usd=str(cost),
            input_tokens=inputs,
            output_tokens=outputs,
            requests=len(row["attempts"]),
            agent_turns=len({p[0] for p in seen_attempts}),
            unknown_usage_attempts=unknown,
            usage_tokens_complete=unknown == 0,
            tool_calls=row["tool_calls"],
            receipts=projected_receipts,
            latency_ms=row["latency_ms"],
        )
        exact_keys(
            row["recorded"],
            (
                "answer",
                "metrics",
                "outcome",
                "accounted_cost_usd",
                "input_tokens",
                "output_tokens",
                "requests",
                "agent_turns",
                "unknown_usage_attempts",
                "usage_tokens_complete",
            ),
            "recorded outcome",
        )
        if canonical(row["recorded"]) != canonical({key: result[key] for key in row["recorded"]}):
            raise ValueError("recomputed trial differs from private recorded outcome/accounting")
        results.append(result)
        table.append(
            {
                **{
                    key: case[key]
                    for key in ("case_id", "base_id", "family", "defective", "tools_available")
                },
                "kind": kind,
                "exact_correct": metrics["exact_correct"],
                "outcome": outcome,
                "failure_code": failure,
                "input_tokens": inputs,
                "output_tokens": outputs,
                "accounted_cost_usd": str(cost),
            }
        )
    return core.summarize(results, len(suite["cases"])), table


def write_files(output, files):
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing existing output")
    for raw in files.values():
        screen(raw)
    output.mkdir(parents=True)
    for name, raw in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)


def export_run(run, output, plot=False):
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing existing output")
    if run.resolve() == output.resolve() or run.resolve() in output.resolve().parents:
        raise ValueError("public export must be outside the private run")
    package, receipts, sources = project_run(run)
    write_files(
        output,
        {
            "replay_inputs.json": canonical(package),
            "source_receipts.json": canonical(receipts),
            **sources,
        },
    )
    return replay(output, output / "reproduced", plot=plot)


def figure(package, summary, rows):
    import io
    import random

    import matplotlib

    if matplotlib.__version__ != "3.10.8":
        raise ValueError("plotting requires matplotlib==3.10.8")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"svg.hashsalt": "alljobs-tool-defect-v1", "font.family": "DejaVu Sans"})
    cases = {c["case_id"]: c for c in package["suite"]["cases"]}
    by_base = {}
    cost = {False: Decimal(0), True: Decimal(0)}
    for row in rows:
        case = cases[row["case_id"]]
        by_base.setdefault(case["base_id"], {})[(case["defective"], case["tools_available"])] = row
        cost[case["tools_available"]] += Decimal(row.get("accounted_cost_usd", "0"))
    labels = ["Equal-family primary"]
    values = [
        (
            summary["primary_equal_family_paired_difference"],
            summary["stratified_base_bootstrap_95"],
            summary["n_complete_paired_bases"],
        )
    ]
    rng = random.Random(20260906)
    for family in ("reconciliation", "record_preparation", "formal_rules"):
        diffs = []
        for base_id, cells in by_base.items():
            if not any(c["base_id"] == base_id and c["family"] == family for c in cases.values()):
                continue
            if len(cells) != 4 or any(c["exact_correct"] is None for c in cells.values()):
                continue
            diffs.append(
                sum(
                    int(cells[d, True]["exact_correct"]) - int(cells[d, False]["exact_correct"])
                    for d in (False, True)
                )
                / 2
            )
        point = sum(diffs) / len(diffs) if diffs else None
        ci = None
        if len(diffs) >= 2:
            boot = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(4000))
            ci = [boot[100], boot[3899]]
        labels.append(family.replace("_", " ").capitalize())
        values.append((point, ci, len(diffs)))
    fig, ax = plt.subplots(figsize=(9, 4.8))
    bounds = [0.0]
    for point, ci, _ in values:
        if point is not None:
            bounds.extend(ci if ci is not None else [point])
    left, right = min(bounds) * 100 - 5, max(bounds) * 100 + 5
    span = right - left
    for i, (point, ci, n) in enumerate(values):
        if point is not None:
            ax.plot(point * 100, i, "o", color="#215f85", markersize=7)
            if ci:
                ax.plot([ci[0] * 100, ci[1] * 100], [i, i], color="#215f85", linewidth=2)
        ax.text(right + span * 0.03, i, f"{n} complete bases", va="center", fontsize=9)
    ax.axvline(0, color="#999999", linewidth=1)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_xlim(left, right + span * 0.45)
    step = 5 if span < 30 else 10
    ax.set_xticks(
        list(range(math.ceil(left / step) * step, math.floor(right / step) * step + 1, step))
    )
    ax.set_xlabel("Within-budget exact correctness: tools present − absent (percentage points)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(f"Tools × input defects · {package['evidence_mode'].upper()} evidence", loc="left")
    fig.text(
        0.03,
        0.13,
        f"Observed {summary['n_observed_trials']}/{summary['n_expected_trials']} trials. "
        f"Conservative accounted cost: absent USD {cost[False]:.4f}; present USD {cost[True]:.4f}.",
        fontsize=9,
    )
    fig.text(
        0.03,
        0.075,
        "Bars: descriptive 95% base bootstrap (4,000 draws); only complete four-cell bases.\n"
        "Degenerate intervals do not establish equivalence. Three synthetic templates; no occupational inference.",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.2, 1, 1))
    files = {}
    for extension in ("png", "svg"):
        buffer = io.BytesIO()
        metadata = (
            {"Date": None} if extension == "svg" else {"Software": "AllJobs tool-defect replay"}
        )
        fig.savefig(buffer, format=extension, dpi=160, metadata=metadata)
        files[f"figure_tool_effect.{extension}"] = buffer.getvalue()
    plt.close(fig)
    return files


def replay(package_path, output, plot=False):
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing existing output")
    receipts = read(package_path / "source_receipts.json")
    expected_names = {"replay_inputs.json", *SOURCE_MEMBERS}
    if set(receipts["members"]) != expected_names:
        raise ValueError("public source member allowlist mismatch")
    sources = {}
    for name, expected in receipts["members"].items():
        path = package_path / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("public source unavailable")
        raw = path.read_bytes()
        if sha(raw) != expected:
            raise ValueError("public member checksum mismatch")
        screen(raw)
        sources[name] = raw
    package = strict_load(sources.pop("replay_inputs.json"))
    summary, rows = calculate(package, sources)
    result = {
        "schema_version": SCHEMA,
        "claim_ceiling": CEILING,
        "evidence_mode": package["evidence_mode"],
        "summary": summary,
    }
    import csv
    import io

    def csv_bytes(rows):
        fields = list(dict.fromkeys(key for row in rows for key in row))
        handle = io.StringIO(newline="")
        writer = csv.DictWriter(handle, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return handle.getvalue().encode()

    cells = [{"cell": key, **value} for key, value in summary["cell_denominators"].items()]
    files = {
        "results.json": canonical(result),
        "trials.csv": csv_bytes(rows),
        "cells.csv": csv_bytes(cells),
    }
    if plot:
        files.update(figure(package, summary, rows))
    write_files(output, files)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--run", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--plot", action="store_true", help="Requires matplotlib==3.10.8")
    repeat = sub.add_parser("replay")
    repeat.add_argument("--package", type=Path, required=True)
    repeat.add_argument("--output", type=Path, required=True)
    repeat.add_argument("--plot", action="store_true", help="Requires matplotlib==3.10.8")
    args = parser.parse_args()
    result = (
        export_run(args.run, args.output, args.plot)
        if args.command == "export"
        else replay(args.package, args.output, args.plot)
    )
    print(
        json.dumps(
            {
                "command": args.command,
                "evidence_mode": result["evidence_mode"],
                "n_expected_trials": result["summary"]["n_expected_trials"],
                "model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
