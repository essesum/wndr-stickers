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


def test_preflight_checks_both_reference_sheets_and_font_file(monkeypatch, tmp_path, capsys):
    retro = tmp_path / "retro.png"
    flat = tmp_path / "flat.png"
    font = tmp_path / "GolosText-Black.ttf"
    retro.write_bytes(b"retro")
    flat.write_bytes(b"flat")
    font.write_bytes(b"font")

    class Settings:
        telegram_bot_token = "x"
        telegram_owner_id = 1
        sticker_pack_owner = 1
        image_provider_chain = "gemini"
        provider_chain = ["gemini"]
        https_proxy = ""
        duplicate_check = False
        stickers_dir = tmp_path / "stickers"
        db_path = tmp_path / "db.sqlite"
        reference_sheet_path = retro
        font_file = font

        def reference_for(self, look):
            assert look == "clean"
            return flat

    monkeypatch.setattr(preflight, "get_settings", lambda: Settings())
    result = __import__("asyncio").run(preflight.main())

    out = capsys.readouterr().out
    assert result == 0
    assert "ретро-референс: retro.png" in out
    assert "плоский референс: flat.png" in out
    assert "шрифт: GolosText-Black.ttf" in out
