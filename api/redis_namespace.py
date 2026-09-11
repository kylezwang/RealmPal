"""
Deployment-scoped Redis keys.

Cache and quota keys were global, so pointing two environments at one Redis
meant they silently shared state: a staging scrape would satisfy a production
cache read, and quota counters would be shared across deployments. Rather
than prefix at ~40 call sites and rely on everyone remembering, the prefix is
applied once here, around the client handed out by `get_redis`.

Commands are classified by where their keys sit in the argument list. Anything
unclassified raises instead of silently passing an unprefixed key through,
because a key that escapes the namespace is exactly the bug this prevents.
"""
from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

# Key is the first positional argument.
_SINGLE_KEY_COMMANDS = frozenset(
    {
        "get", "getdel", "getex", "set", "setex", "setnx", "psetex", "append",
        "strlen", "incr", "incrby", "incrbyfloat", "decr", "decrby",
        "expire", "expireat", "pexpire", "ttl", "pttl", "persist", "type",
        "lpush", "rpush", "lpop", "rpop", "llen", "lrange", "ltrim", "lindex",
        "lrem", "lset",
        "sadd", "srem", "smembers", "sismember", "scard",
        "hset", "hget", "hdel", "hgetall", "hkeys", "hvals", "hlen", "hexists",
        "hincrby",
        "zadd", "zrem", "zscore", "zrange", "zrevrange", "zcard", "zincrby",
        "setbit", "getbit", "bitcount",
    }
)

# Every positional argument is a key.
_MULTI_KEY_COMMANDS = frozenset({"exists", "delete", "unlink", "touch", "mget"})

# Connection and server level | no keys involved.
_NO_KEY_COMMANDS = frozenset(
    {
        "ping", "close", "aclose", "info", "dbsize", "echo", "wait",
        # Note: these ignore the namespace and clear the whole database.
        "flushall", "flushdb",
    }
)


class NamespacedRedis:
    """
    Wraps an async Redis client, prefixing every key with `prefix`.

    Deliberately not a subclass of `redis.asyncio.Redis`: subclassing would
    mean overriding `execute_command`, where the key positions are no longer
    visible per command.
    """

    __slots__ = ("_client", "_prefix")

    def __init__(self, client: aioredis.Redis, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    @property
    def prefix(self) -> str:
        return self._prefix

    @property
    def unprefixed(self) -> aioredis.Redis:
        """The underlying client. For migrations and diagnostics only."""
        return self._client

    def key(self, name: str) -> str:
        """The namespaced form of `name`, for callers that need it directly."""
        return f"{self._prefix}{name}"

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        attr = getattr(self._client, name)

        if name in _NO_KEY_COMMANDS:
            return attr

        if name in _SINGLE_KEY_COMMANDS:
            def call_with_prefixed_first(key: Any, *args: Any, **kwargs: Any) -> Any:
                return attr(self.key(key), *args, **kwargs)

            return call_with_prefixed_first

        if name in _MULTI_KEY_COMMANDS:
            def call_with_all_prefixed(*keys: Any, **kwargs: Any) -> Any:
                return attr(*(self.key(k) for k in keys), **kwargs)

            return call_with_all_prefixed

        if callable(attr):
            raise AttributeError(
                f"Redis command '{name}' is not classified in "
                "api/redis_namespace.py. Add it to _SINGLE_KEY_COMMANDS, "
                "_MULTI_KEY_COMMANDS or _NO_KEY_COMMANDS so its keys stay "
                "inside the deployment namespace."
            )
        return attr


def namespaced(client: aioredis.Redis, prefix: str) -> aioredis.Redis:
    """Return `client` scoped to `prefix`, or unchanged when prefix is empty."""
    if not prefix:
        return client
    return NamespacedRedis(client, prefix)  # type: ignore[return-value]
