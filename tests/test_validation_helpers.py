from fedleave.validation import sanitize_text, sanitize_url
import pytest


def test_sanitize_text_strips_and_limits():
    assert sanitize_text("  hello \n") == "hello"


def test_sanitize_text_rejects_null_byte():
    with pytest.raises(ValueError):
        sanitize_text("bad\x00value")


def test_sanitize_url_accepts_http():
    url = "https://example.com/path"
    assert sanitize_url(url) == url


def test_sanitize_url_rejects_non_http():
    with pytest.raises(ValueError):
        sanitize_url("ftp://example.com/file")


def test_sanitize_url_missing_host():
    with pytest.raises(ValueError):
        sanitize_url("https:///no-host")
