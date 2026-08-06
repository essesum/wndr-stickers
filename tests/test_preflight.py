"""Preflight должен ловить loopback proxy, который Seatbelt режет в runtime."""

from scripts import preflight


def test_blocked_local_proxy_detection_catches_seatbelt_denied_variants():
    assert preflight.is_blocked_local_proxy("http://127.0.0.1:10811")
    assert preflight.is_blocked_local_proxy("localhost:10811")
    assert preflight.is_blocked_local_proxy("localhost.:10811")
    assert preflight.is_blocked_local_proxy("http://[::1]:10811")
    assert preflight.is_blocked_local_proxy("http://[0:0:0:0:0:0:0:1]:10811")


def test_blocked_local_proxy_detection_ignores_empty_external_and_unblocked_ports():
    assert not preflight.is_blocked_local_proxy("")
    assert not preflight.is_blocked_local_proxy("https://proxy.example.com:443")
    assert not preflight.is_blocked_local_proxy("http://127.42.0.1:9999")
