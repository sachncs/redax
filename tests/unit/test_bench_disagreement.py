from __future__ import annotations

import pytest

from app.bench.disagreement import (
    UnitRating,
    disagreement_report,
    krippendorff_alpha,
    pairwise_disagreement,
    per_unit_type_alpha,
    per_unit_type_disagreement,
    spearman_rank,
    wilson_interval,
)


def _worked_example_ratings() -> list[UnitRating]:
    """Encode Table 11 of Appendix H: 10 units rated by 4 users.

    Labels per unit (1=redact, 0=keep): user1..user4.
    """
    rows = [
        (1, "gap_a", [0, 0, 0, 0]),
        (2, "gap_b", [0, 0, 0, 0]),
        (3, "yellow", [1, 0, 1, 0]),
        (4, "red", [1, 1, 1, 1]),
        (5, "yellow", [0, 1, 0, 1]),
        (6, "gap_a", [0, 0, 0, 0]),
        (7, "yellow", [1, 0, 1, 0]),
        (8, "gap_a", [0, 0, 0, 0]),
        (9, "gap_b", [1, 1, 0, 0]),
        (10, "red", [1, 1, 0, 0]),
    ]
    ratings: list[UnitRating] = []
    for unit_id, kind, votes in rows:
        for i, vote in enumerate(votes, start=1):
            ratings.append(
                UnitRating(unit_id=f"u{unit_id}", kind=kind, rater=f"user{i}", redacted=bool(vote))
            )
    return ratings


def test_pairwise_disagreement_global_value_matches_worked_example() -> None:
    assert pairwise_disagreement(_worked_example_ratings()) == pytest.approx(0.333, abs=1e-3)


def test_per_unit_type_disagreement_matches_table_12() -> None:
    per = per_unit_type_disagreement(_worked_example_ratings())
    assert per["red"]["disagreement"] == pytest.approx(0.333, abs=1e-3)
    assert per["yellow"]["disagreement"] == pytest.approx(0.667, abs=1e-3)
    assert per["gap_a"]["disagreement"] == pytest.approx(0.0, abs=1e-3)
    assert per["gap_b"]["disagreement"] == pytest.approx(0.333, abs=1e-3)


def test_global_krippendorff_alpha_matches_worked_example() -> None:
    assert krippendorff_alpha(_worked_example_ratings()) == pytest.approx(0.286, abs=1e-3)


def test_per_unit_type_alpha_matches_table_14_for_red_and_yellow() -> None:
    alphas = per_unit_type_alpha(_worked_example_ratings())
    assert alphas["red"] == pytest.approx(0.222, abs=1e-2)
    assert alphas["yellow"] == pytest.approx(-0.222, abs=1e-2)


def test_per_unit_type_alpha_combined_gap_matches_table_14() -> None:
    """Paper Table 14 reports a single 'Gap' kind that pools g_a and g_b."""
    ratings = [r for r in _worked_example_ratings() if r.kind in {"gap_a", "gap_b"}]
    for r in ratings:
        ratings_with_combined_kind = [
            UnitRating(
                unit_id=r.unit_id,
                kind="gap",
                rater=r.rater,
                redacted=r.redacted,
            )
            for r in ratings
        ]
        break
    alphas = per_unit_type_alpha(ratings_with_combined_kind)
    assert alphas["gap"] == pytest.approx(0.297, abs=1e-2)


def test_krippendorff_alpha_is_one_when_perfect_agreement() -> None:
    ratings = [
        UnitRating(unit_id="u1", kind="red", rater="a", redacted=True),
        UnitRating(unit_id="u1", kind="red", rater="b", redacted=True),
        UnitRating(unit_id="u2", kind="red", rater="a", redacted=False),
        UnitRating(unit_id="u2", kind="red", rater="b", redacted=False),
    ]
    assert krippendorff_alpha(ratings) == pytest.approx(1.0)


def test_disagreement_report_aggregates_counters() -> None:
    ratings = _worked_example_ratings()
    report = disagreement_report(ratings)
    assert report.n_qualifying_units == 10
    assert report.n_redact_votes == 14
    assert report.n_no_redact_votes == 26


def test_wilson_interval_bounds_hold_for_extreme_proportions() -> None:
    lo, hi = wilson_interval(0, 30)
    assert 0.0 <= lo <= hi <= 1.0
    lo, hi = wilson_interval(30, 30)
    assert 0.0 <= lo <= hi <= 1.0
    lo, hi = wilson_interval(15, 30)
    assert lo < 0.5 < hi


def test_spearman_rank_detects_perfect_monotonic_relationship() -> None:
    rho, p = spearman_rank([1, 2, 3, 4, 5], [10, 20, 30, 40, 50])
    assert rho == pytest.approx(1.0, abs=1e-9)
    assert p < 1e-6


def test_spearman_rank_detects_perfect_negative_relationship() -> None:
    rho, _ = spearman_rank([1, 2, 3, 4, 5], [50, 40, 30, 20, 10])
    assert rho == pytest.approx(-1.0, abs=1e-9)
