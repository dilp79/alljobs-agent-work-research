---
creator: codex
purpose: Successor transport contract after the direct OpenRouter authentication gate failed.
why: Use the configured local OpenRouter proxy without weakening exact model, provider, budget, or inferential gates.
version: 2
updated: 2026-08-12
---

# Predictive-validity successor v2

All scientific, competence, pilot, budget, analysis, and claim-ceiling rules from
`predictive-validity-successor-v1.md` remain unchanged. V2 changes only the authenticated transport
and uses a new immutable frame and run paths.

## V1 stop receipt

V1 sent its preregistered 80 pilot case-runs to the direct `openrouter.ai` endpoint. Every request
returned the same HTTP 401 before any model response because the environment's
`OPENROUTER_API_KEY` is scoped to the configured local proxy, not direct OpenRouter. The machine
receipt is
`workforce-graph/data/predictive_validity/successor_2026-08-12/v1-stop.json`. It records zero agent
outcomes and zero observed model responses; token/cost authority is unknown. HTTP 401 is not an
agent failure and no V1 pilot decision exists.

## V2 transport

The V2 frame is
`workforce-graph/data/predictive_validity/successor_2026-08-12-v2/frame.json`. It additionally binds
the configured `http://localhost:3001/v1` model catalog, where the exact
`google/gemini-3.5-flash-lite` route is owned by `openrouter`.

Every successful response must still prove all four identities:

- top-level response model equals `google/gemini-3.5-flash-lite`;
- `_routed_via.platform` equals `openrouter`;
- `_routed_via.model` equals `google/gemini-3.5-flash-lite`; and
- top-level provider equals `Google AI Studio`, requested with fallback disabled.

Any missing or different receipt remains `HOLD_ROUTE_OR_TRANSPORT`, not an outcome. V2 writes new
pilot/main logs and artifacts; it never overwrites V1 evidence.

## V2 result

The exact route and tool-use gates passed for all 80 pilot observations (160 requests). Every one of
the 20 cases failed deterministic conformance under every schema-only scaffold, so the frozen pilot
decision is `HOLD_INSTRUMENT_RANGE_MISS`; no V2 main call is authorised. The instrument supplied
shape but not the exact serialization semantics enforced by the checker. This is an instrument
failure, not evidence of general agent inability.

The pilot used 75,608 input and 11,746 output tokens, with catalog-price cost estimated at
$0.0520474. Its frozen artifact is
`workforce-graph/data/predictive_validity/successor_2026-08-12-v2/pilot.json`.
