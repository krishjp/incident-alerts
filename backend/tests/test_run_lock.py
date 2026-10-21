import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from redis_client import single_run_lock


class FakeRedis:
    """Implements just the SET NX EX / GET / DEL semantics the lock relies on."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


class BrokenRedis(FakeRedis):
    def set(self, *args, **kwargs):
        raise ConnectionError("redis went away")


class TestSingleRunLock:
    def test_acquires_when_free(self):
        redis = FakeRedis()
        with single_run_lock("worker:poll", 300, client=redis) as acquired:
            assert acquired is True

    def test_releases_on_exit(self):
        redis = FakeRedis()
        with single_run_lock("worker:poll", 300, client=redis):
            pass
        # A held lock after a clean exit would make every later run skip until
        # the TTL expired.
        assert redis.store == {}

    def test_second_holder_is_refused_while_held(self):
        redis = FakeRedis()
        with single_run_lock("worker:poll", 300, client=redis) as first:
            assert first is True
            with single_run_lock("worker:poll", 300, client=redis) as second:
                assert second is False

    def test_lock_is_reusable_after_release(self):
        redis = FakeRedis()
        with single_run_lock("worker:poll", 300, client=redis):
            pass
        with single_run_lock("worker:poll", 300, client=redis) as acquired:
            assert acquired is True

    def test_released_even_when_body_raises(self):
        redis = FakeRedis()
        try:
            with single_run_lock("worker:poll", 300, client=redis):
                raise RuntimeError("poll cycle blew up")
        except RuntimeError:
            pass
        assert redis.store == {}

    def test_does_not_release_a_lock_it_no_longer_owns(self):
        # An overrunning execution whose lock already expired must not delete
        # the lock a newer execution legitimately holds.
        redis = FakeRedis()
        with single_run_lock("worker:poll", 300, client=redis):
            redis.store["lock:worker:poll"] = "a-newer-executions-token"
        assert redis.store["lock:worker:poll"] == "a-newer-executions-token"

    def test_independent_lock_names_do_not_collide(self):
        redis = FakeRedis()
        with single_run_lock("worker:poll", 300, client=redis) as first:
            with single_run_lock("worker:other", 300, client=redis) as second:
                assert first is True
                assert second is True


class TestDegradation:
    def test_proceeds_without_redis(self):
        # Redis is an optimization everywhere else in this system; a missing
        # cache must not stop alerts going out.
        with single_run_lock("worker:poll", 300, client=None) as acquired:
            assert acquired is True

    def test_proceeds_when_redis_errors(self):
        with single_run_lock("worker:poll", 300, client=BrokenRedis()) as acquired:
            assert acquired is True
