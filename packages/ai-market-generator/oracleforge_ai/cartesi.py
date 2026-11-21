"""Deterministic compute runner (Cartesi Machine abstraction).

Heavy/statistical work (Monte Carlo forecasting, Bayesian updates) must be
*reproducible*: given the same inputs and seed, every node — and every fraud-proof
replay — gets identical output. These runners use a fixed-seed PRNG and integer
math where it matters so the result is byte-identical across machines.

In production, ``CartesiRunner.run`` dispatches the job into the Cartesi Machine
rollup; here the same deterministic function runs in-process so tests and the
local pipeline reproduce the on-chain result exactly.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import List


@dataclass
class ForecastResult:
    prob_yes: float  # 0..1
    samples: int
    seed: int
    input_hash: str  # sha256 of the canonical input -> ties result to inputs
    ci_low: float = 0.0   # 95% interval lower bound (0..1)
    ci_high: float = 0.0  # 95% interval upper bound (0..1)

    @property
    def prob_bps(self) -> int:
        return max(0, min(10_000, round(self.prob_yes * 10_000)))

    @property
    def ci_low_bps(self) -> int:
        return max(0, min(10_000, round(self.ci_low * 10_000)))

    @property
    def ci_high_bps(self) -> int:
        return max(0, min(10_000, round(self.ci_high * 10_000)))


def _wald_ci(prob: float, samples: int, z: float = 1.96) -> tuple:
    """95% normal-approximation (Wald) interval on a sample proportion. Derived
    purely from `prob` and `samples` (no new randomness), so every node and every
    fraud-proof replay computes identical bounds. Clamped to [0, 1]."""
    if samples <= 0:
        return (prob, prob)
    half = z * math.sqrt(prob * (1.0 - prob) / samples)
    return (max(0.0, round(prob - half, 4)), min(1.0, round(prob + half, 4)))


def _seed_from_inputs(question: str, priors: List[float]) -> int:
    canon = question.strip().lower() + "|" + ",".join(f"{p:.6f}" for p in priors)
    digest = hashlib.sha256(canon.encode()).digest()
    return int.from_bytes(digest[:8], "big")


def monte_carlo_forecast(
    question: str, priors: List[float], base_rate: float = 0.5, samples: int = 50_000
) -> ForecastResult:
    """Deterministic Monte Carlo estimate of P(YES).

    `priors` are per-source directional signals in [-1,1] (positive => favors YES).
    Each sample perturbs a logit built from the base rate and the mean prior, then
    we take the fraction of samples above the decision boundary.
    """
    seed = _seed_from_inputs(question, priors)
    rng = random.Random(seed)

    mean_prior = sum(priors) / len(priors) if priors else 0.0
    # logit of base rate, nudged by aggregate signal
    center = _logit(base_rate) + 1.4 * mean_prior
    spread = 1.0  # signal uncertainty

    hits = 0
    for _ in range(samples):
        draw = center + rng.gauss(0.0, spread)
        if _sigmoid(draw) >= 0.5:
            hits += 1
    prob = hits / samples
    ci_low, ci_high = _wald_ci(prob, samples)
    input_hash = "0x" + hashlib.sha256(
        (question + "|" + ",".join(map(str, priors))).encode()
    ).hexdigest()
    return ForecastResult(
        prob_yes=round(prob, 4), samples=samples, seed=seed, input_hash=input_hash,
        ci_low=ci_low, ci_high=ci_high,
    )


def bayesian_update(prior_prob: float, likelihood_ratio: float) -> float:
    """Posterior YES probability given a likelihood ratio (evidence strength)."""
    prior_odds = prior_prob / (1.0 - prior_prob) if prior_prob < 1.0 else 1e9
    post_odds = prior_odds * likelihood_ratio
    return round(post_odds / (1.0 + post_odds), 4)


# --- small deterministic math helpers (avoid importing numpy) ---
def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


class CartesiRunner:
    """Dispatch deterministic jobs. In-process here; rollup-bound in production."""

    def forecast(self, question: str, priors: List[float], base_rate: float = 0.5) -> ForecastResult:
        return monte_carlo_forecast(question, priors, base_rate)
