"""HTTP session against fmr.nbtc.go.th/Oper: login, throttle, cache.

The portal sits behind Cloudflare, which rejects non-browser TLS fingerprints,
so every request goes through curl_cffi impersonating Chrome. No browser runs.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

from curl_cffi import requests as cffi

from . import config, parse

BASE = "https://fmr.nbtc.go.th"
LOGIN_PATH = "/Oper/UR/Login.aspx"


class NbtcError(RuntimeError):
    pass


class CloudflareChallenge(NbtcError):
    """Cloudflare answered with a managed challenge instead of the page."""


class LoginFailed(NbtcError):
    pass


class Session:
    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        ver_id: str = "2",
        min_interval: float = 1.5,
        cache_ttl: float = 900,
        state_dir: Path | None = None,
        timeout: float = 60,
    ):
        self._credentials = (username, password) if username and password else None
        self.ver_id = str(ver_id)
        self.min_interval = min_interval
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.state_dir = Path(state_dir) if state_dir else config.state_dir()
        self.requests_sent = 0
        self._last_request = 0.0
        self._http = cffi.Session(impersonate="chrome")
        self._load_cookies()

    # ---------- public ----------

    def get(self, path: str, params=None, *, fresh: bool = False) -> str:
        """GET a portal page as text, logging in first if the session lapsed."""
        url = BASE + path + ("?" + urlencode(params) if params else "")
        return self._cached(("GET", url), fresh, lambda: self._authed("GET", url))

    def post(self, path: str, data: dict, *, fresh: bool = False) -> str:
        """POST a read-only form (the portal's JSON handlers are POST-only)."""
        url = BASE + path
        key = ("POST", url, json.dumps(data, sort_keys=True))
        return self._cached(key, fresh, lambda: self._authed("POST", url, data=data))

    def login(self) -> None:
        user, password = self._credentials or config.load_credentials()
        url = BASE + LOGIN_PATH + "?ReturnUrl=%2fOper%2fISO%2f11%2fFF11ChkSch.aspx"
        page = self._send("GET", url)
        hidden, versions = parse.parse_login_form(page.text)
        if "__VIEWSTATE" not in hidden:
            raise LoginFailed("login form not found at " + LOGIN_PATH)
        if versions and self.ver_id not in versions:
            raise LoginFailed(f"VerID {self.ver_id!r} not offered; choices: {versions}")
        form = {
            **hidden,
            "__EVENTTARGET": "bLogin",
            "__EVENTARGUMENT": "",
            "VerID": self.ver_id,
            "UserName": user,
            "Password": password,
        }
        r = self._send("POST", url, data=form, headers={"Origin": BASE, "Referer": url})
        location = r.headers.get("location") or ""
        if r.status_code != 302 or "Login.aspx" in location:
            raise LoginFailed("the portal did not accept the username/password")
        self._save_cookies()

    # ---------- internals ----------

    def _authed(self, method, url, **kw) -> str:
        r = self._send(method, url, **kw)
        if self._wants_login(r):
            self.login()
            r = self._send(method, url, **kw)
            if self._wants_login(r):
                raise LoginFailed(f"still redirected to login after signing in: {url}")
        if r.status_code != 200:
            raise NbtcError(f"{method} {url} -> HTTP {r.status_code}")
        # The portal's static data scripts are UTF-16 with a BOM and no charset.
        if r.content[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return r.content.decode("utf-16")
        return r.text

    @staticmethod
    def _wants_login(r) -> bool:
        if r.status_code in (301, 302):
            return "Login.aspx" in (r.headers.get("location") or "")
        return r.status_code == 200 and parse.is_login_page(r.text)

    def _send(self, method, url, **kw):
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self._http.request(
                method, url, allow_redirects=False, timeout=self.timeout, **kw
            )
        finally:
            self._last_request = time.monotonic()
            self.requests_sent += 1
        if r.headers.get("cf-mitigated") == "challenge":
            raise CloudflareChallenge(
                f"Cloudflare challenged {method} {url.split('?')[0]} (HTTP {r.status_code})"
            )
        return r

    def _cached(self, key, fresh, fetch) -> str:
        digest = hashlib.sha256("\n".join(key).encode()).hexdigest()
        path = self.state_dir / "cache" / f"{digest}.json"
        if not fresh and self.cache_ttl > 0 and path.is_file():
            entry = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - entry["fetched_at"] < self.cache_ttl:
                return entry["text"]
        text = fetch()
        if self.cache_ttl > 0:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"fetched_at": time.time(), "text": text}), encoding="utf-8"
            )
        return text

    def _cookie_file(self) -> Path:
        return self.state_dir / "cookies.json"

    def _load_cookies(self) -> None:
        path = self._cookie_file()
        if not path.is_file():
            return
        for c in json.loads(path.read_text(encoding="utf-8")):
            self._http.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])

    def _save_cookies(self) -> None:
        path = self._cookie_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        cookies = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self._http.cookies.jar
        ]
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cookies, f)


