"""
Application Settings
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Core ---
    database_url: str                       # Required — app will not start without this
    secret_key: str                         # Required — signs JWTs

    # --- Secrets with defaults (safe to run locally without these) ---
    callback_secret: str = ""              # GitHub Actions → API shared secret
    github_client_id: str = ""             # GitHub OAuth app client ID
    github_client_secret: str = ""         # GitHub OAuth app client secret
    github_redirect_uri: str = ""          # Must match what GitHub has registered
    github_token: str = ""                 # Fine-grained PAT for triggering workflows
    github_repo: str = ""                  # "org/repo" format, e.g. "acme/outpost"

    # --- Frontend ---
    # Where /auth/github/callback redirects the browser after a successful
    # login: FRONTEND_URL/callback#token=<jwt>.
    frontend_url: str = "http://localhost:3000"

    # --- Auth token lifetimes ---
    # The JWT (access token) is deliberately short-lived now that a refresh
    # flow exists to back it up silently — see services/refresh_tokens.py's
    # module docstring for the full design. Previously this was a flat 24h
    # with no refresh mechanism at all; that traded off session length
    # against blast radius (a leaked 24h token stays valid a long time) for
    # simplicity. It no longer needs to make that trade.
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # --- Refresh cookie attributes ---
    # See services/refresh_tokens.py's set_cookie()/clear_cookie() — both
    # read these, so changing an attribute here changes it consistently
    # everywhere the cookie is touched.
    refresh_cookie_name: str = "outpost_refresh_token"
    # True by default. Browsers treat http://localhost as a secure context
    # (per the W3C spec), so `Secure` cookies work fine there in Chrome and
    # Firefox despite no TLS — this does NOT need to be set False for local
    # `docker compose` dev. Only relevant if serving the UI/API over plain
    # HTTP on a real hostname, which shouldn't happen outside local dev.
    refresh_cookie_secure: bool = True
    # "lax" is correct as long as the UI and API share a registrable domain
    # (e.g. localhost:3000 + localhost:8000 — different ports, same site;
    # or app.example.com + api.example.com in prod). If a real deployment
    # ever puts the UI and API on genuinely different second-level domains,
    # this needs "none" (which in turn requires refresh_cookie_secure=True,
    # since browsers reject SameSite=None without Secure).
    refresh_cookie_samesite: str = "lax"
    # Empty = host-only cookie (recommended default). Set to e.g.
    # ".example.com" only if the UI and API are on different subdomains of
    # the same registrable domain and need to share the cookie.
    refresh_cookie_domain: str = ""

    # --- AWS ---
    aws_region: str = "us-east-1"
    aws_role_arn: str = ""                 # Optional — for assuming a role in Lambda/ECS

    # --- Business rules ---
    max_ttl_hours: int = 168               # 7 days

    # --- Grace period & pause (TTL safety net) ---
    # See routers/environments.py's module docstring, "GRACE PERIOD & PAUSE
    # SAFETY NET", for the full design and why these live here as global
    # platform constants rather than per-environment overrides — same
    # simplicity trade-off already made for max_ttl_hours above.
    expiring_grace_period_hours: int = 24  # RUNNING -> EXPIRING -> (this many hours) -> PAUSING
    paused_max_days: int = 7               # PAUSED -> (this many days) -> DESTROYING, for real

    class Config:
        env_file = ".env"


settings = Settings()