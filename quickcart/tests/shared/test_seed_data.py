"""The demo cases every team relies on are really in the seed data."""
import pytest

from shared import db, settings
from shared.testing import build_test_db


@pytest.fixture(autouse=True)
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_PATH", build_test_db(tmp_path))


def test_u1_latest_order_is_out_for_delivery():
    row = db.query_one("SELECT order_id, status FROM orders WHERE user_id = ? ORDER BY placed_at DESC LIMIT 1", ("u1",))
    assert row == {"order_id": "O103", "status": "out_for_delivery"}


def test_u1_last_delivered_order_has_eggs_for_90():
    order = db.query_one("SELECT order_id FROM orders WHERE user_id = ? AND status = 'delivered' "
                         "ORDER BY placed_at DESC LIMIT 1", ("u1",))
    eggs = db.query_one("SELECT unit_price FROM order_items WHERE order_id = ? AND sku = 'SKU-EGGS-6'", (order["order_id"],))
    assert order["order_id"] == "O102" and eggs["unit_price"] == "90.00"


def test_o101_was_25_minutes_late():
    row = db.query_one("SELECT CAST(ROUND((julianday(delivered_at) - julianday(promised_eta)) * 1440) AS INTEGER) AS late "
                       "FROM orders WHERE order_id = 'O101'")
    assert row["late"] == 25


@pytest.mark.parametrize("user, expected", [("u1", 0), ("u2", 3)])
def test_refunds_in_last_30_days(user, expected):
    row = db.query_one("SELECT COUNT(*) AS n FROM refunds WHERE user_id = ? AND issued_at >= datetime('now', '-30 days')", (user,))
    assert row["n"] == expected


def test_peanut_free_substitutes_exclude_the_peanut_bar():
    rows = db.query(
        """SELECT p.sku FROM products p JOIN products src ON src.sku = :sku
           WHERE p.category = src.category AND p.sku <> src.sku AND p.stock > 0
             AND NOT EXISTS (SELECT 1 FROM product_allergens a WHERE a.sku = p.sku AND a.allergen = :allergen)
           ORDER BY ABS(CAST(p.price AS REAL) - CAST(src.price AS REAL)) LIMIT 3""",
        {"sku": "SKU-BAR-NUTTY", "allergen": "peanut"})
    skus = [r["sku"] for r in rows]
    assert "SKU-BAR-PB" not in skus and "SKU-BAR-OAT" in skus and "SKU-BAR-ALMOND" in skus


def test_nutty_bar_is_out_of_stock():
    assert db.query_one("SELECT stock FROM products WHERE sku = 'SKU-BAR-NUTTY'")["stock"] == 0


def test_brand_x_paneer_has_mixed_reviews_and_brand_y_is_limited():
    x = db.query_one("SELECT COUNT(*) AS n, MIN(rating) AS lo, MAX(rating) AS hi FROM reviews WHERE sku = 'SKU-PANEER-X-200'")
    y = db.query_one("SELECT COUNT(*) AS n FROM reviews WHERE sku = 'SKU-PANEER-Y-200'")
    assert x["n"] >= 5 and x["lo"] <= 2 and x["hi"] == 5 and y["n"] < 5


def test_injected_review_exists():
    assert "ignore all previous instructions" in db.query_one("SELECT text FROM reviews WHERE review_id = 'R060'")["text"]


def test_o999_belongs_to_another_user():
    assert db.query_one("SELECT user_id FROM orders WHERE order_id = 'O999'")["user_id"] == "u3"


def test_every_order_total_matches_its_items():
    rows = db.query("""SELECT o.order_id, o.total, SUM(i.qty * CAST(i.unit_price AS REAL)) AS items
                       FROM orders o JOIN order_items i ON i.order_id = o.order_id GROUP BY o.order_id""")
    for r in rows:
        assert abs(float(r["total"]) - r["items"]) < 0.001, r
