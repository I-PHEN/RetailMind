"""WhatsApp formatting normalization — guards both legacy + new bullet handling."""
from app.ai.textfmt import to_whatsapp


def test_double_asterisk_bold_collapses_to_single():
    assert to_whatsapp("**bold**") == "*bold*"


def test_markdown_heading_becomes_bold():
    assert to_whatsapp("### Hello") == "*Hello*"


def test_dash_bullets_normalize_to_unicode():
    out = to_whatsapp("- one\n- two\n- three")
    assert out == "• one\n• two\n• three"


def test_asterisk_bullets_normalize_to_unicode():
    out = to_whatsapp("* one\n* two")
    assert out == "• one\n• two"


def test_bold_line_is_not_treated_as_bullet():
    """A line like '*Group header*' must stay bold, not become '• Group header*'."""
    out = to_whatsapp("*What I can do*\n* item one")
    assert "*What I can do*" in out
    assert "• item one" in out
    # Header line stays intact (still wrapped in asterisks)
    assert "• What I can do" not in out


def test_grouped_bullets_block_round_trips_cleanly():
    src = """*What I can do*
- Pull any sales numbers
- Send charts on request

*What I can't do yet*
- See live stock counts"""
    out = to_whatsapp(src)
    assert "*What I can do*" in out
    assert "• Pull any sales numbers" in out
    assert "• See live stock counts" in out
    assert "*What I can't do yet*" in out
