"""resync.py: what it reports, and the exit code scripts rely on."""

import pytest

import resync
from bookstack.api_client import BookStackAPIError


class Unreachable:
    """A BookStack that cannot be reached, or that refuses the token."""

    def get_all_books(self):
        raise BookStackAPIError("API request failed: refused")


def test_full_resync_of_a_healthy_wiki_exits_zero(
    db_path, fake_bookstack, monkeypatch, capsys
):
    monkeypatch.setattr(resync, "get_bookstack_client", lambda: fake_bookstack)
    assert resync.main(["--full-resync"]) == 0
    assert "pages: 2" in capsys.readouterr().out


def test_an_unreachable_bookstack_is_not_reported_as_success(
    db_path, monkeypatch, capsys
):
    # Regression: the client turned the failed book listing into an empty list, so
    # the run printed "errors: 0" and exited 0 with an empty index (a wrong token
    # was the common cause).
    monkeypatch.setattr(resync, "get_bookstack_client", lambda: Unreachable())
    assert resync.main(["--full-resync"]) == 1
    captured = capsys.readouterr()
    assert "errors: 1" in captured.out
    assert "nothing was pruned" in captured.err


def test_dry_run_reports_the_index(db_path, fake_bookstack, monkeypatch, capsys):
    monkeypatch.setattr(resync, "get_bookstack_client", lambda: fake_bookstack)
    resync.main(["--full-resync"])
    capsys.readouterr()
    assert resync.main(["--dry-run"]) == 0
    assert "Index holds 4 items" in capsys.readouterr().out


def test_without_an_action_it_asks_for_one(db_path, fake_bookstack, monkeypatch):
    monkeypatch.setattr(resync, "get_bookstack_client", lambda: fake_bookstack)
    with pytest.raises(SystemExit):
        resync.main([])
