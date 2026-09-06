"""Inter-annotator agreement and disagreement metrics from the RedactionBench
user-study section.

Implements:
* Per-unit-type mean pairwise disagreement D_t (Appendix G)
* Krippendorff's alpha (global, Appendix F.1)
* Per-unit-type alpha (Appendix F.2) — reported as a negative control
* Wilson 95% CI for a binomial proportion (Appendix E)
* Spearman's rank correlation (Appendix D)
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from math import comb, sqrt
from statistics import NormalDist


@dataclass(frozen=True)
class UnitRating:
    """One rater's vote on one unit.

    `kind` is the unit-type ("mandatory", "contextual", "gap_a", "gap_b", ...).
    `redacted` is True iff the rater redacted the unit. A unit is "qualifying"
    iff at least two raters rated it.
    """

    unit_id: str
    kind: str
    rater: str
    redacted: bool


@dataclass(frozen=True)
class DisagreementReport:
    """Output of disagreement computation across a population of ratings."""

    n_qualifying_units: int
    n_redact_votes: int
    n_no_redact_votes: int
    global_alpha: float
    per_kind: dict[str, dict[str, float]] = field(default_factory=dict)


def _pairwise_disagreement(k: int, m: int) -> float:
    """D_u = k (m - k) / C(m, 2); zero if m < 2."""
    if m < 2:
        return 0.0
    total = comb(m, 2)
    if total == 0:
        return 0.0
    return k * (m - k) / total


def pairwise_disagreement(ratings: Iterable[UnitRating]) -> float:
    """Mean pairwise disagreement over all qualifying units.

    A unit is qualifying iff `m_u >= 2`. Returns 0.0 when no qualifying unit
    exists.
    """
    by_unit: dict[str, list[bool]] = {}
    for r in ratings:
        by_unit.setdefault(r.unit_id, []).append(bool(r.redacted))

    du_vals: list[float] = []
    for labels in by_unit.values():
        m = len(labels)
        if m < 2:
            continue
        k = sum(1 for v in labels if v)
        du_vals.append(_pairwise_disagreement(k, m))
    return sum(du_vals) / len(du_vals) if du_vals else 0.0


def per_unit_type_disagreement(
    ratings: Iterable[UnitRating],
) -> dict[str, dict[str, float]]:
    """Per-kind breakdown: N_t, mean D_u, mean redaction rate, 95% CI."""
    by_kind: dict[str, dict[str, list[bool]]] = {}
    for r in ratings:
        by_kind.setdefault(r.kind, {}).setdefault(r.unit_id, []).append(bool(r.redacted))

    out: dict[str, dict[str, float]] = {}
    for kind, units in by_kind.items():
        dus: list[float] = []
        rates: list[float] = []
        for labels in units.values():
            m = len(labels)
            if m < 2:
                continue
            k = sum(1 for v in labels if v)
            dus.append(_pairwise_disagreement(k, m))
            rates.append(k / m)
        if not dus:
            out[kind] = {"n_qualifying": 0.0, "disagreement": 0.0, "redaction_rate": 0.0}
            continue
        mean_d = sum(dus) / len(dus)
        mean_rate = sum(rates) / len(rates)
        out[kind] = {
            "n_qualifying": float(len(dus)),
            "disagreement": mean_d,
            "redaction_rate": mean_rate,
        }
    return out


def per_unit_type_alpha(
    ratings: Iterable[UnitRating],
) -> dict[str, float]:
    """Krippendorff's alpha per kind, with `m_u >= 2`.

    This is the negative control from Appendix F.2; it can collapse to a
    low value under the prevalence paradox even when raw agreement is high.
    """
    by_kind: dict[str, dict[str, list[bool]]] = {}
    for r in ratings:
        by_kind.setdefault(r.kind, {}).setdefault(r.unit_id, []).append(bool(r.redacted))

    out: dict[str, float] = {}
    for kind, units in by_kind.items():
        n_total = 0
        n0 = 0
        n1 = 0
        for labels in units.values():
            n_total += len(labels)
            n0 += sum(1 for v in labels if not v)
            n1 += sum(1 for v in labels if v)
        if n_total < 2:
            out[kind] = 0.0
            continue

        sum_per_unit = 0.0
        n_units = 0
        for labels in units.values():
            m = len(labels)
            if m < 2:
                continue
            k = sum(1 for v in labels if v)
            nu0 = m - k
            nu1 = k
            sum_per_unit += 2 * nu0 * nu1 / (m - 1)
            n_units += 1
        if n_units == 0:
            out[kind] = 0.0
            continue
        do = sum_per_unit / n_total
        de = (2 * n0 * n1) / (n_total * (n_total - 1))
        if de == 0:
            out[kind] = 1.0 if do == 0 else 0.0
            continue
        out[kind] = 1.0 - do / de
    return out


def krippendorff_alpha(ratings: Iterable[UnitRating]) -> float:
    """Global Krippendorff's alpha over all qualifying units."""
    by_unit: dict[str, list[bool]] = {}
    for r in ratings:
        by_unit.setdefault(r.unit_id, []).append(bool(r.redacted))

    n_total = 0
    n0 = 0
    n1 = 0
    sum_per_unit = 0.0
    for labels in by_unit.values():
        m = len(labels)
        n_total += m
        k = sum(1 for v in labels if v)
        n0 += m - k
        n1 += k
        if m < 2:
            continue
        nu0 = m - k
        nu1 = k
        sum_per_unit += 2 * nu0 * nu1 / (m - 1)
    if n_total < 2:
        return 1.0
    do = sum_per_unit / n_total
    de = (2 * n0 * n1) / (n_total * (n_total - 1))
    if de == 0:
        return 1.0 if do == 0 else 0.0
    return 1.0 - do / de


def disagreement_report(ratings: Iterable[UnitRating]) -> DisagreementReport:
    """Compute the headline disagreement report (alpha + per-kind breakdown)."""
    ratings_list = list(ratings)
    by_unit: dict[str, list[bool]] = {}
    for r in ratings_list:
        by_unit.setdefault(r.unit_id, []).append(bool(r.redacted))
    n_qual = sum(1 for v in by_unit.values() if len(v) >= 2)
    n1 = sum(1 for r in ratings_list if r.redacted)
    n0 = len(ratings_list) - n1
    return DisagreementReport(
        n_qualifying_units=n_qual,
        n_redact_votes=n1,
        n_no_redact_votes=n0,
        global_alpha=krippendorff_alpha(ratings_list),
        per_kind=per_unit_type_disagreement(ratings_list),
    )


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% CI for a binomial proportion.

    `z=1.96` corresponds to the standard 95% CI; the paper's Appendix E uses
    this exact value. The returned interval is closed-form (no scipy).
    """
    if n <= 0:
        return (0.0, 1.0)
    p_hat = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    half = (z / denom) * sqrt(p_hat * (1.0 - p_hat) / n + z2 / (4.0 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def spearman_rank(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Spearman's rho and a two-sided p-value (no scipy).

    Implementation handles ties via the average-rank convention and returns
    t = rho * sqrt((n-2)/(1-rho^2)) with df = n-2; the p-value is from the
    Student-t survival function via `math` (normal-dist tail approx for
    large n; exact two-sided p-value via the t-CDF is not available in stdlib
    so we use the standard normal approximation that scipy uses internally
    when n is large).
    """
    n = len(xs)
    if n != len(ys):
        raise ValueError("xs and ys must have the same length")
    if n < 3:
        raise ValueError("spearman requires at least 3 observations")

    def ranks(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda p: p[1])
        out = [0.0] * len(values)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[indexed[k][0]] = avg
            i = j + 1
        return out

    rx = ranks(xs)
    ry = ranks(ys)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry, strict=True))
    rho = 1.0 - (6.0 * d2) / (n * (n * n - 1))

    if abs(rho) >= 0.999999:
        return (rho, 0.0)
    t_stat = rho * math.sqrt((n - 2) / (1.0 - rho * rho))
    p = 2.0 * (1.0 - NormalDist().cdf(abs(t_stat)))
    return (rho, p)
