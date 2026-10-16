"""The response cache: entries past cache_ttl are deleted, not only skipped."""
import os
import time

from nbtc_oper.client import Session


def test_writing_an_entry_deletes_the_expired_ones(tmp_path):
    session = Session(state_dir=tmp_path, cache_ttl=900)
    cache = tmp_path / "cache"
    cache.mkdir()
    old, recent = cache / "old.json", cache / "recent.json"
    for path, age in ((old, 3600), (recent, 60)):
        path.write_text('{"fetched_at": 0, "text": ""}', encoding="utf-8")
        os.utime(path, (time.time() - age,) * 2)

    assert session._cached(("GET", "https://x/page"), False, lambda: "page") == "page"
    assert not old.exists()
    assert recent.exists()
    assert len(list(cache.glob("*.json"))) == 2  # recent, and the page just written
    assert session._cached(("GET", "https://x/page"), False, lambda: "refetched") == "page"


def test_the_sweep_runs_at_most_once_per_ttl(tmp_path):
    session = Session(state_dir=tmp_path, cache_ttl=900)
    session._cached(("GET", "https://x/1"), False, lambda: "1")
    stale = tmp_path / "cache" / "stale.json"
    stale.write_text("{}", encoding="utf-8")
    os.utime(stale, (time.time() - 3600,) * 2)
    session._cached(("GET", "https://x/2"), False, lambda: "2")
    assert stale.exists()  # swept a moment ago; the next sweep comes a ttl later
