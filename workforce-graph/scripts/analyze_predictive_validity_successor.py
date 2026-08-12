"""Execute the locked predictive-validity analysis after the main instrument gate.

The primary statistic is five-fold held-out log-loss improvement from adding the three frozen vote
doses to category and a preregistered scalar difficulty index.  Vote vectors are permuted jointly
within category.  The result is predictive association in this synthetic harness only.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import click

ROOT = Path(__file__).resolve().parent.parent

_builder_spec = importlib.util.spec_from_file_location(
    "build_predictive_validity_successor",
    Path(__file__).parent / "build_predictive_validity_successor.py",
)
builder = importlib.util.module_from_spec(_builder_spec)
_builder_spec.loader.exec_module(builder)

CATEGORY_ORDER = builder.CATEGORY_ORDER
DEFAULT_FRAME = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v3" / "frame.json"
DEFAULT_MAIN = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v3" / "main.json"
DEFAULT_OUTPUT = ROOT / "data" / "predictive_validity" / "successor_2026-08-12-v3" / "analysis.json"


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp = math.exp(-value)
        return 1.0 / (1.0 + exp)
    exp = math.exp(value)
    return exp / (1.0 + exp)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("logistic Hessian is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
                ]
    return [augmented[index][-1] for index in range(size)]


def _fit_logistic(
    features: list[list[float]], outcomes: list[int], *, ridge: float = 2.0
) -> list[float]:
    if not features or len(features) != len(outcomes):
        raise ValueError("logistic inputs are empty or misaligned")
    width = len(features[0])
    beta = [0.0] * width
    for _iteration in range(60):
        probabilities = [
            _sigmoid(sum(b * x for b, x in zip(beta, row, strict=True))) for row in features
        ]
        gradient = [0.0] * width
        hessian = [[0.0] * width for _ in range(width)]
        for row, outcome, probability in zip(features, outcomes, probabilities, strict=True):
            residual = probability - outcome
            weight = max(probability * (1.0 - probability), 1e-8)
            for left in range(width):
                gradient[left] += row[left] * residual
                for right in range(width):
                    hessian[left][right] += row[left] * row[right] * weight
        for index in range(1, width):
            gradient[index] += ridge * beta[index]
            hessian[index][index] += ridge
        delta = _solve(hessian, gradient)
        beta = [value - change for value, change in zip(beta, delta, strict=True)]
        if max(abs(change) for change in delta) < 1e-8:
            break
    return beta


def _fold(mission_id: str, category: str, category_index: int) -> int:
    digest = hashlib.sha256(f"{builder.FRAME_SEED}:cv:{category}:{mission_id}".encode()).hexdigest()
    return (int(digest[:8], 16) + category_index) % 5


def _feature_rows(
    train: list[Mapping[str, Any]],
    target: list[Mapping[str, Any]],
    *,
    include_votes: bool,
) -> tuple[list[list[float]], list[list[float]]]:
    numeric_names = ["difficulty_index"]
    if include_votes:
        numeric_names.extend(["can_do", "no_human_review", "requires_tool_access"])

    def raw(row: Mapping[str, Any], name: str) -> float:
        if name == "difficulty_index":
            return float(row[name])
        return float(row["vote_doses"][name])

    centers = {name: sum(raw(row, name) for row in train) / len(train) for name in numeric_names}
    scales = {}
    for name in numeric_names:
        variance = sum((raw(row, name) - centers[name]) ** 2 for row in train) / len(train)
        scales[name] = math.sqrt(variance) or 1.0

    def encode(row: Mapping[str, Any]) -> list[float]:
        category = row["category"]
        category_features = [
            1.0 if category == candidate else 0.0 for candidate in CATEGORY_ORDER[1:]
        ]
        numeric = [(raw(row, name) - centers[name]) / scales[name] for name in numeric_names]
        return [1.0, *category_features, *numeric]

    return [encode(row) for row in train], [encode(row) for row in target]


def cross_validated_log_loss(
    rows: list[Mapping[str, Any]], *, include_votes: bool
) -> dict[str, Any]:
    if len(rows) != 70 or len({row["base_mission_id"] for row in rows}) != 70:
        raise ValueError("analysis requires 70 independent mission clusters")
    fold_by_id: dict[str, int] = {}
    for category in CATEGORY_ORDER:
        category_rows = sorted(
            (row for row in rows if row["category"] == category),
            key=lambda row: hashlib.sha256(
                f"{builder.FRAME_SEED}:cv-order:{row['base_mission_id']}".encode()
            ).hexdigest(),
        )
        if len(category_rows) != 7:
            raise ValueError("cross-validation frame lost category balance")
        for category_index, row in enumerate(category_rows):
            fold_by_id[row["base_mission_id"]] = _fold(
                row["base_mission_id"], category, category_index
            )
    predictions: dict[str, float] = {}
    coefficients = []
    for fold in range(5):
        train = [row for row in rows if fold_by_id[row["base_mission_id"]] != fold]
        target = [row for row in rows if fold_by_id[row["base_mission_id"]] == fold]
        if not train or not target:
            raise ValueError("deterministic cross-validation produced an empty fold")
        train_x, target_x = _feature_rows(train, target, include_votes=include_votes)
        beta = _fit_logistic(train_x, [int(row["failure"]) for row in train])
        coefficients.append(beta)
        for row, features in zip(target, target_x, strict=True):
            predictions[row["base_mission_id"]] = _sigmoid(
                sum(value * feature for value, feature in zip(beta, features, strict=True))
            )
    losses = []
    for row in rows:
        probability = min(max(predictions[row["base_mission_id"]], 1e-12), 1 - 1e-12)
        outcome = int(row["failure"])
        losses.append(
            -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
        )
    return {
        "fold_coefficients": coefficients,
        "log_loss": sum(losses) / len(losses),
        "observations": len(rows),
        "predictions": predictions,
    }


def permute_votes_within_category(
    rows: list[Mapping[str, Any]], *, seed: str
) -> list[dict[str, Any]]:
    shuffled = [copy.deepcopy(dict(row)) for row in rows]
    generator = random.Random(seed)
    for category in CATEGORY_ORDER:
        indexes = [index for index, row in enumerate(shuffled) if row["category"] == category]
        vectors = [copy.deepcopy(shuffled[index]["vote_doses"]) for index in indexes]
        generator.shuffle(vectors)
        for index, vector in zip(indexes, vectors, strict=True):
            shuffled[index]["vote_doses"] = vector
    return shuffled


def analyze_rows(rows: list[Mapping[str, Any]], *, permutations: int = 1999) -> dict[str, Any]:
    failures = sum(bool(row["failure"]) for row in rows)
    if len(rows) != 70:
        raise ValueError("main analysis requires exactly 70 rows")
    if failures < 14 or failures > 28:
        return {
            "decision": "HOLD_INSTRUMENT_RANGE_MISS",
            "failure_count": failures,
            "predictive_analysis": None,
            "target_failure_count": [14, 28],
        }
    baseline = cross_validated_log_loss(rows, include_votes=False)
    augmented = cross_validated_log_loss(rows, include_votes=True)
    observed = baseline["log_loss"] - augmented["log_loss"]
    null_improvements = []
    for index in range(permutations):
        permuted = permute_votes_within_category(
            rows, seed=f"{builder.FRAME_SEED}:blocked-permutation:{index}"
        )
        permuted_augmented = cross_validated_log_loss(permuted, include_votes=True)
        null_improvements.append(baseline["log_loss"] - permuted_augmented["log_loss"])
    exceedances = sum(value >= observed - 1e-15 for value in null_improvements)
    p_value = (exceedances + 1) / (permutations + 1)
    association = observed > 0 and p_value <= 0.05
    return {
        "decision": (
            "INCREMENTAL_PREDICTIVE_ASSOCIATION"
            if association
            else "NO_DETECTED_INCREMENTAL_ASSOCIATION"
        ),
        "failure_count": failures,
        "predictive_analysis": {
            "augmented_log_loss": augmented["log_loss"],
            "baseline_log_loss": baseline["log_loss"],
            "blocked_permutation_exceedances": exceedances,
            "blocked_permutation_p_one_sided": p_value,
            "held_out_log_loss_improvement": observed,
            "permutations": permutations,
        },
        "target_failure_count": [14, 28],
    }


def _validate_payload(value: Mapping[str, Any], *, name: str) -> None:
    if value.get("payload_sha256") != builder.payload_hash(value):
        raise ValueError(f"{name} payload hash mismatch")


def rows_from_artifacts(frame: Mapping[str, Any], main: Mapping[str, Any]) -> list[dict[str, Any]]:
    builder.validate_frame(frame)
    _validate_payload(main, name="main")
    if main.get("frame_payload_sha256") != frame["payload_sha256"]:
        raise ValueError("main artifact is not bound to the frame")
    cases = {row["case_id"]: row for row in frame["main_cases"]}
    records = main.get("records")
    if not isinstance(records, list) or len(records) != 70:
        raise ValueError("main artifact does not contain 70 records")
    rows = []
    for record in records:
        case = cases.get(record.get("case_id"))
        if case is None:
            raise ValueError("main record is outside the frozen frame")
        outcome = record.get("outcome") or {}
        if not isinstance(outcome.get("conformant"), bool):
            raise TypeError("main record has no observed conformance outcome")
        receipt = record.get("route_receipt") or {}
        models = receipt.get("models")
        platforms = receipt.get("platforms")
        providers = receipt.get("providers")
        routed_models = receipt.get("routed_models")
        if (
            not isinstance(models, list)
            or not models
            or any(model != builder.MODEL_ID for model in models)
            or providers != ["Google AI Studio"] * len(models)
            or platforms != ["openrouter"] * len(models)
            or routed_models != [builder.MODEL_ID] * len(models)
        ):
            raise ValueError("main record route/provider identity drifted")
        calls = (record.get("tool_receipt") or {}).get("calls")
        if record.get("status") == "agent_tool_contract_failure":
            if len(models) != 1 or calls != 0:
                raise ValueError("main tool-contract failure receipt is malformed")
        elif len(models) != 2 or calls != 1:
            raise ValueError("main record lacks its exact tool-use receipt")
        rows.append(
            {
                "base_mission_id": case["base_mission_id"],
                "category": case["category"],
                "difficulty_index": case["difficulty_features"]["difficulty_index"],
                "failure": not outcome["conformant"],
                "vote_doses": case["vote_doses"],
            }
        )
    return rows


@click.command()
@click.option("--frame", default=DEFAULT_FRAME, type=click.Path(path_type=Path))
@click.option("--main", "main_path", default=DEFAULT_MAIN, type=click.Path(path_type=Path))
@click.option("--output", default=DEFAULT_OUTPUT, type=click.Path(path_type=Path))
def cli(frame: Path, main_path: Path, output: Path) -> None:
    frozen = json.loads(frame.read_text(encoding="utf-8"))
    main = json.loads(main_path.read_text(encoding="utf-8"))
    result = analyze_rows(rows_from_artifacts(frozen, main))
    artifact = {
        "claim_ceiling": frozen["claim_ceiling"],
        "decision": result["decision"],
        "frame_payload_sha256": frozen["payload_sha256"],
        "main_payload_sha256": main["payload_sha256"],
        "result": result,
        "schema_version": "alljobs.predictive-validity-successor-analysis.v1",
    }
    artifact["payload_sha256"] = builder.payload_hash(artifact)
    status = builder.freeze_json(output, artifact)
    click.echo(f"{status}: {output} decision={result['decision']}")


if __name__ == "__main__":
    cli()
