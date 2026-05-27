"""Storage helpers: stock / conversation / notes. All Supabase calls mocked."""
from unittest.mock import MagicMock, patch


def _mock_client(method_chain_result):
    """Build a chainable Supabase mock where .table().select()....execute() → given result."""
    client = MagicMock()
    table = MagicMock()
    client.table.return_value = table
    # every chained method returns the table mock, .execute() returns the result
    for m in ("select", "eq", "order", "limit", "insert", "upsert", "delete"):
        getattr(table, m).return_value = table
    table.execute.return_value = MagicMock(data=method_chain_result)
    return client


def test_stock_set_returns_payload_when_unconfigured():
    with patch("app.storage.stock.get_client", return_value=None):
        from app.storage.stock import set_stock
        out = set_stock("shop1", "case", 50)
    assert out["retailer_id"] == "shop1"
    assert out["product"] == "case"
    assert out["units"] == 50.0


def test_stock_get_returns_empty_when_unconfigured():
    with patch("app.storage.stock.get_client", return_value=None):
        from app.storage.stock import get_stock
        assert get_stock("shop1") == []


def test_stock_set_upserts_when_configured():
    fake = _mock_client([{"retailer_id": "shop1", "product": "case", "units": 50}])
    with patch("app.storage.stock.get_client", return_value=fake):
        from app.storage.stock import set_stock
        out = set_stock("shop1", "case", 50)
    fake.table.assert_called_with("stock_snapshots")
    fake.table().upsert.assert_called_once()
    assert out["product"] == "case"


def test_conversation_recent_returns_in_chrono_order():
    # Supabase returns newest-first; helper reverses to oldest-first.
    fake = _mock_client([
        {"role": "assistant", "content": "newer", "created_at": "2026-05-27T12:01:00Z"},
        {"role": "user", "content": "older", "created_at": "2026-05-27T12:00:00Z"},
    ])
    with patch("app.storage.conversation.get_client", return_value=fake):
        from app.storage.conversation import recent_messages
        out = recent_messages("shop1", limit=16)
    assert [m["content"] for m in out] == ["older", "newer"]


def test_conversation_append_is_silent_when_unconfigured():
    with patch("app.storage.conversation.get_client", return_value=None):
        from app.storage.conversation import append_message
        # Must not raise.
        append_message("shop1", "user", "hi")


def test_notes_add_skips_empty_fact():
    fake = _mock_client([{"id": 1, "fact": "x"}])
    with patch("app.storage.notes.get_client", return_value=fake):
        from app.storage.notes import add_note
        assert add_note("shop1", "   ") is None
        fake.table().insert.assert_not_called()


def test_notes_get_returns_list_of_facts():
    fake = _mock_client([
        {"fact": "closed Sundays", "created_at": "..."},
        {"fact": "sells phones", "created_at": "..."},
    ])
    with patch("app.storage.notes.get_client", return_value=fake):
        from app.storage.notes import get_notes
        out = get_notes("shop1")
    assert out == ["closed Sundays", "sells phones"]
