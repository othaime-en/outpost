"""Unit tests for app.services.slugify.generate_slug — pure function, no
DB/fixtures needed."""

import pytest

from app.services.slugify import generate_slug


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Platform Engineering", "platform-engineering"),
        ("platform-eng", "platform-eng"),  # already a valid slug: no-op
        ("  QA / Test_Infra!!  ", "qa-test-infra"),
        ("K8s Platform (EU)", "k8s-platform-eu"),
        ("Multiple   Spaces", "multiple-spaces"),
        ("under_score_name", "under-score-name"),
        ("---leading-and-trailing---", "leading-and-trailing"),
        ("UPPERCASE", "uppercase"),
        ("MiXeD CaSe Team", "mixed-case-team"),
        ("a--b---c", "a-b-c"),  # collapse repeated hyphens from adjacent bad chars
        ("Team #1 (Alpha)", "team-1-alpha"),
    ],
)
def test_generate_slug_produces_expected_output(name, expected):
    assert generate_slug(name) == expected


def test_generate_slug_returns_empty_string_when_nothing_survives():
    """Names made entirely of characters outside [a-z0-9-] (after
    lowercasing) produce an empty slug. Callers — not this function — are
    responsible for treating that as a 422, since an empty slug being
    silently accepted would violate the NOT NULL constraint anyway."""
    assert generate_slug("🚀🚀🚀") == ""
    assert generate_slug("!!!") == ""
    assert generate_slug("   ") == ""


def test_generate_slug_truncates_to_max_length_without_trailing_hyphen():
    long_name = "word " * 20  # far exceeds 50 chars once hyphenated
    slug = generate_slug(long_name, max_length=20)
    assert len(slug) <= 20
    assert not slug.endswith("-")


def test_generate_slug_respects_custom_max_length():
    assert generate_slug("Platform Engineering", max_length=8) == "platform"