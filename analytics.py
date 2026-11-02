"""
E-Commerce Business Intelligence Dashboard - Analytics Engine

Uses the SAME SQLAlchemy engine and SQLite database configured in database.py.
Database schema compatibility:
  products(product_id, product_name, category, ...)
  orders(order_id, order_date, order_status, region, ...)
  order_items(item_id, order_id, product_id, quantity, unit_price,
              discount_amount, return_amount)
"""

from pathlib import Path
import pandas as pd

from sqlalchemy import text
from database import engine, init_db, DATABASE_PATH, IS_SQLITE

BASE_DIR = Path(__file__).resolve().parent

# Keep analytics connected to the exact database used by database.py.
DEFAULT_DB_PATH = DATABASE_PATH

# These statuses count toward sales. Cancelled/pending orders are excluded.
ELIGIBLE_STATUSES = {
    "completed", "delivered", "shipped", "processing", "paid"
}


def get_table_names(db_path=None):
    """Return table names from the configured database."""
    if db_path is None:
        with engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )).fetchall()
            return [row[0] for row in rows]

    # Optional explicit SQLite path, useful for tests.
    import sqlite3
    with sqlite3.connect(str(db_path)) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [row[0] for row in rows]


def load_data(db_path=None):
    """Load the three business tables from the configured database."""
    if db_path is None:
        init_db()
        with engine.connect() as connection:
            products = pd.read_sql_query(text("SELECT * FROM products"), connection)
            orders = pd.read_sql_query(text("SELECT * FROM orders"), connection)
            items = pd.read_sql_query(text("SELECT * FROM order_items"), connection)
    else:
        # For explicit SQLite path only.
        import sqlite3
        with sqlite3.connect(str(db_path)) as connection:
            products = pd.read_sql_query("SELECT * FROM products", connection)
            orders = pd.read_sql_query("SELECT * FROM orders", connection)
            items = pd.read_sql_query("SELECT * FROM order_items", connection)

    return products, orders, items


def validate_data(products, orders, items):
    """Raise a clear error when a required table column is missing."""
    required = {
        "products": (products, {"product_id", "product_name", "category"}),
        "orders": (orders, {"order_id", "order_date", "order_status", "region"}),
        "order_items": (items, {"order_id", "product_id", "quantity", "unit_price"}),
    }
    errors = []
    for table, (frame, columns) in required.items():
        missing = columns.difference(frame.columns)
        if missing:
            errors.append(f"{table} missing columns: {', '.join(sorted(missing))}")
    if errors:
        raise ValueError("Invalid database schema: " + "; ".join(errors))
    return True


def prepare_data(db_path=None):
    """
    Join order items to orders/products and calculate sales.

    Gross sales = quantity * unit_price.
    Net sales = gross sales - discount_amount - return_amount.
    discount_amount and return_amount are monetary amounts, not percentages.
    """
    products, orders, items = load_data(db_path)
    validate_data(products, orders, items)

    orders = orders.copy()
    items = items.copy()
    products = products.copy()

    orders["order_date"] = pd.to_datetime(orders["order_date"], errors="coerce")
    orders = orders.dropna(subset=["order_date"])

    for column in ("quantity", "unit_price"):
        items[column] = pd.to_numeric(items[column], errors="coerce").fillna(0)

    # Match the actual database.py schema: discount_amount, not discount.
    if "discount_amount" not in items.columns:
        items["discount_amount"] = 0.0
    if "return_amount" not in items.columns:
        items["return_amount"] = 0.0

    for column in ("discount_amount", "return_amount"):
        items[column] = pd.to_numeric(items[column], errors="coerce").fillna(0).clip(lower=0)

    items = items[
        (items["quantity"] > 0) &
        (items["unit_price"] >= 0)
    ].copy()

    data = items.merge(orders, on="order_id", how="inner", validate="many_to_one")
    data = data.merge(products, on="product_id", how="left", validate="many_to_one")

    data["category"] = data["category"].fillna("Unknown").astype(str)
    data["region"] = data["region"].fillna("Unknown").astype(str)
    data["product_name"] = data["product_name"].fillna("Unknown Product").astype(str)
    data["order_status_clean"] = (
        data["order_status"].fillna("").astype(str).str.strip().str.lower()
    )

    data["gross_sales"] = data["quantity"] * data["unit_price"]
    data["discount"] = data["discount_amount"]
    data["net_sales"] = (
        data["gross_sales"] - data["discount_amount"] - data["return_amount"]
    ).clip(lower=0)

    data["order_date_only"] = data["order_date"].dt.date
    data["month"] = data["order_date"].dt.to_period("M").astype(str)
    data["year"] = data["order_date"].dt.year
    data["eligible"] = data["order_status_clean"].isin(ELIGIBLE_STATUSES)

    return data


def filter_data(data, start_date=None, end_date=None, category=None, region=None):
    """Filter data by date range, category and region."""
    filtered = data.copy()

    if start_date:
        start = pd.to_datetime(start_date, errors="coerce")
        if pd.isna(start):
            raise ValueError("Invalid start date.")
        filtered = filtered[filtered["order_date"] >= start.normalize()]

    if end_date:
        end = pd.to_datetime(end_date, errors="coerce")
        if pd.isna(end):
            raise ValueError("Invalid end date.")
        end_exclusive = end.normalize() + pd.Timedelta(days=1)
        filtered = filtered[filtered["order_date"] < end_exclusive]

    if category and category != "All":
        filtered = filtered[filtered["category"] == category]
    if region and region != "All":
        filtered = filtered[filtered["region"] == region]

    return filtered


def calculate_kpis(data):
    """Calculate sales KPIs for eligible orders."""
    eligible = data[data["eligible"]].copy() if not data.empty else data.copy()
    gross_sales = float(eligible["gross_sales"].sum()) if not eligible.empty else 0.0
    net_sales = float(eligible["net_sales"].sum()) if not eligible.empty else 0.0
    order_count = int(eligible["order_id"].nunique()) if not eligible.empty else 0
    return {
        "gross_sales": round(gross_sales, 2),
        "net_sales": round(net_sales, 2),
        "eligible_orders": order_count,
        "order_count": order_count,
        "average_order_value": round(net_sales / order_count, 2) if order_count else 0.0,
    }


def calculate_revenue_growth(data, start_date=None, end_date=None):
    """Compare net sales in the selected period with the preceding equal-length period."""
    if data.empty:
        return None

    eligible = data[data["eligible"]].copy()
    if start_date and end_date:
        start = pd.to_datetime(start_date, errors="coerce")
        end = pd.to_datetime(end_date, errors="coerce")
        if pd.isna(start) or pd.isna(end) or end < start:
            return None
        start = start.normalize()
        end_exclusive = end.normalize() + pd.Timedelta(days=1)
        days = (end_exclusive - start).days
    else:
        if eligible.empty:
            return None
        start = eligible["order_date"].min().normalize()
        end_exclusive = eligible["order_date"].max().normalize() + pd.Timedelta(days=1)
        days = (end_exclusive - start).days

    previous_start = start - pd.Timedelta(days=days)
    current = eligible[(eligible["order_date"] >= start) & (eligible["order_date"] < end_exclusive)]
    previous = eligible[(eligible["order_date"] >= previous_start) & (eligible["order_date"] < start)]
    current_sales = float(current["net_sales"].sum())
    previous_sales = float(previous["net_sales"].sum())

    if previous_sales == 0:
        return None
    return round(((current_sales - previous_sales) / previous_sales) * 100, 2)


def _group_sales(data, group_column):
    """Shared grouped sales calculation."""
    eligible = data[data["eligible"]].copy()
    if eligible.empty:
        return pd.DataFrame(columns=[group_column, "gross_sales", "net_sales", "orders", "quantity_sold"])
    result = eligible.groupby(group_column, as_index=False).agg(
        gross_sales=("gross_sales", "sum"),
        net_sales=("net_sales", "sum"),
        orders=("order_id", "nunique"),
        quantity_sold=("quantity", "sum"),
    )
    result["gross_sales"] = result["gross_sales"].round(2)
    result["net_sales"] = result["net_sales"].round(2)
    return result.sort_values("net_sales", ascending=False).reset_index(drop=True)


def monthly_sales(data):
    """Return month-wise gross sales, net sales and order count."""
    eligible = data[data["eligible"]].copy()
    if eligible.empty:
        return pd.DataFrame(columns=["month", "gross_sales", "net_sales", "orders"])
    result = eligible.groupby("month", as_index=False).agg(
        gross_sales=("gross_sales", "sum"),
        net_sales=("net_sales", "sum"),
        orders=("order_id", "nunique"),
    ).sort_values("month").reset_index(drop=True)
    result[["gross_sales", "net_sales"]] = result[["gross_sales", "net_sales"]].round(2)
    return result


def sales_by_category(data):
    """Return category-wise sales and order metrics."""
    return _group_sales(data, "category")


def sales_by_region(data):
    """Return region-wise sales and order metrics."""
    return _group_sales(data, "region")


def top_products(data, limit=10):
    """Return top products by net sales."""
    eligible = data[data["eligible"]].copy()
    columns = ["product_name", "category", "net_sales", "quantity_sold", "orders"]
    if eligible.empty:
        return pd.DataFrame(columns=columns)
    result = eligible.groupby(["product_name", "category"], as_index=False).agg(
        net_sales=("net_sales", "sum"),
        quantity_sold=("quantity", "sum"),
        orders=("order_id", "nunique"),
    ).sort_values("net_sales", ascending=False).head(max(1, int(limit))).reset_index(drop=True)
    result["net_sales"] = result["net_sales"].round(2)
    return result


def daily_sales(data):
    """Return daily sales totals."""
    eligible = data[data["eligible"]].copy()
    columns = ["date", "gross_sales", "net_sales", "orders"]
    if eligible.empty:
        return pd.DataFrame(columns=columns)
    eligible["date"] = eligible["order_date"].dt.strftime("%Y-%m-%d")
    result = eligible.groupby("date", as_index=False).agg(
        gross_sales=("gross_sales", "sum"),
        net_sales=("net_sales", "sum"),
        orders=("order_id", "nunique"),
    ).sort_values("date").reset_index(drop=True)
    result[["gross_sales", "net_sales"]] = result[["gross_sales", "net_sales"]].round(2)
    return result


def order_status_summary(data):
    """Count distinct orders by status."""
    if data.empty:
        return pd.DataFrame(columns=["order_status", "orders"])
    orders = data[["order_id", "order_status"]].drop_duplicates()
    return orders.groupby("order_status", as_index=False).agg(
        orders=("order_id", "nunique")
    ).sort_values("orders", ascending=False).reset_index(drop=True)


def get_kpi_definitions():
    """Definitions for report/documentation."""
    return [
        {"name": "Gross Sales", "formula": "Sum of quantity × unit price",
         "exclusions": "Cancelled, pending and unknown statuses are excluded."},
        {"name": "Net Sales", "formula": "Gross sales − discount amount − recorded return amount",
         "exclusions": "Discount and return fields are treated as monetary amounts."},
        {"name": "Eligible Orders", "formula": "Count of distinct eligible order IDs",
         "exclusions": "Cancelled, pending and unknown statuses are excluded."},
        {"name": "Average Order Value", "formula": "Net sales ÷ eligible orders",
         "exclusions": "Returns and discounts affect net sales."},
        {"name": "Revenue Growth", "formula": "(Current period − previous period) ÷ previous period × 100",
         "exclusions": "Unavailable if previous-period sales are zero."},
    ]


def generate_analytics(db_path=None, start_date=None, end_date=None, category=None, region=None):
    """Return the complete analytics payload."""
    data = prepare_data(db_path)
    filtered = filter_data(data, start_date, end_date, category, region)
    return {
        "data": filtered,
        "kpis": calculate_kpis(filtered),
        "revenue_growth": calculate_revenue_growth(filtered, start_date, end_date),
        "monthly_sales": monthly_sales(filtered),
        "category_sales": sales_by_category(filtered),
        "region_sales": sales_by_region(filtered),
        "top_products": top_products(filtered),
        "daily_sales": daily_sales(filtered),
        "order_status": order_status_summary(filtered),
        "kpi_definitions": get_kpi_definitions(),
    }


def export_report(data, output_path=None):
    """Export eligible transaction rows to CSV."""
    eligible = data[data["eligible"]].copy()
    destination = Path(output_path) if output_path else BASE_DIR / "ecommerce_analytics_report.csv"
    if not destination.is_absolute():
        destination = BASE_DIR / destination
    eligible.to_csv(destination, index=False, encoding="utf-8-sig")
    return destination


if __name__ == "__main__":
    print("E-Commerce Business Intelligence - Analytics Test")
    print(f"Database: {DEFAULT_DB_PATH if IS_SQLITE else 'Configured SQL database'}")
    payload = generate_analytics()
    print("\nKPI SUMMARY")
    for name, value in payload["kpis"].items():
        print(f"{name}: {value}")
    print(f"Revenue growth: {payload['revenue_growth']}")
    print("\nMONTHLY SALES")
    print(payload["monthly_sales"].to_string(index=False))
    print("\nCATEGORY SALES")
    print(payload["category_sales"].to_string(index=False))
    print("\nREGIONAL SALES")
    print(payload["region_sales"].to_string(index=False))
    print("\nTOP PRODUCTS")
    print(payload["top_products"].to_string(index=False))
