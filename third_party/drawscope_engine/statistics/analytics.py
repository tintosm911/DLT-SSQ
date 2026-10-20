from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import combinations, pairwise
from typing import Literal

from drawscope_engine.protocol.models import (
    AnalysisPayload,
    AnalysisResult,
    BacktestSummary,
    BestPatternValidation,
    DateRange,
    Drawing,
    NumberStatistic,
    PairStatistic,
    PatternSummary,
    RetrospectivePatternAnalysis,
    SignalContribution,
    SignalPerformance,
    SimulationSummary,
    TicketPatternSummary,
    WinningNumberPattern,
)

DISCLAIMERS = [
    "Historical frequency does not change the theoretical probability of a future fair draw.",
    "Every retrospective score uses only drawings that occurred before the tested winning draw.",
    (
        "The pattern search is exploratory and correlated; an isolated high rank can "
        "occur by chance."
    ),
    (
        "The best pattern is selected on an earlier discovery segment and rated only "
        "on a later untouched confirmation segment."
    ),
    (
        "The confidence rating measures historical ranking evidence, not the chance "
        "that a ticket will win."
    ),
    "No retrospective-only rating can exceed 49 out of 100 without prospective validation.",
    "No observed pattern demonstrates a reliable way to predict an independent lottery drawing.",
]
PATTERN_NOTES = [
    (
        "A percentile of 100 means the number ranked at the top of that historical "
        "signal before the draw."
    ),
    "Thirty signal definitions and their weights are fixed before the target is examined.",
    (
        "Walk-forward trials repeatedly hide each winning draw and rebuild every "
        "signal from its earlier history."
    ),
    (
        "The best pattern is chosen on the first 60% of trials and measured on the "
        "remaining 40% without reselection."
    ),
    (
        "Score ties use midrank percentiles; selection cutoffs use a declared SHA-256 "
        "tie-break that is independent of winning numbers."
    ),
]
MIN_BACKTEST_HISTORY = 30
MIN_TARGET_HISTORY = 60
Season = Literal["Winter", "Spring", "Summer", "Autumn"]
ConfidenceLabel = Literal[
    "no_demonstrated_edge",
    "very_low",
    "low",
    "preliminary",
    "tentative_historical_only",
]
Recommendation = Literal[
    "do_not_use_to_choose_numbers",
    "historical_experiment_only",
]
NumberGetter = Callable[[Drawing], list[int]]


class AnalysisInputError(ValueError):
    """Raised when a request is internally inconsistent."""


@dataclass(frozen=True)
class SignalDefinition:
    key: str
    label: str
    weight: float


@dataclass(frozen=True)
class ScoreBundle:
    raw: dict[str, dict[int, float]]
    standardized: dict[str, dict[int, float]]
    composite: dict[int, float]
    ranks: dict[int, int]
    percentiles: dict[int, float]


@dataclass
class StrategySeries:
    label: str
    top_hits: list[int]
    winning_percentiles: list[float]


@dataclass(frozen=True)
class SignalValidation:
    winning_percentile: float
    discovery_lift: float
    confirmation_lift: float


SIGNALS = (
    SignalDefinition("overall", "All prior drawings", 0.04),
    SignalDefinition("recent_5", "Previous 5 drawings", 0.04),
    SignalDefinition("recent_10", "Previous 10 drawings", 0.05),
    SignalDefinition("recent_20", "Previous 20 drawings", 0.05),
    SignalDefinition("recent_30", "Previous 30 drawings", 0.05),
    SignalDefinition("recent_50", "Previous 50 drawings", 0.04),
    SignalDefinition("recent_100", "Previous 100 drawings", 0.04),
    SignalDefinition("recent_250", "Previous 250 drawings", 0.02),
    SignalDefinition("decay_fast", "Exponentially weighted · 5-draw half-life", 0.05),
    SignalDefinition("decay_medium", "Exponentially weighted · 20-draw half-life", 0.05),
    SignalDefinition("decay_slow", "Exponentially weighted · 100-draw half-life", 0.03),
    SignalDefinition("momentum", "Last 10 versus preceding 10", 0.04),
    SignalDefinition("weekday", "Same day of week", 0.05),
    SignalDefinition("month", "Same calendar month", 0.04),
    SignalDefinition("season", "Same season", 0.03),
    SignalDefinition("quarter", "Same calendar quarter", 0.02),
    SignalDefinition("day_of_month", "Same day of month", 0.02),
    SignalDefinition("month_phase", "Same part of month", 0.02),
    SignalDefinition("week_of_month", "Same week of month", 0.02),
    SignalDefinition("iso_week", "Nearby week of year", 0.02),
    SignalDefinition("year_to_date", "Current year to date", 0.04),
    SignalDefinition("previous_year", "Previous calendar year", 0.03),
    SignalDefinition("gap", "Drawings since last seen", 0.04),
    SignalDefinition("gap_relative", "Gap versus historical interval", 0.05),
    SignalDefinition("previous_repeat", "Present in previous draw", 0.02),
    SignalDefinition("previous_neighbor", "Adjacent to a previous-draw number", 0.02),
    SignalDefinition("previous_last_digit", "Shares last digit with previous draw", 0.02),
    SignalDefinition("transition_affinity", "Historically followed previous-draw values", 0.03),
    SignalDefinition("previous_sum_state", "Followed a similar previous-draw sum", 0.02),
    SignalDefinition("previous_parity_state", "Followed the same previous-draw parity", 0.01),
)


def _validate_payload(payload: AnalysisPayload) -> list[Drawing]:
    if payload.main_min > payload.main_max:
        raise AnalysisInputError("main_min must not exceed main_max")
    if payload.draw_count > payload.main_max - payload.main_min + 1 and not payload.ordered:
        raise AnalysisInputError("draw_count exceeds the distinct number pool")
    special_bounds = (payload.special_min, payload.special_max)
    if (special_bounds[0] is None) != (special_bounds[1] is None):
        raise AnalysisInputError("special number bounds must be supplied together")
    if special_bounds[0] is None:
        if payload.special_draw_count != 0:
            raise AnalysisInputError("special_draw_count requires a special number pool")
        if any(drawing.special_number is not None for drawing in payload.draws):
            raise AnalysisInputError("drawing has a special number without a special pool")
    elif (
        special_bounds[0] > special_bounds[1]  # type: ignore[operator]
        or payload.special_draw_count != 1
    ):
        raise AnalysisInputError("special number pool is invalid")

    draw_dates = [drawing.draw_date for drawing in payload.draws]
    if len(draw_dates) != len(set(draw_dates)):
        raise AnalysisInputError("drawings contain duplicate dates")
    normalized = sorted(payload.draws, key=lambda item: item.draw_date, reverse=True)
    for drawing in normalized:
        values = drawing.main_numbers
        if len(values) != payload.draw_count:
            raise AnalysisInputError("drawing has an unexpected main-number count")
        if any(value < payload.main_min or value > payload.main_max for value in values):
            raise AnalysisInputError("drawing number is outside the game era")
        if not payload.ordered and len(values) != len(set(values)):
            raise AnalysisInputError("unordered game contains duplicate main numbers")
        if (
            payload.special_min is not None
            and payload.special_max is not None
            and (
                drawing.special_number is None
                or not (payload.special_min <= drawing.special_number <= payload.special_max)
            )
        ):
            raise AnalysisInputError("drawing special number is outside the game era")
    return normalized


def _season(value: date) -> Season:
    if value.month in (12, 1, 2):
        return "Winter"
    if value.month in (3, 4, 5):
        return "Spring"
    if value.month in (6, 7, 8):
        return "Summer"
    return "Autumn"


def _month_phase(value: date) -> int:
    if value.day <= 10:
        return 1
    if value.day <= 20:
        return 2
    return 3


def _week_of_month(value: date) -> int:
    return (value.day - 1) // 7 + 1


def _main_numbers(drawing: Drawing) -> list[int]:
    return drawing.main_numbers


def _special_numbers(drawing: Drawing) -> list[int]:
    return [] if drawing.special_number is None else [drawing.special_number]


def _frequency_vector(
    draws: Sequence[Drawing],
    pool: Sequence[int],
    getter: NumberGetter,
) -> dict[int, float]:
    counts = Counter(value for drawing in draws for value in getter(drawing))
    return {number: float(counts[number]) for number in pool}


def _rate_difference_vector(
    recent: Sequence[Drawing],
    comparison: Sequence[Drawing],
    pool: Sequence[int],
    getter: NumberGetter,
) -> dict[int, float]:
    recent_counts = _frequency_vector(recent, pool, getter)
    comparison_counts = _frequency_vector(comparison, pool, getter)
    return {
        number: (
            recent_counts[number] / max(1, len(recent))
            - comparison_counts[number] / max(1, len(comparison))
        )
        for number in pool
    }


def _decayed_frequency_vector(
    draws: Sequence[Drawing],
    pool: Sequence[int],
    getter: NumberGetter,
    half_life: float,
) -> dict[int, float]:
    result = {number: 0.0 for number in pool}
    for age, drawing in enumerate(reversed(draws)):
        weight = 0.5 ** (age / half_life)
        for number in getter(drawing):
            result[number] += weight
    return result


def _gap_vector(
    prior: Sequence[Drawing],
    pool: Sequence[int],
    getter: NumberGetter,
) -> dict[int, float]:
    gaps = {number: float(len(prior)) for number in pool}
    unseen = set(pool)
    for gap, drawing in enumerate(reversed(prior)):
        for number in getter(drawing):
            if number in unseen:
                gaps[number] = float(gap)
                unseen.remove(number)
        if not unseen:
            break
    return gaps


def _relative_gap_vector(
    prior: Sequence[Drawing],
    pool: Sequence[int],
    getter: NumberGetter,
) -> dict[int, float]:
    appearances: dict[int, list[int]] = {number: [] for number in pool}
    for index, drawing in enumerate(prior):
        for number in getter(drawing):
            appearances[number].append(index)
    current_gaps = _gap_vector(prior, pool, getter)
    result: dict[int, float] = {}
    for number in pool:
        positions = appearances[number]
        intervals = [float(right - left) for left, right in pairwise(positions)]
        mean_interval = sum(intervals) / len(intervals) if intervals else float(max(1, len(prior)))
        result[number] = current_gaps[number] / max(1.0, mean_interval)
    return result


def _last_seen_gap(
    prior: Sequence[Drawing],
    number: int,
    getter: NumberGetter,
) -> int | None:
    for gap, drawing in enumerate(reversed(prior)):
        if number in getter(drawing):
            return gap
    return None


def _sum_band(
    values: Sequence[int],
    pool_min: int,
    pool_max: int,
) -> int:
    minimum = len(values) * pool_min
    maximum = len(values) * pool_max
    if maximum == minimum:
        return 1
    ratio = (sum(values) - minimum) / (maximum - minimum)
    return min(2, int(ratio * 3))


def _transition_vector(
    prior: Sequence[Drawing],
    pool: Sequence[int],
    getter: NumberGetter,
    context_matches: Callable[[Drawing], bool],
) -> dict[int, float]:
    outcomes = [outcome for context, outcome in pairwise(prior) if context_matches(context)]
    return _frequency_vector(outcomes, pool, getter)


def _signal_vectors(
    prior: Sequence[Drawing],
    target_date: date,
    pool: Sequence[int],
    getter: NumberGetter,
) -> dict[str, dict[int, float]]:
    previous_values = set(getter(prior[-1]))
    pool_min = min(pool)
    pool_max = max(pool)
    weekday_draws = [
        drawing for drawing in prior if drawing.draw_date.weekday() == target_date.weekday()
    ]
    month_draws = [drawing for drawing in prior if drawing.draw_date.month == target_date.month]
    season_draws = [
        drawing for drawing in prior if _season(drawing.draw_date) == _season(target_date)
    ]
    quarter = (target_date.month - 1) // 3
    quarter_draws = [drawing for drawing in prior if (drawing.draw_date.month - 1) // 3 == quarter]
    day_draws = [drawing for drawing in prior if drawing.draw_date.day == target_date.day]
    phase_draws = [
        drawing for drawing in prior if _month_phase(drawing.draw_date) == _month_phase(target_date)
    ]
    week_draws = [
        drawing
        for drawing in prior
        if _week_of_month(drawing.draw_date) == _week_of_month(target_date)
    ]
    target_iso_week = target_date.isocalendar().week
    iso_week_draws = []
    for drawing in prior:
        difference = abs(drawing.draw_date.isocalendar().week - target_iso_week)
        if min(difference, 52 - min(difference, 52)) <= 2:
            iso_week_draws.append(drawing)
    year_to_date_draws = [
        drawing for drawing in prior if drawing.draw_date.year == target_date.year
    ]
    previous_year_draws = [
        drawing for drawing in prior if drawing.draw_date.year == target_date.year - 1
    ]
    previous_sum_band = _sum_band(getter(prior[-1]), pool_min, pool_max)
    previous_parity = sum(number % 2 for number in getter(prior[-1]))
    return {
        "overall": _frequency_vector(prior, pool, getter),
        "recent_5": _frequency_vector(prior[-5:], pool, getter),
        "recent_10": _frequency_vector(prior[-10:], pool, getter),
        "recent_20": _frequency_vector(prior[-20:], pool, getter),
        "recent_30": _frequency_vector(prior[-30:], pool, getter),
        "recent_50": _frequency_vector(prior[-50:], pool, getter),
        "recent_100": _frequency_vector(prior[-100:], pool, getter),
        "recent_250": _frequency_vector(prior[-250:], pool, getter),
        "decay_fast": _decayed_frequency_vector(prior, pool, getter, 5),
        "decay_medium": _decayed_frequency_vector(prior, pool, getter, 20),
        "decay_slow": _decayed_frequency_vector(prior, pool, getter, 100),
        "momentum": _rate_difference_vector(
            prior[-10:],
            prior[-20:-10],
            pool,
            getter,
        ),
        "weekday": _frequency_vector(weekday_draws, pool, getter),
        "month": _frequency_vector(month_draws, pool, getter),
        "season": _frequency_vector(season_draws, pool, getter),
        "quarter": _frequency_vector(quarter_draws, pool, getter),
        "day_of_month": _frequency_vector(day_draws, pool, getter),
        "month_phase": _frequency_vector(phase_draws, pool, getter),
        "week_of_month": _frequency_vector(week_draws, pool, getter),
        "iso_week": _frequency_vector(iso_week_draws, pool, getter),
        "year_to_date": _frequency_vector(year_to_date_draws, pool, getter),
        "previous_year": _frequency_vector(previous_year_draws, pool, getter),
        "gap": _gap_vector(prior, pool, getter),
        "gap_relative": _relative_gap_vector(prior, pool, getter),
        "previous_repeat": {number: float(number in previous_values) for number in pool},
        "previous_neighbor": {
            number: float(any(abs(number - previous) == 1 for previous in previous_values))
            for number in pool
        },
        "previous_last_digit": {
            number: float(any(number % 10 == previous % 10 for previous in previous_values))
            for number in pool
        },
        "transition_affinity": _transition_vector(
            prior,
            pool,
            getter,
            lambda drawing: bool(set(getter(drawing)) & previous_values),
        ),
        "previous_sum_state": _transition_vector(
            prior,
            pool,
            getter,
            lambda drawing: _sum_band(getter(drawing), pool_min, pool_max) == previous_sum_band,
        ),
        "previous_parity_state": _transition_vector(
            prior,
            pool,
            getter,
            lambda drawing: sum(number % 2 for number in getter(drawing)) == previous_parity,
        ),
    }


def _standardize(values: dict[int, float]) -> dict[int, float]:
    mean = sum(values.values()) / len(values)
    variance = sum((value - mean) ** 2 for value in values.values()) / len(values)
    if variance == 0:
        return {number: 0.0 for number in values}
    deviation = math.sqrt(variance)
    return {number: (value - mean) / deviation for number, value in values.items()}


def _percentiles(values: dict[int, float]) -> dict[int, float]:
    if len(values) == 1:
        return {number: 100.0 for number in values}
    result: dict[int, float] = {}
    for number, value in values.items():
        lower = sum(candidate < value for candidate in values.values())
        equal_other = sum(candidate == value for candidate in values.values()) - 1
        percentile = 100 * (lower + 0.5 * equal_other) / (len(values) - 1)
        result[number] = round(percentile, 2)
    return result


def _top_numbers(
    values: dict[int, float],
    count: int,
    tie_break_key: str,
) -> list[int]:
    def tie_break(number: int) -> bytes:
        return hashlib.sha256(f"{tie_break_key}|{number}".encode()).digest()

    return sorted(
        values,
        key=lambda number: (-values[number], tie_break(number), number),
    )[:count]


def _score_pool(
    prior: Sequence[Drawing],
    target_date: date,
    pool: Sequence[int],
    getter: NumberGetter,
) -> ScoreBundle:
    raw = _signal_vectors(prior, target_date, pool, getter)
    standardized = {signal.key: _standardize(raw[signal.key]) for signal in SIGNALS}
    composite = {number: 0.0 for number in pool}
    for signal in SIGNALS:
        for number in pool:
            composite[number] += signal.weight * standardized[signal.key][number]
    ranks = {
        number: 1 + sum(value > composite[number] for value in composite.values())
        for number in pool
    }
    return ScoreBundle(
        raw=raw,
        standardized=standardized,
        composite=composite,
        ranks=ranks,
        percentiles=_percentiles(composite),
    )


def _winning_number_pattern(
    number: int,
    scores: ScoreBundle,
    prior: Sequence[Drawing],
    getter: NumberGetter,
) -> WinningNumberPattern:
    raw = scores.raw
    contributions = [
        SignalContribution(
            key=signal.key,
            label=signal.label,
            raw_value=round(raw[signal.key][number], 4),
            standardized_score=round(
                scores.standardized[signal.key][number],
                4,
            ),
            weighted_contribution=round(
                signal.weight * scores.standardized[signal.key][number],
                4,
            ),
        )
        for signal in SIGNALS
    ]
    contributions.sort(
        key=lambda item: (-item.weighted_contribution, item.key),
    )
    return WinningNumberPattern(
        number=number,
        composite_score=round(scores.composite[number], 4),
        composite_rank=scores.ranks[number],
        composite_percentile=scores.percentiles[number],
        overall_hits=int(raw["overall"][number]),
        last_10_hits=int(raw["recent_10"][number]),
        last_30_hits=int(raw["recent_30"][number]),
        last_100_hits=int(raw["recent_100"][number]),
        same_weekday_hits=int(raw["weekday"][number]),
        same_month_hits=int(raw["month"][number]),
        same_season_hits=int(raw["season"][number]),
        same_day_of_month_hits=int(raw["day_of_month"][number]),
        same_month_phase_hits=int(raw["month_phase"][number]),
        year_to_date_hits=int(raw["year_to_date"][number]),
        previous_year_hits=int(raw["previous_year"][number]),
        gap_before_draw=_last_seen_gap(prior, number, getter),
        repeated_previous_draw=bool(raw["previous_repeat"][number]),
        adjacent_previous_draw=bool(raw["previous_neighbor"][number]),
        top_supporting_signals=contributions[:5],
    )


def _empirical_percentile(
    values: Sequence[float],
    target: float,
) -> float:
    lower = sum(value < target for value in values)
    equal = sum(value == target for value in values)
    return round(100 * (lower + 0.5 * equal) / len(values), 2)


def _has_consecutive(values: Sequence[int]) -> bool:
    return _max_consecutive_run(values) > 1


def _max_consecutive_run(values: Sequence[int]) -> int:
    maximum = 1
    current = 1
    for left, right in pairwise(sorted(set(values))):
        if right - left == 1:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 1
    return maximum


def _is_prime(value: int) -> bool:
    if value < 2:
        return False
    return all(value % divisor for divisor in range(2, math.isqrt(value) + 1))


def _repeated_last_digit_pairs(values: Sequence[int]) -> int:
    return sum(left % 10 == right % 10 for left, right in combinations(values, 2))


def _population_standard_deviation(values: Sequence[int]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _matching_rate(values: Sequence[int], target: int) -> float:
    return round(sum(value == target for value in values) / len(values), 4)


def _ticket_pattern(
    prior: Sequence[Drawing],
    target: Drawing,
    payload: AnalysisPayload,
) -> TicketPatternSummary:
    target_values = sorted(target.main_numbers)
    target_sum = sum(target_values)
    target_odd_count = sum(value % 2 for value in target_values)
    midpoint = (payload.main_min + payload.main_max) // 2
    target_spread = max(target_values) - min(target_values)
    target_deviation = _population_standard_deviation(target_values)
    target_low_count = sum(value <= midpoint for value in target_values)
    target_prime_count = sum(_is_prime(value) for value in target_values)
    target_multiple_count = sum(value % 3 == 0 for value in target_values)
    target_last_digit_pairs = _repeated_last_digit_pairs(target_values)
    target_max_run = _max_consecutive_run(target_values)

    prior_sums = [float(sum(drawing.main_numbers)) for drawing in prior]
    prior_odd_counts = [sum(value % 2 for value in drawing.main_numbers) for drawing in prior]
    prior_spreads = [
        float(max(drawing.main_numbers) - min(drawing.main_numbers)) for drawing in prior
    ]
    prior_deviations = [_population_standard_deviation(drawing.main_numbers) for drawing in prior]
    prior_low_counts = [
        sum(value <= midpoint for value in drawing.main_numbers) for drawing in prior
    ]
    prior_prime_counts = [
        sum(_is_prime(value) for value in drawing.main_numbers) for drawing in prior
    ]
    prior_multiple_counts = [
        sum(value % 3 == 0 for value in drawing.main_numbers) for drawing in prior
    ]
    prior_last_digit_pairs = [_repeated_last_digit_pairs(drawing.main_numbers) for drawing in prior]
    prior_max_runs = [_max_consecutive_run(drawing.main_numbers) for drawing in prior]
    consecutive_rate = sum(_has_consecutive(drawing.main_numbers) for drawing in prior) / len(prior)
    repeat_events = sum(
        bool(set(previous.main_numbers) & set(current.main_numbers))
        for previous, current in pairwise(prior)
    )
    repeated = len(set(prior[-1].main_numbers) & set(target_values))

    pair_counts: Counter[tuple[int, int]] = Counter()
    triple_counts: Counter[tuple[int, int, int]] = Counter()
    for drawing in prior:
        values = sorted(set(drawing.main_numbers))
        pair_counts.update(combinations(values, 2))
        triple_counts.update(combinations(values, 3))
    target_pairs = list(combinations(target_values, 2))
    target_triples = list(combinations(target_values, 3))
    return TicketPatternSummary(
        main_sum=target_sum,
        sum_percentile=_empirical_percentile(prior_sums, float(target_sum)),
        odd_count=target_odd_count,
        odd_even_prior_rate=_matching_rate(
            prior_odd_counts,
            target_odd_count,
        ),
        has_consecutive_numbers=_has_consecutive(target_values),
        consecutive_prior_rate=round(consecutive_rate, 4),
        repeated_from_previous_draw=repeated,
        repeat_prior_rate=round(
            repeat_events / max(1, len(prior) - 1),
            4,
        ),
        historical_pair_occurrences=sum(pair_counts[pair] for pair in target_pairs),
        pairs_seen_before=sum(pair_counts[pair] > 0 for pair in target_pairs),
        pair_count=len(target_pairs),
        historical_triple_occurrences=sum(triple_counts[triple] for triple in target_triples),
        triples_seen_before=sum(triple_counts[triple] > 0 for triple in target_triples),
        triple_count=len(target_triples),
        spread=target_spread,
        spread_percentile=_empirical_percentile(
            prior_spreads,
            float(target_spread),
        ),
        standard_deviation=round(target_deviation, 2),
        standard_deviation_percentile=_empirical_percentile(
            prior_deviations,
            target_deviation,
        ),
        low_count=target_low_count,
        low_high_prior_rate=_matching_rate(
            prior_low_counts,
            target_low_count,
        ),
        prime_count=target_prime_count,
        prime_prior_rate=_matching_rate(
            prior_prime_counts,
            target_prime_count,
        ),
        multiples_of_3_count=target_multiple_count,
        multiples_of_3_prior_rate=_matching_rate(
            prior_multiple_counts,
            target_multiple_count,
        ),
        repeated_last_digit_pairs=target_last_digit_pairs,
        repeated_last_digit_prior_rate=_matching_rate(
            prior_last_digit_pairs,
            target_last_digit_pairs,
        ),
        max_consecutive_run=target_max_run,
        max_consecutive_run_prior_rate=_matching_rate(
            prior_max_runs,
            target_max_run,
        ),
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _expected_top_hits(
    draw_count: int,
    pool_size: int,
) -> float:
    return draw_count * draw_count / pool_size


def _top_hit_variance(
    draw_count: int,
    pool_size: int,
) -> float:
    return (
        draw_count
        * (draw_count / pool_size)
        * (1 - draw_count / pool_size)
        * ((pool_size - draw_count) / (pool_size - 1))
    )


def _lift(
    hits: Sequence[int],
    expected_per_draw: float,
) -> float:
    return _mean([float(value) for value in hits]) / expected_per_draw


def _z_score(
    hits: Sequence[int],
    expected_per_draw: float,
    variance_per_draw: float,
) -> float:
    expected_total = len(hits) * expected_per_draw
    deviation = math.sqrt(len(hits) * variance_per_draw)
    if deviation == 0:
        return 0.0
    return (sum(hits) - expected_total) / deviation


def _confirmation_blocks(
    hits: Sequence[int],
    expected_per_draw: float,
) -> tuple[int, int]:
    block_count = min(4, max(1, len(hits) // 10))
    positive = 0
    for block in range(block_count):
        start = block * len(hits) // block_count
        end = (block + 1) * len(hits) // block_count
        if _lift(hits[start:end], expected_per_draw) > 1:
            positive += 1
    return positive, block_count


def _confidence_rating(
    confirmation_lift: float,
    one_sided_p_value: float,
    positive_blocks: int,
    block_count: int,
) -> tuple[int, ConfidenceLabel, Recommendation]:
    if confirmation_lift <= 1:
        return 0, "no_demonstrated_edge", "do_not_use_to_choose_numbers"
    stability = positive_blocks / block_count
    effect_points = min(6, round((confirmation_lift - 1) * 20))
    stability_points = min(3, round(stability * 3))
    if one_sided_p_value >= 0.10:
        return (
            min(9, max(1, effect_points + stability_points)),
            "very_low",
            "do_not_use_to_choose_numbers",
        )
    if one_sided_p_value >= 0.05:
        return (
            min(19, 10 + effect_points + stability_points),
            "low",
            "do_not_use_to_choose_numbers",
        )
    if one_sided_p_value >= 0.01:
        return (
            min(29, 20 + effect_points + stability_points),
            "preliminary",
            "historical_experiment_only",
        )
    if one_sided_p_value >= 0.001:
        return (
            min(39, 30 + effect_points + stability_points),
            "tentative_historical_only",
            "historical_experiment_only",
        )
    return (
        min(49, 40 + effect_points + stability_points),
        "tentative_historical_only",
        "historical_experiment_only",
    )


def _strategy_values(
    scores: ScoreBundle,
    key: str,
) -> dict[int, float]:
    return scores.composite if key == "composite" else scores.raw[key]


def _select_strategy_key(
    strategies: dict[str, StrategySeries],
    discovery_count: int,
    expected_per_draw: float,
) -> str:
    """Freeze selection using discovery observations only."""
    return max(
        strategies,
        key=lambda key: (
            _lift(
                strategies[key].top_hits[:discovery_count],
                expected_per_draw,
            ),
            _mean(strategies[key].winning_percentiles[:discovery_count]),
            -list(strategies).index(key),
        ),
    )


def _best_pattern_validation(
    strategies: dict[str, StrategySeries],
    target: Drawing,
    target_main_scores: ScoreBundle,
    target_special_scores: ScoreBundle | None,
    payload: AnalysisPayload,
    expected_per_draw: float,
    variance_per_draw: float,
    discovery_count: int,
) -> BestPatternValidation:
    selected_key = _select_strategy_key(
        strategies,
        discovery_count,
        expected_per_draw,
    )
    selected = strategies[selected_key]
    discovery_hits = selected.top_hits[:discovery_count]
    confirmation_hits = selected.top_hits[discovery_count:]
    confirmation_percentiles = selected.winning_percentiles[discovery_count:]
    discovery_lift = _lift(discovery_hits, expected_per_draw)
    confirmation_lift = _lift(confirmation_hits, expected_per_draw)
    z_score = _z_score(
        confirmation_hits,
        expected_per_draw,
        variance_per_draw,
    )
    one_sided_p_value = 0.5 * math.erfc(z_score / math.sqrt(2))
    positive_blocks, block_count = _confirmation_blocks(
        confirmation_hits,
        expected_per_draw,
    )
    confidence_score, confidence_label, recommendation = _confidence_rating(
        confirmation_lift,
        one_sided_p_value,
        positive_blocks,
        block_count,
    )
    target_values = _strategy_values(target_main_scores, selected_key)
    counterfactual_main = _top_numbers(
        target_values,
        payload.draw_count,
        (
            f"1.3.0|{payload.game_id}|{payload.era_id}|"
            f"{target.draw_date.isoformat()}|main|{selected_key}"
        ),
    )
    counterfactual_special: int | None = None
    counterfactual_special_hit: bool | None = None
    if target_special_scores is not None:
        special_values = _strategy_values(
            target_special_scores,
            selected_key,
        )
        counterfactual_special = _top_numbers(
            special_values,
            1,
            (
                f"1.3.0|{payload.game_id}|{payload.era_id}|"
                f"{target.draw_date.isoformat()}|special|{selected_key}"
            ),
        )[0]
        counterfactual_special_hit = target.special_number == counterfactual_special
    label = (
        "30-signal weighted composite"
        if selected_key == "composite"
        else next(signal.label for signal in SIGNALS if signal.key == selected_key)
    )
    return BestPatternValidation(
        key=selected_key,
        label=label,
        discovery_draws=len(discovery_hits),
        confirmation_draws=len(confirmation_hits),
        discovery_top_5_lift=round(discovery_lift, 4),
        confirmation_average_top_5_hits=round(
            _mean([float(value) for value in confirmation_hits]),
            4,
        ),
        expected_average_top_5_hits=round(expected_per_draw, 4),
        confirmation_top_5_lift=round(confirmation_lift, 4),
        confirmation_winning_percentile=round(
            _mean(confirmation_percentiles),
            2,
        ),
        confirmation_z_score=round(z_score, 4),
        one_sided_p_value=round(one_sided_p_value, 6),
        positive_confirmation_blocks=positive_blocks,
        confirmation_blocks=block_count,
        counterfactual_main_numbers=counterfactual_main,
        counterfactual_main_hits=len(set(counterfactual_main) & set(target.main_numbers)),
        counterfactual_special_number=counterfactual_special,
        counterfactual_special_hit=counterfactual_special_hit,
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        rating_scope=(
            "Confidence in a repeatable historical ranking advantage; "
            "not the probability of winning."
        ),
        recommendation=recommendation,
    )


def _walk_forward_backtest(
    chronological: Sequence[Drawing],
    target_index: int,
    payload: AnalysisPayload,
    target_main_scores: ScoreBundle,
    target_special_scores: ScoreBundle | None,
) -> tuple[
    BacktestSummary,
    dict[str, SignalValidation],
    BestPatternValidation,
]:
    start_index = max(
        MIN_BACKTEST_HISTORY,
        target_index - payload.backtest_limit + 1,
    )
    test_indices = range(start_index, target_index + 1)
    main_pool = list(range(payload.main_min, payload.main_max + 1))
    special_pool = (
        list(range(payload.special_min, payload.special_max + 1))
        if payload.special_min is not None and payload.special_max is not None
        else []
    )
    strategies = {
        "composite": StrategySeries(
            label="30-signal weighted composite",
            top_hits=[],
            winning_percentiles=[],
        ),
        **{
            signal.key: StrategySeries(
                label=signal.label,
                top_hits=[],
                winning_percentiles=[],
            )
            for signal in SIGNALS
        },
    }
    special_percentiles: list[float] = []

    for test_index in test_indices:
        prior = chronological[:test_index]
        target = chronological[test_index]
        main_scores = _score_pool(
            prior,
            target.draw_date,
            main_pool,
            _main_numbers,
        )
        values_by_strategy = {
            "composite": main_scores.composite,
            **main_scores.raw,
        }
        for key, values in values_by_strategy.items():
            top_numbers = set(
                _top_numbers(
                    values,
                    payload.draw_count,
                    (
                        f"1.3.0|{payload.game_id}|{payload.era_id}|"
                        f"{target.draw_date.isoformat()}|main|{key}"
                    ),
                )
            )
            percentiles = _percentiles(values)
            strategies[key].top_hits.append(len(top_numbers & set(target.main_numbers)))
            strategies[key].winning_percentiles.append(
                _mean([percentiles[number] for number in target.main_numbers])
            )

        if special_pool and target.special_number is not None:
            special_scores = _score_pool(
                prior,
                target.draw_date,
                special_pool,
                _special_numbers,
            )
            special_percentiles.append(special_scores.percentiles[target.special_number])

    tested_draws = len(strategies["composite"].top_hits)
    discovery_count = max(1, int(tested_draws * 0.60))
    discovery_count = min(discovery_count, tested_draws - 1)
    expected_per_draw = _expected_top_hits(
        payload.draw_count,
        len(main_pool),
    )
    variance_per_draw = _top_hit_variance(
        payload.draw_count,
        len(main_pool),
    )
    composite = strategies["composite"]
    composite_hits = composite.top_hits
    composite_z = _z_score(
        composite_hits,
        expected_per_draw,
        variance_per_draw,
    )
    composite_two_sided_p = math.erfc(abs(composite_z) / math.sqrt(2))
    evidence_grade: Literal[
        "within_chance_range",
        "above_chance_range",
        "below_chance_range",
    ]
    if composite_two_sided_p < 0.05 and composite_z > 0:
        evidence_grade = "above_chance_range"
    elif composite_two_sided_p < 0.05:
        evidence_grade = "below_chance_range"
    else:
        evidence_grade = "within_chance_range"
    backtest = BacktestSummary(
        tested_draws=tested_draws,
        start=chronological[start_index].draw_date,
        end=chronological[target_index].draw_date,
        average_top_5_hits=round(
            _mean([float(value) for value in composite_hits]),
            4,
        ),
        expected_average_top_5_hits=round(expected_per_draw, 4),
        top_5_lift=round(
            _lift(composite_hits, expected_per_draw),
            4,
        ),
        any_top_5_hit_draws=sum(value > 0 for value in composite_hits),
        winning_number_average_percentile=round(
            _mean(composite.winning_percentiles),
            2,
        ),
        special_ball_average_percentile=(
            round(_mean(special_percentiles), 2) if special_percentiles else None
        ),
        z_score=round(composite_z, 4),
        two_sided_p_value=round(composite_two_sided_p, 6),
        evidence_grade=evidence_grade,
    )
    signal_validations = {
        signal.key: SignalValidation(
            winning_percentile=round(
                _mean(strategies[signal.key].winning_percentiles),
                2,
            ),
            discovery_lift=round(
                _lift(
                    strategies[signal.key].top_hits[:discovery_count],
                    expected_per_draw,
                ),
                4,
            ),
            confirmation_lift=round(
                _lift(
                    strategies[signal.key].top_hits[discovery_count:],
                    expected_per_draw,
                ),
                4,
            ),
        )
        for signal in SIGNALS
    }
    best_pattern = _best_pattern_validation(
        strategies,
        chronological[target_index],
        target_main_scores,
        target_special_scores,
        payload,
        expected_per_draw,
        variance_per_draw,
        discovery_count,
    )
    return backtest, signal_validations, best_pattern


def _retrospective_analysis(
    drawings: Sequence[Drawing],
    payload: AnalysisPayload,
) -> RetrospectivePatternAnalysis:
    chronological = sorted(
        drawings,
        key=lambda drawing: drawing.draw_date,
    )
    target_date = payload.target_draw_date or chronological[-1].draw_date
    target_index = next(
        (index for index, drawing in enumerate(chronological) if drawing.draw_date == target_date),
        -1,
    )
    if target_index < MIN_TARGET_HISTORY:
        raise AnalysisInputError("target draw is missing or has fewer than 60 earlier drawings")
    target = chronological[target_index]
    prior = chronological[:target_index]
    main_pool = list(range(payload.main_min, payload.main_max + 1))
    main_scores = _score_pool(
        prior,
        target.draw_date,
        main_pool,
        _main_numbers,
    )
    main_patterns = [
        _winning_number_pattern(
            number,
            main_scores,
            prior,
            _main_numbers,
        )
        for number in sorted(target.main_numbers)
    ]
    special_pattern: WinningNumberPattern | None = None
    special_scores: ScoreBundle | None = None
    if (
        payload.special_min is not None
        and payload.special_max is not None
        and target.special_number is not None
    ):
        special_pool = list(range(payload.special_min, payload.special_max + 1))
        special_scores = _score_pool(
            prior,
            target.draw_date,
            special_pool,
            _special_numbers,
        )
        special_pattern = _winning_number_pattern(
            target.special_number,
            special_scores,
            prior,
            _special_numbers,
        )

    backtest, signal_validations, best_pattern = _walk_forward_backtest(
        chronological,
        target_index,
        payload,
        main_scores,
        special_scores,
    )
    signal_results: list[SignalPerformance] = []
    for signal in SIGNALS:
        target_percentiles = _percentiles(main_scores.raw[signal.key])
        validation = signal_validations[signal.key]
        signal_results.append(
            SignalPerformance(
                key=signal.key,
                label=signal.label,
                weight=signal.weight,
                target_winning_percentile=round(
                    _mean([target_percentiles[number] for number in target.main_numbers]),
                    2,
                ),
                backtest_winning_percentile=(validation.winning_percentile),
                discovery_top_5_lift=validation.discovery_lift,
                confirmation_top_5_lift=validation.confirmation_lift,
            )
        )
    return RetrospectivePatternAnalysis(
        target_draw_date=target.draw_date,
        day_of_week=target.draw_date.strftime("%A"),
        month=target.draw_date.strftime("%B"),
        season=_season(target.draw_date),
        history_size=len(prior),
        target_main_numbers=sorted(target.main_numbers),
        target_special_number=target.special_number,
        main_number_patterns=main_patterns,
        special_number_pattern=special_pattern,
        ticket_pattern=_ticket_pattern(prior, target, payload),
        signals=signal_results,
        best_pattern=best_pattern,
        backtest=backtest,
        notes=PATTERN_NOTES,
    )


def analyze(payload: AnalysisPayload) -> AnalysisResult:
    validated_drawings = _validate_payload(payload)
    draws = [drawing.main_numbers for drawing in validated_drawings]
    frequency = Counter(value for values in draws for value in values)
    sample_size = len(draws)
    pool_size = payload.main_max - payload.main_min + 1
    expected = sample_size * payload.draw_count / pool_size

    last_seen: dict[int, int] = {}
    for draw_index, values in enumerate(draws):
        for value in values:
            last_seen.setdefault(value, draw_index)

    numbers = [
        NumberStatistic(
            number=value,
            frequency=frequency[value],
            rate=round(frequency[value] / sample_size, 6),
            current_gap=last_seen.get(value),
        )
        for value in range(payload.main_min, payload.main_max + 1)
    ]

    pair_counts: Counter[tuple[int, int]] = Counter()
    for values in draws:
        pair_counts.update(combinations(sorted(set(values)), 2))
    top_pairs = [
        PairStatistic(numbers=pair, count=count)
        for pair, count in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:12]
    ]

    odd_even: Counter[str] = Counter()
    consecutive_draws = 0
    sums: list[int] = []
    for values in draws:
        odd_count = sum(value % 2 for value in values)
        odd_even[f"{odd_count} odd / {len(values) - odd_count} even"] += 1
        if _has_consecutive(values):
            consecutive_draws += 1
        sums.append(sum(values))

    chi_square = sum(
        ((frequency[value] - expected) ** 2) / expected
        for value in range(payload.main_min, payload.main_max + 1)
    )

    rng = random.Random(payload.seed)
    simulated_frequency: Counter[int] = Counter()
    pool = list(range(payload.main_min, payload.main_max + 1))
    for _ in range(payload.simulation_trials):
        if payload.ordered:
            simulated_frequency.update(
                rng.choices(pool, k=payload.draw_count),
            )
        else:
            simulated_frequency.update(rng.sample(pool, payload.draw_count))

    simulated_values = [simulated_frequency[value] for value in pool]
    theoretical_combinations = (
        pool_size**payload.draw_count
        if payload.ordered
        else math.comb(pool_size, payload.draw_count)
    )
    if payload.special_min is not None and payload.special_max is not None:
        theoretical_combinations *= math.comb(
            payload.special_max - payload.special_min + 1,
            payload.special_draw_count,
        )

    sorted_dates = sorted(drawing.draw_date for drawing in validated_drawings)
    return AnalysisResult(
        game_id=payload.game_id,
        era_id=payload.era_id,
        sample_size=sample_size,
        date_range=DateRange(
            start=sorted_dates[0],
            end=sorted_dates[-1],
        ),
        theoretical_jackpot_odds=(f"1 in {theoretical_combinations:,}"),
        chi_square_statistic=round(chi_square, 4),
        numbers=numbers,
        top_pairs=top_pairs,
        patterns=PatternSummary(
            mean_sum=round(sum(sums) / len(sums), 2),
            odd_even=dict(sorted(odd_even.items())),
            consecutive_draws=consecutive_draws,
        ),
        simulation=SimulationSummary(
            seed=payload.seed,
            trials=payload.simulation_trials,
            min_frequency=min(simulated_values),
            max_frequency=max(simulated_values),
        ),
        retrospective=_retrospective_analysis(
            validated_drawings,
            payload,
        ),
        disclaimers=DISCLAIMERS,
    )
