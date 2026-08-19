"""
Slug derivation for self-serve team creation.

Standalone service (not inlined in routers/teams.py or schemas/team.py) so
it's independently unit-testable and reusable if another slug-bearing
entity shows up later — same reasoning as cost.py / runbook.py living
under services/ rather than inside their router.

Companion to ui/src/pages/Teams.tsx's client-side `slugify()`: that copy
exists purely to give the user a live preview as they type the team name
(Shopify-handle-style UX). It is NOT authoritative — CreateTeamModal omits
`slug` from the request entirely unless the user has manually edited the
field, so in the common case THIS function is the only thing that
determines what actually gets persisted. If the derivation rules here
ever change, the frontend copy should be updated to match, or the preview
will drift from the real saved value (cosmetic only — the backend still
wins — but confusing).
"""

import re

_WHITESPACE_OR_UNDERSCORE = re.compile(r"[_\s]+")
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9-]")
_REPEATED_HYPHENS = re.compile(r"-{2,}")

# Must match CreateTeamRequest.slug's max_length (schemas/team.py).
MAX_SLUG_LENGTH = 50


def generate_slug(name: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """
    Derive a URL-safe, lowercase, hyphenated slug from a team name.

    "Platform Engineering"  -> "platform-engineering"
    "  QA / Test_Infra!! "  -> "qa-test-infra"
    "K8s Platform (EU)"     -> "k8s-platform-eu"

    Returns "" if the name contains no characters that survive the
    filter (e.g. a name made entirely of emoji or punctuation) — callers
    MUST check for this and ask the user to supply a slug explicitly
    rather than persisting an empty string.
    """
    slug = name.strip().lower()
    slug = _WHITESPACE_OR_UNDERSCORE.sub("-", slug)
    slug = _NON_SLUG_CHARS.sub("", slug)
    slug = _REPEATED_HYPHENS.sub("-", slug)
    slug = slug.strip("-")
    # Truncate, then strip again — truncation can leave a trailing hyphen.
    return slug[:max_length].strip("-")