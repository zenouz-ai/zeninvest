"""Events router - SSE stream for real-time activity feed."""

import asyncio
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc

from src.data.database import get_session
from src.utils.config import get_settings

from ..database import EventsLog
from ..schemas import EventSchema

router = APIRouter()
settings = get_settings()


@router.get("/", response_model=list[EventSchema])
async def get_events(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Get event log history with filtering and pagination."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(EventsLog)

        if event_type:
            query = query.filter(EventsLog.event_type == event_type)

        if source:
            query = query.filter(EventsLog.source == source)

        if start_date:
            query = query.filter(EventsLog.timestamp >= start_date)

        if end_date:
            query = query.filter(EventsLog.timestamp <= end_date)

        events = query.order_by(desc(EventsLog.timestamp)).offset(offset).limit(limit).all()
        return events
    finally:
        session.close()


@router.get("/stream")
async def stream_events(request: Request):
    """Server-Sent Events (SSE) stream for real-time event updates."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    if not settings.dashboard_events_enabled:
        raise HTTPException(status_code=503, detail="Dashboard events are disabled")

    async def event_generator():
        """Generate SSE events."""
        try:
            session = get_session()
            try:
                last_event = (
                    session.query(EventsLog)
                    .order_by(desc(EventsLog.timestamp))
                    .first()
                )
            finally:
                session.close()
            last_timestamp = last_event.timestamp if last_event else datetime.now() - timedelta(hours=1)

            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'message': 'SSE stream connected'})}\n\n"

            # Poll for new events
            while True:
                if await request.is_disconnected():
                    break

                session = get_session()
                try:
                    new_events = (
                        session.query(EventsLog)
                        .filter(EventsLog.timestamp > last_timestamp)
                        .order_by(EventsLog.timestamp)
                        .all()
                    )
                finally:
                    session.close()

                for event in new_events:
                    event_data = {
                        "id": event.id,
                        "timestamp": event.timestamp.isoformat(),
                        "event_type": event.event_type,
                        "source": event.source,
                        "message": event.message,
                        "metadata_json": event.metadata_json,
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"
                    last_timestamp = event.timestamp

                # Keep-alive ping every 30 seconds
                yield ": keepalive\n\n"

                await asyncio.sleep(settings.dashboard_sse_poll_interval_seconds)

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for SSE
        },
    )
