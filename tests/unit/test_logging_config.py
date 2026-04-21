"""Regression tests for telemetry.logs configuration.

Covers issue #14: neo4j.notifications floods the controller log with WARNING
entries every time Cypher references a property/relationship-type that doesn't
exist yet. Unreadable controller logs made debugging the smoke run painful.
"""

from __future__ import annotations

import logging

from formica.telemetry import logs as logs_mod


def _reset_logging_state():
    """configure_logging is idempotent via a flag on the root logger; reset it
    so each test gets a clean pass through the configuration code."""
    root = logging.getLogger()
    if hasattr(root, "_formica_configured"):
        delattr(root, "_formica_configured")


def test_configure_logging_silences_neo4j_notifications():
    _reset_logging_state()
    logs_mod.configure_logging(level=logging.INFO)

    notifications = logging.getLogger("neo4j.notifications")
    assert notifications.level == logging.ERROR, (
        f"neo4j.notifications should be pinned to ERROR (issue #14) but was "
        f"{logging.getLevelName(notifications.level)}."
    )
    # WARNING messages must be suppressed.
    assert not notifications.isEnabledFor(logging.WARNING)
    # ERROR messages must still get through.
    assert notifications.isEnabledFor(logging.ERROR)


def test_configure_logging_leaves_other_neo4j_loggers_alone():
    """Only neo4j.notifications is noisy; the parent neo4j logger should still
    respect the root level so real connection/driver issues are visible."""
    _reset_logging_state()
    logs_mod.configure_logging(level=logging.INFO)

    # Parent neo4j logger has no explicit level set, so effective level follows root.
    parent = logging.getLogger("neo4j")
    assert parent.level in (logging.NOTSET, logging.INFO), (
        f"neo4j (parent) should not be independently quieted; got "
        f"{logging.getLevelName(parent.level)}."
    )
    assert parent.isEnabledFor(logging.WARNING), "neo4j driver WARNINGs must still surface"


def test_configure_logging_is_idempotent_and_still_pins_quiet_loggers():
    """Calling configure_logging twice should not undo the quiet-logger pins
    (and should not double-add handlers)."""
    _reset_logging_state()
    logs_mod.configure_logging(level=logging.INFO)
    handler_count = len(logging.getLogger().handlers)

    # Second call is a no-op via the _formica_configured flag.
    logs_mod.configure_logging(level=logging.INFO)
    assert len(logging.getLogger().handlers) == handler_count

    # But notifications must still be silenced.
    assert logging.getLogger("neo4j.notifications").level == logging.ERROR
