from __future__ import annotations

import pandas as pd

from app.routes.opportunities import make_alternate_books, make_all_available_books


def test_alternate_books_remain_truncated_but_all_books_exposed():
    rows = []
    rows.append({"sportsbook": "BestBook", "point": 7.0, "price": -105.0, "edge_pp": 0.251, "ev_per_dollar": 0.512})
    for idx, book in enumerate(["A", "B", "C", "D", "E", "F", "G"], start=1):
        rows.append({"sportsbook": book, "point": 7.0, "price": -110.0 - idx, "edge_pp": 0.24, "ev_per_dollar": 0.45 - idx * 0.01})

    group = pd.DataFrame(rows)
    selected = group.iloc[0]

    alternates = make_alternate_books(group, selected)
    all_books = make_all_available_books(group, selected)

    assert len(alternates) == 5
    assert len(all_books) == 8
    assert all_books[0]["book"] == "BestBook"
    assert all_books[0]["isBest"] is True
    assert any(row["book"] == "F" for row in all_books)
    assert any(row["book"] == "G" for row in all_books)
