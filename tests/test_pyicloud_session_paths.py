import os

from pyicloud_ipd.base import sanitize_apple_id, session_file_path


def test_sanitize_apple_id_strips_non_word_characters() -> None:
    assert sanitize_apple_id("jdoe@gmail.com") == "jdoegmailcom"


def test_session_file_path_matches_naming_scheme() -> None:
    assert session_file_path("/tmp/cookies", "jdoe@gmail.com") == "/tmp/cookies/jdoegmailcom.session"


def test_session_file_path_expands_user_and_normalizes() -> None:
    result = session_file_path("~/cookies/../cookies", "jdoe@gmail.com")
    assert result == os.path.join(os.path.expanduser("~/cookies"), "jdoegmailcom.session")
