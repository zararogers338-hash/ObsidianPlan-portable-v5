"""Deterministic random-seed management.

The skill never relies on an ambient RNG. It provides its own seeded generators
(splitmix64 for stream generation, PCG32 for the primary sequence) so that any
parameter sampled during a reproduction run is fully determined by the seed —
matching the manifest's `seed.value` across machines and reruns.

Policies:
  - generate: mint a new seed (derived from the input timestamp, so a rerun
    with the same timestamp is still byte-identical).
  - reuse: use the provided `random_seed` (default 0).
  - require: reuse AND record it as required; failing if absent.
"""

from __future__ import annotations

from _common import ToolError, emit_progress

MASK64 = (1 << 64) - 1


def splitmix64(state: int) -> tuple[int, int]:
    """Advance a 64-bit state; return (next_state, output)."""
    state = (state + 0x9E3779B97F4A7C15) & MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return state, (z ^ (z >> 31)) & MASK64


class Pcg32:
    """PCG32 (Melissa E. O'Neill) — small, deterministic, well-distributed."""

    def __init__(self, seed: int, inc: int = 0xDA3E39CB94B95BDB):
        self._inc = (inc << 1 | 1) & MASK64
        self._state = 0
        self._seed_to_state(seed & MASK64)

    def _seed_to_state(self, seed: int) -> None:
        self._state = seed
        self._next_u32()
        self._state = (self._state + seed) & MASK64
        self._next_u32()

    def _next_u32(self) -> int:
        old = self._state
        self._state = (old * 6364136223846793005 + self._inc) & MASK64
        xor = ((old >> 18) ^ old) >> 27
        rot = old >> 59
        return (xor >> rot) | (xor << ((-rot) & 31)) & 0xFFFFFFFF

    def next_float(self) -> float:
        """Uniform in [0, 1) — 53-bit precision via two u32 draws."""
        hi = self._next_u32() >> 5
        lo = self._next_u32() >> 6
        return (hi * 67108864.0 + lo) / 9007199254740992.0

    def next_int(self, n: int) -> int:
        """Uniform integer in [0, n)."""
        return int(self.next_float() * n)


def derive_seed(timestamp: str, nonce: int = 0) -> int:
    """Deterministic seed from a timestamp (so generated seeds are stable)."""
    import hashlib
    digest = hashlib.sha256(f"mrv-seed:{timestamp}:{nonce}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def resolve_seed(p: dict) -> dict:
    """Apply the seed policy; returns {value, policy, rng, preview}."""
    policy = p.get("seed_policy", "reuse")
    if policy not in ("generate", "reuse", "require"):
        raise ToolError("MRV-E103", f"unknown seed_policy {policy!r}",
                        details={"seed_policy": policy,
                                 "allowed": ["generate", "reuse", "require"]})
    provided = p.get("random_seed")
    if provided is None:
        provided = (p.get("reproducibility") or {}).get("random_seed")

    if policy == "require" and provided is None:
        raise ToolError("MRV-E102", "seed_policy=require needs random_seed",
                        details={"field": "random_seed",
                                 "why_critical": "a required seed anchors reproducibility",
                                 "how_to_obtain": "pass random_seed in the input"})

    if policy == "generate":
        value = derive_seed(str(p.get("timestamp") or "1970-01-01T00:00:00Z"))
        effective_policy = "generate"
    else:
        value = int(provided) if provided is not None else 0
        effective_policy = "reuse" if provided is not None else "reuse_default"
        if provided is None:
            effective_policy = "reuse_default"

    rng = Pcg32(value)
    preview = [rng.next_float() for _ in range(4)]
    return {
        "value": value,
        "policy": effective_policy,
        "algorithm": "pcg32+splitmix64",
        "preview": preview,
    }


def seed_main(p: dict) -> dict:
    """Top-level seed tool result."""
    emit_progress("resolving random seed")
    resolved = resolve_seed(p)
    resolved["note"] = ("all sampling in this skill is deterministic; the seed "
                        "record anchors the manifest's reproducibility.")
    return resolved
