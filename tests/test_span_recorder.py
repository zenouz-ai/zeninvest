"""Tests for SpanRecorder."""

import time

from src.utils.span_recorder import SpanRecorder


def test_span_recorder_nested_steps():
    recorder = SpanRecorder(slow_threshold_seconds=0.01)
    with recorder.span("broker_sync"):
        time.sleep(0.02)
    steps = recorder.to_step_dict()
    assert "broker_sync" in steps
    assert steps["broker_sync"] >= 0.01
    assert len(recorder.span_rows()) == 1


def test_span_recorder_inherits_phase_timer():
    recorder = SpanRecorder()
    recorder.start("screening")
    recorder.end()
    phases = recorder.to_dict()
    assert "screening" in phases
    assert phases["screening"]["seconds"] >= 0


def test_slow_steps_tracked():
    recorder = SpanRecorder(slow_threshold_seconds=0.001)
    recorder.record_step("wallet_reconcile", 2.5)
    assert recorder.slow_steps()[0]["step"] == "wallet_reconcile"
