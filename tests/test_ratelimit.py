"""Rolling-window rate limiter (SPEC sections A.7, C.4, C.7)."""

import pytest

from things_lib.url import RateLimiter, UrlError


def make(fake_clock, **kwargs):
    return RateLimiter(clock=fake_clock, sleep=fake_clock.sleep, **kwargs)


def test_250_acquires_are_instant(fake_clock):
    limiter = make(fake_clock)
    for _ in range(250):
        assert limiter.acquire() == 0.0
    assert fake_clock.slept == []


def test_251st_sleeps_until_window_frees(fake_clock):
    limiter = make(fake_clock)
    for i in range(250):
        fake_clock.t = i * 0.01
        limiter.acquire()
    fake_clock.t = 5.0
    slept = limiter.acquire()
    assert fake_clock.slept == [pytest.approx(5.0)]  # oldest (t=0) + 10 - 5
    assert slept == pytest.approx(5.0)
    assert fake_clock.t == pytest.approx(10.0)


def test_items_weight(fake_clock):
    limiter = make(fake_clock)
    assert limiter.acquire(200) == 0.0
    assert limiter.acquire(50) == 0.0
    slept = limiter.acquire(1)
    assert slept == pytest.approx(10.0)
    assert fake_clock.slept == [pytest.approx(10.0)]


def test_window_eviction(fake_clock):
    limiter = make(fake_clock)
    limiter.acquire(250)
    fake_clock.advance(10.0)
    assert limiter.acquire(250) == 0.0
    assert fake_clock.slept == []


def test_batch_over_limit_raises(fake_clock):
    limiter = make(fake_clock)
    with pytest.raises(UrlError, match="batch of 251 items exceeds 250 per 10 s; split it"):
        limiter.acquire(251)
    assert fake_clock.slept == []


def test_partial_frees_only_when_enough_room(fake_clock):
    limiter = make(fake_clock, limit=10, window=10.0)
    limiter.acquire(5)
    fake_clock.advance(2.0)
    limiter.acquire(5)
    fake_clock.advance(1.0)  # t = 3
    slept = limiter.acquire(6)  # needs both batches gone: second was at t=2 -> frees at 12
    assert slept == pytest.approx(9.0)
    assert fake_clock.slept == [pytest.approx(7.0), pytest.approx(2.0)]
