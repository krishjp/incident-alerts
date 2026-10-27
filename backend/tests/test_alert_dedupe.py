import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import alert_dedupe
import main
from alert_dedupe import is_similar_summary, summary_similarity
from cache_handler import IncidentCache
from config import settings

THRESHOLD = 0.85

# The two summaries Gemini produced for one Lawndale collision in a single pass.
REWORDED_A = (
    "Traffic collision I-405 N / Palo Verde Ave Onramp. Vehicles blocking lanes & "
    "undrivable. No injuries. Expect major delays."
)
REWORDED_B = (
    "Traffic collision I-405 N / Palo Verde Ave onramp. Lanes blocked, vehicles "
    "undrivable. Expect delays. No injuries reported."
)


@pytest.fixture(autouse=True)
def no_dedupe_model(monkeypatch):
    # A developer's .env may carry a real AI_GATEWAY_API_KEY; these tests must
    # never reach the gateway. TestDecisionModel opts back in with a fake.
    monkeypatch.setattr(settings, "ai_gateway_api_key", "")
    monkeypatch.setattr(alert_dedupe, "_gateway_refused", False)
    # Memory-only cache, so decisions never land in (or come from) local Redis.
    monkeypatch.setattr(alert_dedupe, "global_incident_cache", IncidentCache(client=False))
    alert_dedupe._ask_model.cache_clear()
    yield
    alert_dedupe._ask_model.cache_clear()


class _FakeResponse:
    def __init__(self, probability):
        self._probability = probability

    def raise_for_status(self):
        pass

    def json(self):
        return {"answers": {"same_alert": {"type": "boolean", "probability": self._probability}}}


LOW_OVERLAP_A = "Collision I-405 N at Palo Verde. Lanes blocked. No injuries."
LOW_OVERLAP_B = "Crash on northbound 405 near Palo Verde obstructing roadway. Nobody hurt."
OTHER_INCIDENT = "Stalled vehicle I-110 S / Manchester Ave. Right lane blocked. Minor delays."


class TestDecisionModel:
    @pytest.fixture
    def gateway(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_gateway_api_key", "test-key")
        monkeypatch.setattr(settings, "dedupe_min_probability", 0.85)
        calls = []
        state = SimpleNamespace(probability=0.95, error=None, calls=calls)

        def post(url, json, headers, timeout):
            calls.append(json)
            if state.error:
                raise state.error
            return _FakeResponse(state.probability)
        monkeypatch.setattr(alert_dedupe.httpx, "post", post)
        return state

    def test_high_overlap_suppresses_without_asking_the_model(self, gateway):
        gateway.probability = 0.0
        assert is_similar_summary(REWORDED_A, REWORDED_B, THRESHOLD)
        assert gateway.calls == []

    def test_low_overlap_rewording_is_suppressed_when_model_agrees(self, gateway):
        assert summary_similarity(LOW_OVERLAP_A, LOW_OVERLAP_B) < THRESHOLD
        assert is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        assert gateway.calls[0]["model"] == settings.dedupe_model
        assert gateway.calls[0]["state"] == {"previous_alert": LOW_OVERLAP_A, "new_alert": LOW_OVERLAP_B}

    def test_probability_below_bar_sends(self, gateway):
        gateway.probability = 0.8
        assert not is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)

    def test_fact_flip_never_asks_the_model(self, gateway):
        update = "Fatal traffic collision I-405 N / Palo Verde Ave onramp. Lanes blocked, vehicles undrivable."
        assert not is_similar_summary(REWORDED_B, update, THRESHOLD)
        assert gateway.calls == []

    def test_gateway_failure_sends(self, gateway):
        gateway.error = RuntimeError("gateway down")
        assert not is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        assert not is_similar_summary(REWORDED_A, OTHER_INCIDENT, THRESHOLD)

    def test_account_refusal_stops_further_calls(self, gateway):
        request = alert_dedupe.httpx.Request("POST", "https://ai-gateway.vercel.sh/v1/evaluate")
        gateway.error = alert_dedupe.httpx.HTTPStatusError(
            "429", request=request, response=alert_dedupe.httpx.Response(429, request=request)
        )
        assert not is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        assert not is_similar_summary(REWORDED_A, OTHER_INCIDENT, THRESHOLD)
        assert len(gateway.calls) == 1

    def test_same_pair_is_asked_once(self, gateway):
        is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        assert len(gateway.calls) == 1

    def test_pair_in_either_order_is_asked_once(self, gateway):
        # Two routes can queue the same two incidents in opposite orders.
        assert is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        assert is_similar_summary(LOW_OVERLAP_B, LOW_OVERLAP_A, THRESHOLD)
        assert len(gateway.calls) == 1

    def test_answer_is_reused_by_the_next_pass(self, gateway):
        # A suppressed UPDATE is re-compared every pass; each pass is a new
        # process, so only the shared cache (Redis in production) carries it.
        is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        alert_dedupe._ask_model.cache_clear()
        assert is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        assert len(gateway.calls) == 1

    def test_failures_are_not_stored_for_later_passes(self, gateway):
        gateway.error = RuntimeError("timeout")
        assert not is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        alert_dedupe._ask_model.cache_clear()
        gateway.error = None
        assert is_similar_summary(LOW_OVERLAP_A, LOW_OVERLAP_B, THRESHOLD)
        assert len(gateway.calls) == 2


class TestSummarySimilarity:
    def test_gemini_rewording_is_similar(self):
        assert summary_similarity(REWORDED_A, REWORDED_B) >= THRESHOLD
        assert is_similar_summary(REWORDED_A, REWORDED_B, THRESHOLD)

    def test_different_incident_is_not_similar(self):
        other = "Stalled vehicle I-110 S / Manchester Ave. Right lane blocked. Minor delays."
        assert not is_similar_summary(REWORDED_A, other, THRESHOLD)

    @pytest.mark.parametrize(
        "update",
        [
            "Traffic collision I-405 N / Palo Verde Ave onramp. Lanes blocked, vehicles undrivable. Injuries reported. Expect delays.",
            "Traffic collision I-405 N / Palo Verde Ave onramp. Lanes cleared, vehicles undrivable. No injuries.",
            "Traffic collision I-405 N / Palo Verde Ave onramp. All lanes closed, vehicles undrivable. No injuries.",
            "Fatal traffic collision I-405 N / Palo Verde Ave onramp. Lanes blocked, vehicles undrivable.",
        ],
    )
    def test_material_fact_change_is_never_similar(self, update):
        # High word overlap, but the driver-relevant facts differ.
        assert not is_similar_summary(REWORDED_B, update, THRESHOLD)

    def test_empty_summary_is_not_similar(self):
        assert not is_similar_summary("", REWORDED_A, THRESHOLD)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_):
        return self

    def all(self):
        return list(self._rows)


class _FakeDb:
    """In-memory stand-in for NotifiedIncident rows, persisted across passes."""

    def __init__(self):
        self.rows = {}
        self.messages = []
        self.subs = {}

    def query(self, model):
        if model is main.RouteSubscription:
            return _FakeQuery(self.subs.values())
        return _FakeQuery(self.rows.values())

    def add(self, record):
        if isinstance(record, main.AlertMessage):
            self.messages.append(record)
        else:
            self.rows[record.id] = record


class _FakeQueue:
    def __init__(self):
        self.sent = []

    def enqueue(self, to_phone, message):
        self.sent.append((to_phone, message))

    def process_queue(self):
        pass


def _incident(number, blob):
    return {
        "number": number,
        "location": "I-405 N / Palo Verde Ave",
        "location_desc": "",
        "details": {"lat_lon": "33.88 -118.35", "full_text_blob": blob},
    }


@pytest.fixture
def worker(monkeypatch):
    db = _FakeDb()
    queue = _FakeQueue()
    feed = []
    summaries = {}
    cache = {}

    sub = SimpleNamespace(id="sub1", userId="user1", origin="Torrance", destination="Lawndale", polyline="x")
    db.subs[sub.id] = sub
    # Emptying this list takes the route out of its time window.
    active = [{"sub": sub, "phone": "+15551234567", "user": "u@example.com"}]
    monkeypatch.setattr(main, "get_active_subscriptions", lambda: list(active))
    monkeypatch.setattr(main, "fetch_caltrans_incidents", lambda: list(feed))
    monkeypatch.setattr(main, "is_within_range", lambda *a, **k: True)
    monkeypatch.setattr(main, "global_notification_queue", queue)
    monkeypatch.setattr(main, "check_dependencies", lambda: [])

    @contextmanager
    def session_scope():
        yield db
    monkeypatch.setattr(main, "session_scope", session_scope)

    # Summaries are keyed like the real cache: (number, str(details)).
    def summarize(inc):
        key = (inc["number"], str(inc["details"]))
        cache[key] = summaries[inc["details"]["full_text_blob"]]
        return cache[key]
    monkeypatch.setattr(main, "summarize_incident", summarize)
    monkeypatch.setattr(main, "global_incident_cache",
                        SimpleNamespace(get_summary=lambda n, d: cache.get((n, d))))

    return SimpleNamespace(feed=feed, summaries=summaries, queue=queue, db=db, active=active)


class TestCheckAndNotifyDedupe:
    def test_two_incident_numbers_for_one_collision_send_one_sms(self, worker):
        worker.summaries.update({"a": REWORDED_A, "b": REWORDED_B})
        worker.feed[:] = [_incident("LA01", "a"), _incident("LA02", "b")]

        main.check_and_notify()

        assert len(worker.queue.sent) == 1
        # Both are recorded, so the second number doesn't alert next pass either.
        assert set(worker.db.rows) == {"sub1_LA01", "sub1_LA02"}

        main.check_and_notify()
        assert len(worker.queue.sent) == 1

    def test_suppressed_duplicate_resolves_silently(self, worker):
        worker.summaries.update({"a": REWORDED_A, "b": REWORDED_B})
        worker.feed[:] = [_incident("LA01", "a"), _incident("LA02", "b")]
        main.check_and_notify()

        worker.feed[:] = [_incident("LA01", "a")]
        main.check_and_notify()

        assert len(worker.queue.sent) == 1
        assert worker.db.rows["sub1_LA02"].state == "RESOLVED"

    def test_reworded_update_is_suppressed(self, worker):
        worker.summaries.update({"v1": REWORDED_A, "v2": REWORDED_B})
        worker.feed[:] = [_incident("LA01", "v1")]
        main.check_and_notify()

        worker.feed[:] = [_incident("LA01", "v2")]
        main.check_and_notify()

        assert len(worker.queue.sent) == 1

    def test_material_update_still_alerts(self, worker):
        worker.summaries.update({
            "v1": REWORDED_A,
            "v2": "Traffic collision I-405 N / Palo Verde Ave onramp. All lanes closed. Injuries reported.",
        })
        worker.feed[:] = [_incident("LA01", "v1")]
        main.check_and_notify()

        worker.feed[:] = [_incident("LA01", "v2")]
        main.check_and_notify()

        assert len(worker.queue.sent) == 2
        assert worker.queue.sent[1][1].startswith("Incident UPDATE Alert")

    def test_repeated_placemark_in_feed_sends_once(self, worker):
        worker.summaries.update({"a": REWORDED_A})
        worker.feed[:] = [_incident("LA01", "a"), _incident("LA01", "a")]

        main.check_and_notify()

        assert len(worker.queue.sent) == 1

    def test_each_queued_alert_is_logged_with_its_route(self, worker):
        worker.summaries.update({"a": REWORDED_A})
        worker.feed[:] = [_incident("LA01", "a")]
        main.check_and_notify()

        worker.feed[:] = []
        main.check_and_notify()

        assert [(m.kind, m.incidentNumber) for m in worker.db.messages] == [
            ("NEW", "LA01"), ("RESOLVED", "LA01"),
        ]
        new, resolved = worker.db.messages
        assert new.userId == "user1" and new.subscriptionId == "sub1"
        assert new.routeLabel == "Torrance->Lawndale"
        assert new.matchMethod == "spatial"
        assert new.message == worker.queue.sent[0][1]
        assert resolved.matchMethod is None and resolved.distanceMiles is None

    def test_suppressed_duplicate_is_not_logged(self, worker):
        worker.summaries.update({"a": REWORDED_A, "b": REWORDED_B})
        worker.feed[:] = [_incident("LA01", "a"), _incident("LA02", "b")]
        main.check_and_notify()

        assert len(worker.db.messages) == len(worker.queue.sent) == 1

    def test_user_without_phone_is_logged_but_not_queued(self, worker, monkeypatch):
        sub = SimpleNamespace(id="sub1", userId="user1", origin="Torrance", destination="Lawndale", polyline="x")
        monkeypatch.setattr(main, "get_active_subscriptions",
                            lambda: [{"sub": sub, "phone": None, "user": "u@example.com"}])
        worker.summaries.update({"a": REWORDED_A})
        worker.feed[:] = [_incident("LA01", "a")]
        main.check_and_notify()

        worker.feed[:] = []
        main.check_and_notify()

        assert worker.queue.sent == []
        assert [(m.kind, m.delivery) for m in worker.db.messages] == [("NEW", "none"), ("RESOLVED", "none")]


class TestStaleIncidents:
    def _alert_then_leave_window(self, worker):
        worker.summaries.update({"a": REWORDED_A})
        worker.feed[:] = [_incident("LA01", "a")]
        main.check_and_notify()
        worker.window = list(worker.active)
        worker.active.clear()
        main.check_and_notify()

    def test_leaving_the_window_parks_the_incident_silently(self, worker):
        self._alert_then_leave_window(worker)

        assert worker.db.rows["sub1_LA01"].state.startswith(main.STALE_PREFIX)
        assert len(worker.queue.sent) == 1
        stale = worker.db.messages[-1]
        assert (stale.kind, stale.delivery, stale.incidentNumber) == ("STALE", "none", "LA01")
        assert stale.routeLabel == "Torrance->Lawndale"

    def test_stale_incident_is_not_parked_twice(self, worker):
        self._alert_then_leave_window(worker)
        main.check_and_notify()

        assert [m.kind for m in worker.db.messages] == ["NEW", "STALE"]

    def test_still_reported_next_window_resumes_without_an_sms(self, worker):
        self._alert_then_leave_window(worker)
        worker.active.extend(worker.window)
        main.check_and_notify()

        assert [m.kind for m in worker.db.messages] == ["NEW", "STALE", "ACTIVE"]
        assert worker.db.messages[-1].delivery == "none"
        assert not worker.db.rows["sub1_LA01"].state.startswith(main.STALE_PREFIX)
        assert len(worker.queue.sent) == 1

        main.check_and_notify()
        assert [m.kind for m in worker.db.messages] == ["NEW", "STALE", "ACTIVE"]

    def test_changed_while_stale_resumes_with_an_update(self, worker):
        self._alert_then_leave_window(worker)
        worker.summaries["b"] = "Traffic collision I-405 N / Palo Verde Ave onramp. All lanes closed. Injuries reported."
        worker.feed[:] = [_incident("LA01", "b")]
        worker.active.extend(worker.window)
        main.check_and_notify()

        assert [m.kind for m in worker.db.messages] == ["NEW", "STALE", "ACTIVE", "UPDATE"]
        assert len(worker.queue.sent) == 2

    def test_gone_by_next_window_stays_stale_and_silent(self, worker):
        self._alert_then_leave_window(worker)
        worker.feed[:] = []
        worker.active.extend(worker.window)
        main.check_and_notify()

        assert worker.db.rows["sub1_LA01"].state.startswith(main.STALE_PREFIX)
        assert [m.kind for m in worker.db.messages] == ["NEW", "STALE"]
        assert len(worker.queue.sent) == 1

    def test_resolved_and_duplicate_incidents_are_left_alone(self, worker):
        worker.db.rows["sub1_OLD"] = SimpleNamespace(id="sub1_OLD", state="RESOLVED")
        worker.db.rows["sub1_DUP"] = SimpleNamespace(id="sub1_DUP", state=main.DUPLICATE_PREFIX + "x")
        worker.active.clear()
        main.check_and_notify()

        assert worker.db.rows["sub1_OLD"].state == "RESOLVED"
        assert worker.db.rows["sub1_DUP"].state.startswith(main.DUPLICATE_PREFIX)
        assert worker.db.messages == []
