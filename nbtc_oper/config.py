"""Credentials and local state locations. Nothing here may hardcode a secret."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

USER_KEYS = ("NBTC_USER", "NBTC_USERNAME")
PASS_KEYS = ("NBTC_PASS", "NBTC_PASSWORD")


class CredentialsNotFound(RuntimeError):
    pass


def parse_dotenv(path: Path) -> dict:
    """Tolerant dotenv reader: allows spaces around '=' and quoted values."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            out[key] = value.strip().strip('"').strip("'")
    return out


def _first(mapping, keys):
    for key in keys:
        if mapping.get(key):
            return mapping[key]
    return None


def _candidate_files():
    yield Path.cwd() / ".env"
    yield PROJECT_ROOT / ".env"
    override = os.environ.get("NBTC_ENV_FILE")
    if override:
        yield Path(override).expanduser()


def load_credentials() -> tuple[str, str]:
    """Environment first, then ./.env, the project .env, then $NBTC_ENV_FILE."""
    user = _first(os.environ, USER_KEYS)
    password = _first(os.environ, PASS_KEYS)
    tried = []
    for path in _candidate_files():
        if user and password:
            break
        tried.append(str(path))
        if not path.is_file():
            continue
        values = parse_dotenv(path)
        user = user or _first(values, USER_KEYS)
        password = password or _first(values, PASS_KEYS)
    if user and password:
        return user, password
    raise CredentialsNotFound(
        f"NBTC credentials not found. Looked for {USER_KEYS} / {PASS_KEYS} "
        f"in the environment and in: {', '.join(tried)}"
    )


def state_dir() -> Path:
    """Where cookies and the response cache live (gitignored)."""
    override = os.environ.get("NBTC_OPER_STATE_DIR")
    return Path(override).expanduser() if override else PROJECT_ROOT / ".nbtc_oper"
