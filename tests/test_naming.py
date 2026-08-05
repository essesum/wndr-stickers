from skill.wndr_stickers.src.naming import allocate, next_version, slugify, versioned_name


def test_slugify_transliterates_and_kebabs():
    assert slugify("Я приношу весь свой объем") == "ya-prinoshu-ves-svoy-obem"
    assert slugify("Со мной все нормально") == "so-mnoy-vse-normalno"
    assert slugify("Пусть все цветы расцветут") == "pust-vse-tsvety-rastsvetut"


def test_slugify_drops_punctuation_and_accent_markers():
    assert slugify("Это не *тантра*!") == "eto-ne-tantra"
    assert slugify("Я сейчас получаю удовольствие") == "ya-seychas-poluchayu-udovolstvie"


def test_slugify_never_returns_empty():
    assert slugify("!!!") == "sticker"


def test_yo_and_hard_sign_do_not_collide_into_nothing():
    # «объем» и «обем» обязаны давать разные исходные фразы, но один slug —
    # это ожидаемо: различие держит сам текст, не имя файла.
    assert slugify("объем") == "obem"
    assert slugify("ёлка") == "elka"


def test_next_version_starts_at_one(tmp_path):
    assert next_version("ya-prinoshu", tmp_path) == 1


def test_next_version_skips_existing(tmp_path):
    for n in (1, 2, 5):
        (tmp_path / versioned_name("ya-prinoshu", n)).write_bytes(b"x")
    assert next_version("ya-prinoshu", tmp_path) == 6


def test_next_version_ignores_other_slugs(tmp_path):
    (tmp_path / "let-all-flowers-bloom-v9.webp").write_bytes(b"x")
    assert next_version("ya-prinoshu", tmp_path) == 1


def test_allocate_never_overwrites_approved(tmp_path):
    (tmp_path / "eto-ne-tantra-v1.webp").write_bytes(b"x")
    slug, version, filename = allocate("Это не *тантра*!", tmp_path)
    assert slug == "eto-ne-tantra"
    assert version == 2
    assert filename == "eto-ne-tantra-v2.webp"
    assert not (tmp_path / filename).exists()
