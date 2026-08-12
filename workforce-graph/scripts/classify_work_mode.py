"""Give every task statement one attribute: where the work physically happens.

Why this exists. The project publishes a share — how much of work is reachable by a
software agent. A share needs a denominator, and until now the denominator was the whole
corpus, which put bedside care, cooking and welding into a figure about work done at a
screen (prd.md 8.0b). The figure answered a question nobody asked.

The correct denominator is not a list of digital occupations. Almost every occupation has
a share of work done at a screen, and that share is the subject: for a nurse it is the
chart, the intake interview and the callbacks, not the bedside. So the split has to be
made per task statement, across all 18,796 of them, and that is what this script does.

What it does NOT ask. It does not ask whether software could do the task. That is the
separate, harder question the autonomy scoring answers. Mixing the two into one call would
make a task look physical because it is difficult, or digital because it is easy. Here the
only question is where the work happens.

Method notes, so the numbers stay comparable with the rest of the project:

  * One task per request. The same model re-reading the same task disagrees with itself on
    3.6% of pairs at one task per request and 28.1% at twenty (prd.md 9.1a). Batching is
    cheaper and produces a different measurement, so it is not used here.
  * Several models over the same corpus. A single rater's opinion has no error bar. Running
    the whole corpus through more than one model costs almost nothing on the free route and
    turns "the label" into "the label plus how much raters agree on it".
  * Repeats of one model over a subsample, to separate rater disagreement from a rater's
    disagreement with itself.
  * Resumable by construction. The run is long and unattended; it appends, and on restart
    it skips what is already written rather than starting over.

Usage:
    python scripts/classify_work_mode.py --model gemini-3.5-flash-lite
    python scripts/classify_work_mode.py --model gemini-3.5-flash-lite --limit 60
    python scripts/classify_work_mode.py --model deepseek-v4-pro --repeat 1
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import click
from openai import BadRequestError, OpenAI

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "work_mode" / "corpus.jsonl"
OUT_DIR = ROOT / "data" / "work_mode"

BASE_URL = os.environ.get("FREELLMAPI_BASE_URL", "http://localhost:3001/v1")
KEY_ENV = "FREELLMAPI_KEY"
TEMPERATURE = 0.0
MAX_RETRIES = 4
BATCH_SIZE = 1  # not a parameter; see the module docstring
RETRY_PASS_ENV = "ALLJOBS_WORK_MODE_RETRY_PASS"

MODES = ("screen", "mixed", "physical")
CHANNELS = ("text", "voice", "video", "none")

SYSTEM_PROMPT = """You classify work tasks by WHERE THE WORK PHYSICALLY HAPPENS.

You are given one task statement from the O*NET occupational database together with the
occupation it belongs to. Decide which of three modes it is.

"screen" — the whole task can be carried out through a computer, phone or network
interface, by a person sitting anywhere. Reading, writing, analysing, deciding,
calculating, designing, planning, scheduling, entering and checking data, and
communicating by text, voice or video are all screen work.

"physical" — carrying out the task requires being at a place, using the body, or moving
physical matter.

"mixed" — the statement as written bundles both: one part needs presence or hands, another
part is done at a screen. "Take patients' vital signs and record them in the chart" is
mixed, because taking them is physical and recording them is screen.

Rules that settle the hard cases:
1. Judge the task as written. If the statement names a physical place, object or bodily
   action, it is physical or mixed, even when some similar task could be done remotely.
2. A meeting, consultation, interview, negotiation or lesson is screen work unless the
   statement requires being physically present — demonstrating on equipment, examining a
   patient, showing a property.
3. Supervising, coordinating, directing and managing are screen work unless the statement
   ties them to a physical site or to physically handling people or equipment.
4. Work that moves matter is physical even when the interface is a console or a screen:
   driving, flying, operating cranes or production equipment, dispensing, packing.
5. Inspecting is physical when the thing inspected must be visited or handled, and screen
   when what is inspected is a document, record, image, or data feed.
6. Do NOT consider whether a computer could perform the task well, or how skilled or
   difficult it is. That is a different question asked elsewhere. Decide only where the
   work happens.

Then name the primary channel through which this work reaches other people:
"text"  — writing, documents, data, chat, email, forms
"voice" — spoken conversation, telephone, live audio
"video" — the worker must be seen: live video presence, presenting on camera
"none"  — the task involves no communication with another person

Answer with one JSON object and nothing else:
{"mode": "screen|mixed|physical", "channel": "text|voice|video|none", "why": "<max 15 words>"}"""


class Pacer:
    """Keep the request rate just under whatever the provider currently allows.

    The free tier has a requests-per-minute ceiling shared across a couple of accounts, and
    the router's reaction to crossing it is not an error but a silent substitution: it
    serves the question from a different vendor's model and labels the answer with the name
    you asked for. So the substitution rate is the rate-limit signal, and this class steers
    on it.

    The aim is NOT zero substitutions. A substitution is detected and retried, so it costs
    a call and no data; at a 20% substitution rate four attempts fail together once in six
    hundred tasks. Driving it to zero would mean crawling. So the constants are chosen to
    settle at roughly one refusal in five: a refusal raises the interval by 10%, a good
    call lowers it by 2.5%, and those balance at 21%.

    An earlier version halved the speed on every refusal and recovered slowly. It read a
    normal background substitution rate as a crisis and pinned itself at six requests a
    minute, which would have taken fifty-two hours for one pass.

    The ceiling is shared with whatever else the founder is running, so a fixed rate chosen
    now would be wrong in an hour. This adapts instead.
    """

    def __init__(self, rpm: float, floor_rpm: float = 10.0) -> None:
        self.min_interval = 60.0 / max(rpm, 0.1)
        self.max_interval = 60.0 / max(floor_rpm, 0.1)
        self.interval = self.min_interval
        self._next = 0.0
        self._lock = threading.Lock()
        # Counted here rather than at the call site because a retry that succeeds erases
        # the evidence: the written row says "ok" and the substitution that preceded it
        # leaves no trace. The run has to report how often the provider was not the one
        # asked for, or the next reader will think the route was clean.
        self.refusals = 0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def refused(self) -> None:
        with self._lock:
            self.refusals += 1
            self.interval = min(self.interval * 1.10, self.max_interval)

    def served(self) -> None:
        with self._lock:
            self.interval = max(self.interval * 0.986, self.min_interval)

    def rpm(self) -> float:
        return 60.0 / self.interval


class DailyBudget:
    """Spend the day's allowance quickly, then wait for it to come back.

    Google's free tier meters two ways at once: fifteen requests a minute and five hundred a
    day per account, four accounts making sixty and two thousand. Only the daily number is
    scarce, and it does not roll over — an allowance not spent today is gone. So there is
    nothing to gain by trickling: at twenty requests a minute the whole day's budget is spent
    in under two hours, and the data arrives that much sooner.

    What must not happen is what happened before this class existed. The run held a
    per-minute pace with no notion of a day, spent the allowance in the first hour, and then
    kept asking for another twenty-three: of 1,400 consecutive requests, two were answered by
    the model we asked for and 1,397 by an NVIDIA model wearing its name. The substitution
    guard threw all 1,397 away, so no bad data was written — but the capacity the other
    raters were waiting for went into the bin with them.

    So the run stops asking once the allowance is spent, and the allowance is judged spent by
    either signal: the count reaching the budget, or the router substituting repeatedly,
    which means the quota went before the count did — the accounts are shared, and the
    founder may be spending them too.

    Recovery is probed rather than calculated. A reset time computed from an assumed timezone
    would be wrong twice a year and unverifiable the rest of it, so the run sleeps, tries one
    request, and either resumes or sleeps again. The cost of a wrong guess is one request.
    """

    def __init__(
        self,
        requests_per_day: int,
        stop_after_consecutive_substitutions: int = 25,
        recheck_minutes: float = 30.0,
        reprobe_after_consecutive_substitutions: int = 3,
    ):
        self.reprobe_limit = reprobe_after_consecutive_substitutions
        self.requests_per_day = requests_per_day
        self.limit = stop_after_consecutive_substitutions
        self.recheck_seconds = recheck_minutes * 60
        self.spent = 0
        self.consecutive = 0
        self.windows = 0
        self.probing = False   # true only between waking and the first served call
        self._open = threading.Event()
        self._open.set()
        self._lock = threading.Lock()

    def substituted(self) -> None:
        with self._lock:
            self.consecutive += 1
            # Two thresholds, and which applies depends on what question is being asked.
            #
            # "Am I still shut out?" — asked by the first calls after waking from a sleep —
            # needs almost no evidence, because we already know the allowance was gone and
            # are only checking whether it returned. Three substitutions answer it, and
            # probing at the full threshold cost twenty-five wasted calls every half hour.
            #
            # "Have I been shut out mid-run?" needs real evidence. A few substitutions are
            # ordinary background noise from a shared router, and treating them as the end
            # of the day's allowance is how this run spent twenty-four hours asleep across
            # sixty-eight windows while completing thirty-five tasks. So once a call has
            # been served in this window, the full threshold applies again.
            threshold = self.reprobe_limit if self.probing else self.limit
            if self.consecutive >= threshold and self._open.is_set():
                self._close("the router substituted "
                            f"{self.consecutive} times running; the quota went early")

    def served(self) -> None:
        with self._lock:
            self.consecutive = 0
            self.probing = False   # the allowance is back; stop being twitchy
            self.spent += 1
            if self.spent >= self.requests_per_day and self._open.is_set():
                self._close(f"{self.spent} requests spent, the day's allowance is gone")

    def _close(self, why: str) -> None:
        """Caller holds the lock."""
        self._open.clear()
        self.reason = why

    def wait_if_closed(self) -> str | None:
        """Block until the allowance is believed back. Returns a message when one is due.

        Exactly one caller does the sleeping and the reopening; the rest simply wait on the
        event, so a pool of workers cannot each start its own timer.
        """
        if self._open.is_set():
            return None
        with self._lock:
            if self._open.is_set():
                return None
            mine = not getattr(self, "_sleeping", False)
            if mine:
                self._sleeping = True
                why = self.reason
        if not mine:
            self._open.wait()
            return None
        time.sleep(self.recheck_seconds)
        with self._lock:
            self.spent = 0
            self.consecutive = 0
            self.windows += 1
            self.probing = True
            self._sleeping = False
            self._open.set()
        return f"{why}; slept {self.recheck_seconds/60:.0f}m and trying again (window {self.windows + 1})"

    def hours_for(self, pending: int, rpm: float) -> float:
        """Wall-clock hours including the waits, not just the time spent asking."""
        if not self.requests_per_day or not rpm:
            return float("inf")
        full_days, rest = divmod(pending, self.requests_per_day)
        return full_days * 24 + (rest / rpm) / 60


def prompt_hash() -> str:
    """Identity of the instrument. A changed instruction is a different measurement."""
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:16]


def user_prompt(task: dict) -> str:
    occupation = task.get("occupation_title") or "unspecified"
    return f"Occupation: {occupation}\nTask: {task['title']}"


def strip_fences(text: str) -> str:
    """Gemini and GLM wrap JSON in markdown fences through the router regardless of
    response_format, which makes a bare json.loads fail on the first character."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse(content: str) -> dict | None:
    """Return a validated label, or None if the reply cannot be trusted.

    An unparseable or out-of-vocabulary reply is dropped rather than coerced. Coercion is
    how a rater's confusion becomes a confident-looking row in a table.
    """
    text = strip_fences(content)
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None
    mode = str(obj.get("mode", "")).strip().lower()
    channel = str(obj.get("channel", "")).strip().lower()
    if mode not in MODES or channel not in CHANNELS:
        return None
    return {"mode": mode, "channel": channel, "why": str(obj.get("why", ""))[:200]}


def response_receipt(resp: object) -> dict[str, object]:
    """Keep the provider evidence needed to audit a paid or substituted attempt.

    The router's request database is the strongest operational authority, but it lives in
    another repository and can be rotated.  A compact receipt beside the label preserves
    the response id, exact served route, tokens and reported cost without copying prompts
    or response text into a second artifact.
    """
    extra = getattr(resp, "model_extra", None) or {}
    extra = extra if isinstance(extra, dict) else {}
    via = extra.get("_routed_via")
    via = via if isinstance(via, dict) else {}
    usage = getattr(resp, "usage", None)
    usage_extra = getattr(usage, "model_extra", None) or {}
    return {
        "response_id": getattr(resp, "id", None),
        "response_model_id": getattr(resp, "model", None),
        "provider": via.get("platform") or extra.get("provider"),
        "served_model_id": via.get("model") or getattr(resp, "model", None),
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "cost_usd": usage_extra.get("cost"),
    }


def cache_nonce_for_pass(repeat: int, retry_pass: int, max_passes: int) -> int:
    """Allocate disjoint cache keys to successive passes of one repeat arm."""
    return (repeat * max_passes + retry_pass - 1) * MAX_RETRIES


def call_once(
    client: OpenAI, model: str, task: dict, nonce: int, pacer: Pacer | None = None
) -> tuple[dict | None, str, str | None, list[dict[str, object]]]:
    """One task, one logical request. Returns label, status, backend and attempt receipts.

    The nonce rides on max_tokens because the router keys its response cache on
    (model, messages, temperature, max_tokens) and ignores `user`, `seed` and cache
    headers. Without it a repeat of the same task returns the first answer verbatim and
    the self-consistency figure measures the cache instead of the rater.

    The token ceiling is deliberately far above what an answer needs — a correct reply is
    about 37 tokens. At a tight ceiling the rater sometimes starts reasoning in prose and
    is then cut off mid-sentence, which cost 39% of a trial run. Headroom is free here and
    a truncated answer is not a cheap answer, it is a lost task.
    """
    last = "unknown"
    backend = None
    receipts: list[dict[str, object]] = []
    for attempt in range(MAX_RETRIES):
        if pacer is not None:
            pacer.wait()
        request_max_tokens = 1500 + nonce + attempt
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt(task)},
                ],
                temperature=TEMPERATURE,
                # The router caches on max_tokens. Every retry must use a fresh value or a
                # truncated/empty response is replayed without another provider request.
                max_tokens=request_max_tokens,
                response_format={"type": "json_object"},
            )
            # Which backend actually served this. One model name can be fronted by more
            # than one provider, and a run that silently changes provider halfway is two
            # measurements wearing one name.
            extra = getattr(resp, "model_extra", None) or {}
            via = extra.get("_routed_via")
            receipt = response_receipt(resp)
            receipt["request_max_tokens"] = request_max_tokens
            receipts.append(receipt)
            served = str(receipt.get("served_model_id") or "")
            if isinstance(via, dict):
                backend = f"{via.get('platform')}/{via.get('model')}"
            elif served:
                provider = receipt.get("provider") or "unverified-provider"
                backend = f"{provider}/{served}"
            # The router silently substitutes another provider's model when the
            # requested one is rate-limited. A trial run asked for gemini-3.5-flash-lite
            # and got nemotron-3-super-120b-a12b:free for 27% of calls, all of them
            # labelled "gemini" in the output. Availability is not a reason to
            # substitute: a run whose rater changes halfway is two measurements sharing
            # a filename. Direct OpenRouter calls do not carry _routed_via, so compare
            # their top-level response model by the same rule.
            if not served or served != model:
                last = f"substituted:{backend or 'unverified-backend'}"
                if pacer is not None:
                    pacer.refused()
                time.sleep(min(2**attempt, 8) + random.random())
                continue
            if isinstance(via, dict) and pacer is not None:
                pacer.served()
            choices = resp.choices or []
            content = choices[0].message.content if choices else None
            label = parse(content)
            if label is not None:
                return label, "ok", backend, receipts
            # Keep the text that defeated the parser. An unattended run that only records
            # "unparseable" leaves nothing to diagnose in the morning, and the difference
            # between an empty reply, a refusal and a prose answer changes what to fix.
            last = "unparseable:" + repr(content)[:160]
        except BadRequestError as exc:
            # A 400 is a property of the request, not of the moment; retrying burns quota
            # and returns the same error.
            return None, f"bad_request:{str(exc)[:80]}", backend, receipts
        except Exception as exc:  # noqa: BLE001 - transport, rate limit, provider error
            last = f"{type(exc).__name__}:{str(exc)[:80]}"
            if pacer is not None and ("429" in last or "rate" in last.lower()):
                pacer.refused()
        if attempt < MAX_RETRIES - 1:
            time.sleep(min(2**attempt, 8) + random.random())
    return None, last, backend, receipts


def load_corpus(limit: int | None, seed: int) -> list[dict]:
    """Read the exported corpus. A limit takes a deterministic random sample, not a head
    slice: the file is ordered by activity id, and a head slice of it is one alphabetical
    corner of the occupational structure."""
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is not None and limit < len(rows):
        rows = random.Random(seed).sample(rows, limit)
        rows.sort(key=lambda r: r["activity_id"])
    return rows


def by_influence(rows: list[dict]) -> list[dict]:
    """Order the corpus so that the tasks that move published numbers are labelled first.

    Only 2,359 of the 18,796 statements influence the aggregates the project publishes
    (prd.md 9.4); the rest are carried for completeness. A rate-limited run that gets
    through only part of the corpus should be stopped by the sunrise, not by the alphabet,
    so the queue is ordered by occupational importance, most important first.

    This changes nothing about the labels themselves — the request for a task is identical
    wherever it sits in the queue. It only decides which half of the corpus exists if the
    night runs out.
    """
    return sorted(rows, key=lambda r: (-(r.get("importance") or 0.0), r["activity_id"]))


def done_ids(path: Path) -> set[str]:
    """Ids that already carry a label, so a restart resumes instead of repeating.

    Rows whose call failed are deliberately not counted as done: re-running the same
    command is the retry mechanism, and skipping them would make a run look complete while
    a systematic failure — one provider down for an hour — silently ate a slice of the
    corpus. The duplicate rows this leaves behind are resolved by keeping the last.
    """
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("mode") is not None:
            ids.add(rec.get("activity_id"))
    return ids


def contested_ids(exclude: str) -> set[str]:
    """Tasks the OTHER raters disagreed about.

    A third rater is worth most where two have split, because there the answer is still open;
    on a task two raters already agree about, a third mostly confirms what is recorded and
    buys reproducibility rather than a decision. When the budget is 2,000 calls a day against
    a corpus of 18,796, that difference decides whether the third voice arrives this week or
    next month.

    `exclude` keeps the rater's own earlier answers out of the disagreement count, so a run
    resumed after a restart does not treat its own past self as one of the others.
    """
    by_task: dict[str, set[str]] = {}
    for path in sorted(glob.glob(str(OUT_DIR / "*__r0.jsonl"))):
        run = os.path.basename(path)[:-9]
        if run == re.sub(r"[^A-Za-z0-9._-]", "_", exclude):
            continue
        with open(path, encoding="utf-8") as lines:
            for line in lines:
                rec = json.loads(line)
                if rec.get("mode"):
                    by_task.setdefault(rec["activity_id"], set()).add(rec["mode"])
    return {a for a, modes in by_task.items() if len(modes) > 1}


@click.command()
@click.option(
    "--model",
    required=True,
    help="Stable rater identity used in the output file and model_id receipt.",
)
@click.option(
    "--request-model",
    default=None,
    help="Exact model route sent to the endpoint; defaults to --model.",
)
@click.option(
    "--repeat",
    default=0,
    type=click.IntRange(min=0),
    show_default=True,
    help="Repeat index; combined with retry pass into disjoint cache keys.",
)
@click.option("--limit", default=None, type=int, help="Sample this many tasks instead of all.")
@click.option("--seed", default=17, show_default=True, help="Sample seed.")
@click.option("--concurrency", default=6, show_default=True)
@click.option("--rpm", default=90.0, show_default=True, help="Ceiling on requests per minute; the pacer only goes slower than this.")
@click.option("--out", "out_name", default=None, help="Output file name; derived if absent.")
@click.option(
    "--max-passes",
    default=1,
    type=click.IntRange(min=1),
    show_default=True,
    help="Retry failed tasks in the same PID, up to this many complete passes.",
)
@click.option(
    "--daily-budget", default=None, type=int,
    help="Requests the provider allows per DAY. Spreads them evenly and overrides --rpm.",
)
@click.option(
    "--only-contested", is_flag=True,
    help="Rate only the tasks the other raters split on. Spends a scarce budget where a "
         "third voice decides something instead of confirming what two already agreed.",
)
def main(
    model: str,
    request_model: str | None,
    repeat: int,
    limit: int | None,
    seed: int,
    concurrency: int,
    rpm: float,
    out_name: str | None,
    max_passes: int,
    daily_budget: int | None,
    only_contested: bool,
) -> None:
    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} is not set")
    if daily_budget and max_passes > 1:
        raise click.UsageError("--max-passes above 1 cannot be combined with --daily-budget")
    retry_pass = int(os.environ.get(RETRY_PASS_ENV, "1"))
    if retry_pass < 1 or retry_pass > max_passes:
        raise click.UsageError(
            f"invalid retry pass {retry_pass}; expected a value from 1 through {max_passes}"
        )

    # Never start a run without printing what is actually about to run.
    requested_route = request_model or model
    cache_nonce = cache_nonce_for_pass(repeat, retry_pass, max_passes)
    click.echo(
        f"model={model}  request_model={requested_route}  endpoint={BASE_URL}  key_env={KEY_ENV}"
    )
    click.echo(f"pass={retry_pass}/{max_passes}  cache_nonce={cache_nonce}")
    click.echo(f"prompt={prompt_hash()}  temperature={TEMPERATURE}  batch_size={BATCH_SIZE}  repeat={repeat}")

    budget = DailyBudget(daily_budget) if daily_budget else None
    if budget:
        click.echo(
            f"daily_budget={daily_budget} at {rpm:.0f}/min — spent in "
            f"{daily_budget/rpm/60:.1f}h, then waits for the allowance to return. "
            f"Stops early after {budget.limit} consecutive substitutions."
        )

    tasks = by_influence(load_corpus(limit, seed))
    if only_contested:
        contested = contested_ids(exclude=model)
        tasks = [t for t in tasks if t["activity_id"] in contested]
        click.echo(f"only_contested: {len(tasks)} tasks the other raters split on")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    out_path = OUT_DIR / (out_name or f"{safe}__r{repeat}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    already = done_ids(out_path)
    pending = [t for t in tasks if t["activity_id"] not in already]
    click.echo(f"corpus={len(tasks)}  already_done={len(already)}  pending={len(pending)}  -> {out_path}")
    if not pending:
        click.echo("nothing to do")
        return

    client = OpenAI(api_key=key, base_url=BASE_URL, timeout=90.0, max_retries=0)
    stamp = datetime.now(UTC).isoformat()
    phash = prompt_hash()
    pacer = Pacer(rpm)
    lock = threading.Lock()
    counts = {"ok": 0, "failed": 0, "substituted": 0}
    started = time.time()
    if budget:
        click.echo(f"the {len(pending)} pending take about {budget.hours_for(len(pending), rpm):.1f}h in wall clock")

    with out_path.open("a", encoding="utf-8") as fh:
        def work(task: dict) -> None:
            if budget:
                note = budget.wait_if_closed()
                if note:
                    click.echo(f"  {note}", err=True)
            label, status, backend, attempt_receipts = call_once(
                client, requested_route, task, cache_nonce, pacer
            )
            if budget:
                budget.substituted() if status.startswith("substituted:") else budget.served()
            record = {
                "activity_id": task["activity_id"],
                "title": task["title"],
                "occupation_title": task.get("occupation_title"),
                "mode": label["mode"] if label else None,
                "channel": label["channel"] if label else None,
                "why": label["why"] if label else None,
                "status": status,
                "model_id": model,
                "requested_model_id": requested_route,
                "backend": backend,
                "attempt_receipts": attempt_receipts,
                "cache_nonce": cache_nonce,
                "prompt_hash": phash,
                "temperature": TEMPERATURE,
                "batch_size": BATCH_SIZE,
                "repeat": repeat,
                "scored_at": stamp,
            }
            with lock:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()  # an unattended run must be inspectable while it runs
                counts["ok" if label else "failed"] += 1
                if status.startswith("substituted:"):
                    counts["substituted"] += 1
                n = counts["ok"] + counts["failed"]
                if n % 200 == 0 or n == len(pending):
                    rate = n / max(time.time() - started, 1e-9)
                    # A cumulative average is the wrong clock under a daily budget. Once the
                    # allowance is spent the run sleeps, so the average since start folds hours
                    # of waiting into the rate and reports an ETA two and a half times too
                    # long — 298 hours against a true 121. When a budget is set, ask the budget.
                    left = (
                        budget.hours_for(len(pending) - n, rpm) * 3600
                        if budget else (len(pending) - n) / max(rate, 1e-9)
                    )
                    click.echo(
                        f"  {n}/{len(pending)}  ok={counts['ok']} failed={counts['failed']} "
                        f"lost={counts['substituted']} refused={pacer.refusals}  {rate*60:.0f}/min "
                        f"(pace {pacer.rpm():.0f})  eta={left/3600:.1f}h",
                        err=True,
                    )

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(work, pending))

    elapsed = time.time() - started
    click.echo(
        f"done in {elapsed/60:.1f}m  ok={counts['ok']}  failed={counts['failed']}  "
        f"provider substitutions refused: {pacer.refusals}  final pace {pacer.rpm():.0f}/min"
    )
    if counts["failed"]:
        click.echo(f"re-run the same command to retry the {counts['failed']} that failed", err=True)
        if retry_pass < max_passes:
            next_pass = retry_pass + 1
            click.echo(
                f"starting retry pass {next_pass}/{max_passes} in the same PID",
                err=True,
            )
            os.environ[RETRY_PASS_ENV] = str(next_pass)
            sys.stdout.flush()
            sys.stderr.flush()
            os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == "__main__":
    main()
