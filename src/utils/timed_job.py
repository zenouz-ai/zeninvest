"""Timed scheduler job wrapper — creates runs rows with duration for off-hours jobs."""

from __future__ import annotations

import functools
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from src.utils.logger import get_logger
from src.utils.run_summary import merge_run_summary

logger = get_logger("timed_job")

F = TypeVar("F", bound=Callable[..., Any])

_DASHBOARD_AVAILABLE = False
_Run = None
_get_db_session = None
_log_event = None

try:
    from dashboard.backend.app.database import Run as _RunModel
    from dashboard.backend.app.services.event_logger import log_event as _log_event_fn
    from src.data.database import get_session as _get_session

    _DASHBOARD_AVAILABLE = True
    _Run = _RunModel
    _get_db_session = _get_session
    _log_event = _log_event_fn
except ImportError:
    pass


def timed_job(job_id: str, *, run_type: str | None = None, reraise: bool = False) -> Callable[[F], F]:
    """Decorator that records start/end in runs.summary_json for scheduler handlers."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started_at = datetime.now(timezone.utc)
            cycle_id = f"{run_type or job_id}_{started_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            resolved_run_type = run_type or job_id
            result: dict[str, Any] = {"job_id": job_id}
            status = "completed"
            error_message: str | None = None

            if _DASHBOARD_AVAILABLE and _Run is not None and _get_db_session is not None:
                try:
                    session = _get_db_session()
                    try:
                        session.add(
                            _Run(
                                cycle_id=cycle_id,
                                run_type=resolved_run_type,
                                started_at=started_at,
                                status="running",
                            )
                        )
                        session.commit()
                    except Exception:
                        session.rollback()
                        raise
                    finally:
                        session.close()
                except Exception as exc:
                    logger.debug("Timed job run create failed (fail-open): %s", exc)

            if _DASHBOARD_AVAILABLE and _log_event is not None:
                try:
                    _log_event(
                        event_type="run_started",
                        source="scheduler",
                        message=f"Scheduled job {job_id} starting",
                        metadata={
                            "cycle_id": cycle_id,
                            "run_type": resolved_run_type,
                            "job_id": job_id,
                            "started_at": started_at.isoformat(),
                        },
                    )
                except Exception:
                    pass

            outcome: Any = None
            try:
                outcome = func(*args, **kwargs)
                if isinstance(outcome, dict):
                    result.update(outcome)
            except Exception as exc:
                status = "failed"
                error_message = str(exc)
                result["error_type"] = type(exc).__name__
                result["error_message"] = error_message
                if reraise:
                    raise
            finally:
                completed_at = datetime.now(timezone.utc)
                duration_seconds = (completed_at - started_at).total_seconds()
                summary = merge_run_summary(
                    None,
                    result,
                    duration_seconds=duration_seconds,
                    extra={"job_id": job_id},
                )
                if error_message:
                    summary["error_message"] = error_message

                if _DASHBOARD_AVAILABLE and _Run is not None and _get_db_session is not None:
                    try:
                        session = _get_db_session()
                        try:
                            run = session.query(_Run).filter(_Run.cycle_id == cycle_id).first()
                            if run:
                                run.completed_at = completed_at
                                run.status = status
                                run.summary_json = merge_run_summary(run.summary_json, summary, duration_seconds=duration_seconds)
                            session.commit()
                        except Exception:
                            session.rollback()
                            raise
                        finally:
                            session.close()
                    except Exception as exc:
                        logger.debug("Timed job run update failed (fail-open): %s", exc)

                if _DASHBOARD_AVAILABLE and _log_event is not None:
                    try:
                        _log_event(
                            event_type="run_completed",
                            source="scheduler",
                            message=f"Scheduled job {job_id} {status}",
                            metadata={
                                "cycle_id": cycle_id,
                                "run_type": resolved_run_type,
                                "job_id": job_id,
                                "status": status,
                                "duration_seconds": duration_seconds,
                            },
                        )
                    except Exception:
                        pass

            return outcome

        return wrapper  # type: ignore[return-value]

    return decorator


def run_timed_job(job_id: str, run_type: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a callable inside timed_job instrumentation (non-decorator form)."""
    wrapped = timed_job(job_id, run_type=run_type, reraise=False)(func)
    return wrapped(*args, **kwargs)
