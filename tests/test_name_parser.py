from app.onboarding.name_parser import parse_name


def test_standard_intro():
    owner, shop = parse_name("I'm Amina, Amina's Mini-Mart")
    assert owner == "Amina"
    assert "Mini-Mart" in shop


def test_my_name_is_pattern():
    owner, shop = parse_name("My name is John, John's Pharmacy")
    assert owner == "John"
    assert "Pharmacy" in shop


def test_name_only_no_shop():
    owner, shop = parse_name("Amina")
    assert owner == "Amina"
    assert shop == "Amina's Shop"  # default fallback


def test_name_and_shop_no_intro():
    owner, shop = parse_name("Kofi, Kofi Mart")
    assert owner == "Kofi"
    assert "Mart" in shop


def test_strips_punctuation():
    owner, shop = parse_name("  Fatima!  Fatima Stores  ")
    assert owner == "Fatima"
    assert "Stores" in shop
