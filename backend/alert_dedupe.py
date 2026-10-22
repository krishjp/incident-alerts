"""
Near-duplicate detection for outbound alert text.

Gemini rewords the same incident differently from call to call ("Vehicles
blocking lanes & undrivable. No injuries." vs "Lanes blocked, vehicles
undrivable. No injuries reported."), and CHP often files the same collision
under two incident numbers. Exact-match fingerprints treat each rewording as new
content and send another SMS. This compares meaning-bearing words first, and
only when they don't overlap enough to suppress does it ask a decision model
(Laya by default, through Vercel AI Gateway) whether the newer summary is a
rewording the word check missed. That keeps model calls (rate-limited to a few
per minute) for the uncertain cases. Either way, two summaries that disagree on
a fact that matters to a driver (injuries, fatality, closure, cleared) are
never merged.
"""
import re
from functools import lru_cache

import httpx

from cache_handler import global_incident_cache
from config import settings

_GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/evaluate"
_TIMEOUT_SECONDS = 5.0

# Set when the gateway refuses the account itself (bad key, no card on file,
# rate limit):
# every further call this process would fail the same way, so stop asking.
_gateway_refused = False

# Words that carry no incident-specific information. Kept short on purpose:
# dropping too much makes unrelated incidents on the same freeway look alike.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "at", "on", "in", "is", "are", "was",
    "to", "for", "with", "near", "by", "from", "reported", "report", "expect",
    "possible", "currently", "now", "please", "alert",
})

# Facts whose presence/absence must match for two summaries to count as the
# same alert. Each pattern is checked independently; a flip in any one means the
# newer text is a real update.
_SIGNALS = {
    "injury": re.compile(r"(?<!no )(?<!non-)(?<!non )\binjur(y|ies|ed)\b"),
    "fatal": re.compile(r"\b(fatal|fatality|killed|deceased)\b"),
    "closed": re.compile(r"\b(all lanes (are )?(closed|blocked)|closure|closed|sigalert|shut down)\b"),
    "cleared": re.compile(r"\b(cleared|reopened|re-opened|open again|lanes open)\b"),
    "fire": re.compile(r"\b(fire|burning|flames)\b"),
    "hazmat": re.compile(r"\b(hazmat|spill|leak)\b"),
}


def _stem(token: str) -> str:
    # Crude suffix stripping, enough to equate block/blocked/blocking and
    # lane/lanes without pulling in an NLP dependency.
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _tokens(text: str) -> set:
    text = text.lower().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", text)
    return {_stem(w) for w in words if w not in _STOPWORDS}


def _signals(text: str) -> frozenset:
    lowered = text.lower()
    return frozenset(name for name, pattern in _SIGNALS.items() if pattern.search(lowered))


def summary_similarity(a: str, b: str) -> float:
    """Jaccard similarity (0..1) of the two summaries' stemmed content words."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def same_alert_probability(a: str, b: str):
    """
    Decision-model probability (0..1) that a and b are the same alert, or None
    when the model is unavailable. The question is asked once per unordered
    pair: an incident matching several routes (or users) reaches here once per
    route with the same two summaries, and a suppressed UPDATE is re-compared
    every pass until its details change, so answers are kept in Redis for 24h.
    """
    if not settings.dedupe_model_enabled:
        return None
    first, second = sorted((a, b))
    return _ask_model(first, second)


# In front of the Redis cache: also remembers failures (None) for the rest of
# the pass, so a timing-out gateway isn't retried for every route.
@lru_cache(maxsize=1024)
def _ask_model(a: str, b: str):
    global _gateway_refused
    cached = global_incident_cache.get_decision(settings.dedupe_model, a, b)
    if cached is not None:
        return cached
    if _gateway_refused:
        return None
    payload = {
        "model": settings.dedupe_model,
        # Labels are positional only: the pair is sorted, and the question
        # is meant to read the same either way round.
        "state": {"previous_alert": a, "new_alert": b},
        "questions": {
            "same_alert": {
                "type": "boolean",
                "instructions": (
                    "Both are SMS traffic alerts sent to the same commuter. Is "
                    "new_alert the same traffic incident as previous_alert, with "
                    "nothing a driver would act on differently?"
                ),
                "criteria": {
                    "true": "same incident and location; only wording or minor detail differs",
                    "false": (
                        "a different incident or location, or a change in lanes "
                        "blocked or cleared, closures, injuries, fatalities, fire, "
                        "hazmat, or expected delay"
                    ),
                },
            },
        },
    }
    try:
        response = httpx.post(
            _GATEWAY_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.ai_gateway_api_key}"},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        probability = float(response.json()["answers"]["same_alert"]["probability"])
    except httpx.HTTPStatusError as e:
        # 429 too: the per-minute limit outlasts the rest of this pass.
        if e.response.status_code in (401, 402, 403, 429):
            _gateway_refused = True
        print(f"[Dedupe] {settings.dedupe_model} refused ({e.response.status_code}), sending: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"[Dedupe] {settings.dedupe_model} unavailable, sending: {e}")
        return None
    global_incident_cache.set_decision(settings.dedupe_model, a, b, probability)
    return probability


def is_similar_summary(a: str, b: str, threshold: float) -> bool:
    """True when b says nothing materially different from a."""
    if not a or not b:
        return False
    # Hard veto ahead of the model: a flip in a driver-critical fact always
    # sends, whatever the model thinks. Mistakes here only cost an extra SMS.
    if _signals(a) != _signals(b):
        return False
    if summary_similarity(a, b) >= threshold:
        return True
    # Not enough shared words to suppress on their own: ask the model whether
    # this is a rewording anyway. Unavailable model means send.
    probability = same_alert_probability(a, b)
    return probability is not None and probability >= settings.dedupe_min_probability
