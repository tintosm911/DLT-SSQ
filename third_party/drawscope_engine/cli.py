from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import NoReturn
from uuid import uuid4

from pydantic import ValidationError

from drawscope_engine import __version__
from drawscope_engine.protocol.models import (
    AnalysisPayload,
    EngineCommand,
    EngineEvent,
    EngineEventType,
)
from drawscope_engine.statistics.analytics import AnalysisInputError, analyze

MAX_LINE_BYTES = 16 * 1024 * 1024


def _emit(
    command: EngineCommand,
    sequence: int,
    event_type: EngineEventType,
    payload: dict[str, object],
) -> None:
    event = EngineEvent(
        message_id=uuid4(),
        job_id=command.job_id,
        attempt_id=command.attempt_id,
        sequence_number=sequence,
        occurred_at=datetime.now(UTC),
        type=event_type,
        payload=payload,
    )
    print(event.model_dump_json(ensure_ascii=True), flush=True)


def _fail(
    code: str,
    message: str,
    *,
    command: EngineCommand | None = None,
    sequence: int = 1,
) -> NoReturn:
    job_id = command.job_id if command else uuid4()
    attempt_id = command.attempt_id if command else uuid4()
    event = EngineEvent(
        message_id=uuid4(),
        job_id=job_id,
        attempt_id=attempt_id,
        sequence_number=sequence,
        occurred_at=datetime.now(UTC),
        type="job_failed",
        payload={
            "error": {
                "code": code,
                "retryable": False,
                "stage": "analysis",
                "message": message,
                "diagnostic_id": str(uuid4()),
            }
        },
    )
    print(event.model_dump_json(ensure_ascii=True), flush=True)
    raise SystemExit(2)


def process_line(line: str) -> int:
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        _fail("engine.protocol_line_too_large", "The request exceeded the protocol limit.")

    try:
        command = EngineCommand.model_validate_json(line)
    except ValidationError:
        _fail("engine.protocol_invalid", "The engine request did not match contract 1.0.")

    if command.type == "health_check":
        _emit(
            command,
            1,
            "analysis_completed",
            {
                "health": "ok",
                "engine_version": __version__,
                "contract_version": "1.0",
            },
        )
        return 0

    try:
        payload = AnalysisPayload.model_validate(command.payload)
        _emit(
            command,
            1,
            "analysis_started",
            {"sample_size": len(payload.draws), "methodology_version": "1.3.0"},
        )
        result = analyze(payload)
    except (ValidationError, AnalysisInputError):
        _fail(
            "analysis.input_invalid",
            "The drawing set is inconsistent with the selected game era.",
            command=command,
            sequence=2,
        )
    except Exception:
        _fail(
            "analysis.internal_failure",
            "The analytical engine encountered an unexpected internal failure.",
            command=command,
            sequence=2,
        )

    _emit(command, 2, "analysis_completed", {"result": result.model_dump(mode="json")})
    return 0


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        _fail("engine.protocol_empty", "No engine request was received.")
    return process_line(line)


if __name__ == "__main__":
    raise SystemExit(main())
