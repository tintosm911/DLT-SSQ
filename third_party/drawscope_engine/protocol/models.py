from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EngineEventType = Literal[
    "analysis_started",
    "analysis_progress",
    "analysis_completed",
    "job_failed",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Drawing(StrictModel):
    draw_date: date
    main_numbers: list[int] = Field(min_length=1)
    special_number: int | None
    multiplier: int | None = Field(default=None, ge=1)


class AnalysisPayload(StrictModel):
    game_id: str = Field(min_length=1)
    era_id: str = Field(min_length=1)
    main_min: int
    main_max: int
    draw_count: int = Field(gt=0)
    special_min: int | None = None
    special_max: int | None = None
    special_draw_count: int = Field(default=0, ge=0)
    ordered: bool
    simulation_trials: int = Field(default=10_000, ge=100, le=1_000_000)
    seed: int = 20_260_728
    target_draw_date: date | None = None
    backtest_limit: int = Field(default=250, ge=30, le=1_000)
    draws: list[Drawing] = Field(min_length=1, max_length=500_000)


class EngineCommand(StrictModel):
    schema_version: Literal["1.0"]
    message_id: UUID
    job_id: UUID
    attempt_id: UUID
    sequence_number: int = Field(ge=1)
    occurred_at: datetime
    type: Literal["analyze_drawings", "health_check"]
    payload: AnalysisPayload | dict[str, str]


class NumberStatistic(StrictModel):
    number: int
    frequency: int = Field(ge=0)
    rate: float = Field(ge=0)
    current_gap: int | None = Field(ge=0)


class PairStatistic(StrictModel):
    numbers: tuple[int, int]
    count: int = Field(ge=0)


class DateRange(StrictModel):
    start: date
    end: date


class PatternSummary(StrictModel):
    mean_sum: float
    odd_even: dict[str, int]
    consecutive_draws: int = Field(ge=0)


class SimulationSummary(StrictModel):
    seed: int
    trials: int = Field(gt=0)
    min_frequency: int = Field(ge=0)
    max_frequency: int = Field(ge=0)


class SignalContribution(StrictModel):
    key: str
    label: str
    raw_value: float
    standardized_score: float
    weighted_contribution: float


class WinningNumberPattern(StrictModel):
    number: int
    composite_score: float
    composite_rank: int = Field(gt=0)
    composite_percentile: float = Field(ge=0, le=100)
    overall_hits: int = Field(ge=0)
    last_10_hits: int = Field(ge=0)
    last_30_hits: int = Field(ge=0)
    last_100_hits: int = Field(ge=0)
    same_weekday_hits: int = Field(ge=0)
    same_month_hits: int = Field(ge=0)
    same_season_hits: int = Field(ge=0)
    same_day_of_month_hits: int = Field(ge=0)
    same_month_phase_hits: int = Field(ge=0)
    year_to_date_hits: int = Field(ge=0)
    previous_year_hits: int = Field(ge=0)
    gap_before_draw: int | None = Field(ge=0)
    repeated_previous_draw: bool
    adjacent_previous_draw: bool
    top_supporting_signals: list[SignalContribution] = Field(max_length=5)


class TicketPatternSummary(StrictModel):
    main_sum: int
    sum_percentile: float = Field(ge=0, le=100)
    odd_count: int = Field(ge=0)
    odd_even_prior_rate: float = Field(ge=0, le=1)
    has_consecutive_numbers: bool
    consecutive_prior_rate: float = Field(ge=0, le=1)
    repeated_from_previous_draw: int = Field(ge=0)
    repeat_prior_rate: float = Field(ge=0, le=1)
    historical_pair_occurrences: int = Field(ge=0)
    pairs_seen_before: int = Field(ge=0)
    pair_count: int = Field(ge=0)
    historical_triple_occurrences: int = Field(ge=0)
    triples_seen_before: int = Field(ge=0)
    triple_count: int = Field(ge=0)
    spread: int = Field(ge=0)
    spread_percentile: float = Field(ge=0, le=100)
    standard_deviation: float = Field(ge=0)
    standard_deviation_percentile: float = Field(ge=0, le=100)
    low_count: int = Field(ge=0)
    low_high_prior_rate: float = Field(ge=0, le=1)
    prime_count: int = Field(ge=0)
    prime_prior_rate: float = Field(ge=0, le=1)
    multiples_of_3_count: int = Field(ge=0)
    multiples_of_3_prior_rate: float = Field(ge=0, le=1)
    repeated_last_digit_pairs: int = Field(ge=0)
    repeated_last_digit_prior_rate: float = Field(ge=0, le=1)
    max_consecutive_run: int = Field(ge=1)
    max_consecutive_run_prior_rate: float = Field(ge=0, le=1)


class SignalPerformance(StrictModel):
    key: str
    label: str
    weight: float = Field(gt=0, le=1)
    target_winning_percentile: float = Field(ge=0, le=100)
    backtest_winning_percentile: float = Field(ge=0, le=100)
    discovery_top_5_lift: float = Field(ge=0)
    confirmation_top_5_lift: float = Field(ge=0)


class BestPatternValidation(StrictModel):
    key: str
    label: str
    discovery_draws: int = Field(gt=0)
    confirmation_draws: int = Field(gt=0)
    discovery_top_5_lift: float = Field(ge=0)
    confirmation_average_top_5_hits: float = Field(ge=0)
    expected_average_top_5_hits: float = Field(ge=0)
    confirmation_top_5_lift: float = Field(ge=0)
    confirmation_winning_percentile: float = Field(ge=0, le=100)
    confirmation_z_score: float
    one_sided_p_value: float = Field(ge=0, le=1)
    positive_confirmation_blocks: int = Field(ge=0)
    confirmation_blocks: int = Field(gt=0)
    counterfactual_main_numbers: list[int] = Field(min_length=1)
    counterfactual_main_hits: int = Field(ge=0)
    counterfactual_special_number: int | None
    counterfactual_special_hit: bool | None
    confidence_score: int = Field(ge=0, le=49)
    confidence_label: Literal[
        "no_demonstrated_edge",
        "very_low",
        "low",
        "preliminary",
        "tentative_historical_only",
    ]
    confidence_cap: Literal[49] = 49
    rating_scope: str
    recommendation: Literal[
        "do_not_use_to_choose_numbers",
        "historical_experiment_only",
    ]


class BacktestSummary(StrictModel):
    tested_draws: int = Field(gt=0)
    start: date
    end: date
    average_top_5_hits: float = Field(ge=0)
    expected_average_top_5_hits: float = Field(ge=0)
    top_5_lift: float = Field(ge=0)
    any_top_5_hit_draws: int = Field(ge=0)
    winning_number_average_percentile: float = Field(ge=0, le=100)
    special_ball_average_percentile: float | None = Field(default=None, ge=0, le=100)
    z_score: float
    two_sided_p_value: float = Field(ge=0, le=1)
    evidence_grade: Literal[
        "within_chance_range",
        "above_chance_range",
        "below_chance_range",
    ]


class RetrospectivePatternAnalysis(StrictModel):
    target_draw_date: date
    day_of_week: str
    month: str
    season: Literal["Winter", "Spring", "Summer", "Autumn"]
    history_size: int = Field(ge=60)
    target_main_numbers: list[int] = Field(min_length=1)
    target_special_number: int | None
    main_number_patterns: list[WinningNumberPattern] = Field(min_length=1)
    special_number_pattern: WinningNumberPattern | None
    ticket_pattern: TicketPatternSummary
    signals: list[SignalPerformance] = Field(min_length=1)
    best_pattern: BestPatternValidation
    backtest: BacktestSummary
    notes: list[str] = Field(min_length=1)


class AnalysisResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    methodology_version: Literal["1.3.0"] = "1.3.0"
    game_id: str
    era_id: str
    sample_size: int = Field(ge=0)
    date_range: DateRange
    theoretical_jackpot_odds: str
    chi_square_statistic: float = Field(ge=0)
    numbers: list[NumberStatistic]
    top_pairs: list[PairStatistic]
    patterns: PatternSummary
    simulation: SimulationSummary
    retrospective: RetrospectivePatternAnalysis
    disclaimers: list[str] = Field(min_length=1)


class EngineEvent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_id: UUID
    job_id: UUID
    attempt_id: UUID
    sequence_number: int = Field(ge=1)
    occurred_at: datetime
    type: EngineEventType
    payload: dict[str, object]
