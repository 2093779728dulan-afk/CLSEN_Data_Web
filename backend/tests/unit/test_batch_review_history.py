from unittest.mock import MagicMock, patch

from app.api.batch_reviews import list_batch_reviews


def test_history_filters_site_and_bounds_page() -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = [
        {"id": n, "status": "paused"} for n in range(21)
    ]
    with patch("app.api.batch_reviews._site_id", return_value=5):
        result = list_batch_reviews(MagicMock(), engine, 2)
    query, parameters = connection.execute.call_args.args
    assert "WHERE site_id = :site_id" in str(query)
    assert parameters == {"site_id": 5, "offset": 20}
    items = result["items"]
    assert isinstance(items, list)
    assert len(items) == 20
    assert result["has_next"] is True
