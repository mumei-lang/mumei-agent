"""Tests for Zero-Human Challenge specs and runner.

.. deprecated::
    The suite has been consolidated into ``test_challenge.py``. This module
    keeps a single redirect check so that CI or scripts referencing this
    filename by name still discover a test — previously a star-import made
    pytest collect and run the entire challenge suite twice.
"""

import importlib


def test_consolidated_challenge_suite_exists():
    """The real challenge test module must still be importable."""
    assert importlib.import_module("tests.test_challenge") is not None
