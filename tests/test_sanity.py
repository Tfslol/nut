"""Sanity test to verify the tooling baseline works end to end."""


def test_tooling_baseline_imports() -> None:
    """Ensure the package is importable from the src layout."""
    import singhacks26  # noqa: F401

    assert singhacks26.__name__ == "singhacks26"
