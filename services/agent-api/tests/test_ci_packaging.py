"""CI collection must work the same on Linux and local development."""

from __future__ import annotations

from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_reused_test_helpers_are_importable_as_a_package() -> None:
    # CI installs this project into a clean Linux environment. Without this
    # marker, ``from tests.test_editorial_assist import …`` may resolve a
    # third-party ``tests`` package locally but cannot resolve this suite.
    assert (SERVICE_ROOT / "tests" / "__init__.py").is_file()
