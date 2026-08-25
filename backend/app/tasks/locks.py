"""Per-device advisory locks for collection tasks.

The beat tick is fixed at 60s, but one device's collection can take longer —
measured p90 31s / max 31.2s on a PA-440, and a device with many interfaces or
a slow management plane will exceed 60s. Without a lock the next tick starts a
*second* collection of the same device: two SSH sessions competing for the same
CLI, double the API requests on the management plane that is already the
bottleneck. That makes each collection slower, which guarantees more overlap on
the following tick. It amplifies rather than degrades, so it has to be blocked
at the door instead of tuned around.

The lock is advisory and self-expiring. A worker killed mid-collect leaves the
key behind, and the TTL drops it — a crash can never permanently wedge a device.
Release is a compare-and-delete on a per-acquisition token, so a task that
overran its TTL cannot delete the lock a *later* task legitimately holds.

Skips are recorded rather than silently swallowed: `collect_skips()` exposes
them so falling behind surfaces as an alert instead of as quietly missing data
points (design constraint 5).
"""

import logging
import os
import time
from contextlib import contextmanager

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "ngfw:collect:lock:"
_SKIP_KEY = "ngfw:collect:skips"

# Release only if we still own the lock. Without the token comparison, a task
# that overran its TTL would delete the successor's lock on the way out.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    """Process-local Redis client.

    Celery's prefork workers each get their own; a client created before the
    fork would share a socket across processes.
    """
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


@contextmanager
def device_collect_lock(device_id: str, ttl: int | None = None):
    """Hold the collection lock for one device. Yields False if already held.

    The caller must check the yielded value — the context manager does not
    raise, because "someone else is already collecting this device" is normal
    operation, not an error.
    """
    ttl = ttl or settings.collect_lock_ttl
    key = f"{_LOCK_PREFIX}{device_id}"
    token = f"{os.getpid()}:{time.monotonic_ns()}"

    try:
        acquired = bool(_redis().set(key, token, nx=True, ex=ttl))
    except redis.RedisError as e:
        # Redis is also the Celery broker: if it is unreachable, this task was
        # never dispatched. Reaching here means a transient blip, so fall
        # through unlocked rather than skipping a whole collection cycle.
        logger.warning("collect lock unavailable for %s, running unlocked: %s", device_id, e)
        yield True
        return

    if not acquired:
        _record_skip(device_id)
        logger.warning(
            "device %s is still being collected, skipping this cycle "
            "(collection is taking longer than the beat interval)", device_id,
        )
        yield False
        return

    try:
        yield True
    finally:
        try:
            _redis().eval(_RELEASE_LUA, 1, key, token)
        except redis.RedisError as e:
            logger.warning("could not release collect lock for %s: %s", device_id, e)


def _record_skip(device_id: str) -> None:
    """Count a skipped cycle and stamp when it happened."""
    try:
        pipe = _redis().pipeline()
        pipe.hincrby(_SKIP_KEY, f"{device_id}:count", 1)
        pipe.hset(_SKIP_KEY, f"{device_id}:last", int(time.time()))
        pipe.execute()
    except redis.RedisError:
        pass


def collect_skips() -> dict[str, dict]:
    """Skipped-cycle tally per device: {device_id: {"count": n, "last": epoch}}."""
    try:
        raw = _redis().hgetall(_SKIP_KEY)
    except redis.RedisError:
        return {}

    out: dict[str, dict] = {}
    for field, value in raw.items():
        device_id, _, kind = field.rpartition(":")
        if not device_id:
            continue
        try:
            out.setdefault(device_id, {})[kind] = int(value)
        except ValueError:
            continue
    return out


def reset_collect_skips(device_id: str | None = None) -> None:
    """Clear the tally — for one device, or all of them."""
    try:
        if device_id is None:
            _redis().delete(_SKIP_KEY)
        else:
            _redis().hdel(_SKIP_KEY, f"{device_id}:count", f"{device_id}:last")
    except redis.RedisError:
        pass
