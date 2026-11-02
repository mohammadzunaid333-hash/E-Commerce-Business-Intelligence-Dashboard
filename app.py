import os
import secrets
import logging
import sqlite3
from pathlib import Path
from functools import wraps
from datetime import date, timedelta
from urllib.parse import urlparse

import pandas as pd
from flask import (
    Flask, render_template, render_template_string,
    request, redirect, url_for, session, jsonify, Response
)
from werkzeug.security import generate_password_hash, check_password_hash

# =========================================================
# APP CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "ecommerce.db"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================================================
# DATABASE
# =========================================================

def get_db():
    """Create and return a SQLite connection."""
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    """Create the database tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS app_users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                category TEXT,
                unit_cost REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY,
                order_date TEXT NOT NULL,
                order_status TEXT NOT NULL DEFAULT 'Completed',
                region TEXT
            );

            CREATE TABLE IF NOT EXISTS order_items (
                item_id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                discount_amount REAL DEFAULT 0,
                return_amount REAL DEFAULT 0,
                FOREIGN KEY (order_id) REFERENCES orders(order_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );
        """)

        # Optional admin account. Set ADMIN_PASSWORD before launching
        # the application if you want an automatically provisioned admin.
        admin_password = os.environ.get("ADMIN_PASSWORD")
        admin_username = os.environ.get("ADMIN_USERNAME", "admin").strip()

        if admin_password:
            existing = conn.execute(
                "SELECT user_id FROM app_users WHERE username = ?",
                (admin_username,)
            ).fetchone()

            if not existing:
                conn.execute(
                    """
                    INSERT INTO app_users
                    (username, email, password_hash, role)
                    VALUES (?, ?, ?, 'admin')
                    """,
                    (
                        admin_username,
                        "admin@localhost",
                        generate_password_hash(admin_password)
                    )
                )

    logger.info("Database initialized at %s", DB_PATH)


def table_exists(table_name):
    with get_db() as conn:
        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        ).fetchone()
    return result is not None


def read_table(table_name):
    allowed = {"products", "orders", "order_items"}
    if table_name not in allowed:
        raise ValueError("Invalid table name")

    if not table_exists(table_name):
        return pd.DataFrame()

    with get_db() as conn:
        return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)


def get_data():
    """Read and validate the three analytics tables."""
    products = read_table("products")
    orders = read_table("orders")
    items = read_table("order_items")

    required = {
        "products": {"product_id", "product_name", "category"},
        "orders": {"order_id", "order_date", "order_status", "region"},
        "order_items": {
            "item_id", "order_id", "product_id", "quantity", "unit_price"
        }
    }

    tables = {
        "products": products,
        "orders": orders,
        "order_items": items
    }

    for name, columns in required.items():
        if tables[name].empty and len(tables[name].columns) == 0:
            raise RuntimeError(
                f"The '{name}' table is missing. "
                "Check your database and import your existing data."
            )

        missing = columns - set(tables[name].columns)
        if missing:
            raise RuntimeError(
                f"Table '{name}' is missing columns: {', '.join(sorted(missing))}"
            )

    return products, orders, items


# =========================================================
# AUTHENTICATION
# =========================================================

def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


@app.context_processor
def inject_template_helpers():
    # Make the CSRF token generator available in all Jinja templates.
    return {"csrf_token": csrf_token}


def valid_csrf():
    submitted = request.form.get("csrf_token", "")
    expected = session.get("_csrf_token", "")
    return bool(
        submitted and expected
        and secrets.compare_digest(submitted, expected)
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please sign in first."}), 401
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def safe_next_url(target):
    if not target:
        return url_for("dashboard")

    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return url_for("dashboard")

    return target


AUTH_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} | E-Commerce BI</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;
font-family:Inter,Arial,sans-serif;background:#f4f7ff;color:#17233f}
.card{width:min(430px,100%);padding:32px;background:#fff;border:1px solid #e3e9f5;
border-radius:20px;box-shadow:0 16px 45px #1f366414}
.brand{font-size:30px;margin-bottom:15px}
h1{font-size:25px;margin:0 0 8px}
p{color:#687795;line-height:1.6}
label{display:block;margin:16px 0 7px;font-size:13px;font-weight:700}
input{width:100%;padding:13px;border:1px solid #d8e0ef;border-radius:10px;font-size:15px}
input:focus{outline:2px solid #dbe4ff;border-color:#4263eb}
button{width:100%;padding:14px;margin-top:22px;border:0;border-radius:10px;
background:#4263eb;color:white;font-size:15px;font-weight:700;cursor:pointer}
.error{padding:12px;margin:12px 0;background:#fff0f0;color:#a42323;border-radius:8px}
a{color:#4263eb;text-decoration:none;font-weight:700}
.footer{margin-top:22px;font-size:13px;text-align:center}
</style>
</head>
<body>
<main class="card">
<div class="brand">📊</div>
<h1>{{ title }}</h1>
<p>{{ subtitle }}</p>
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
<form method="post">
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
{% for field in fields %}
<label for="{{ field.name }}">{{ field.label }}</label>
<input id="{{ field.name }}" name="{{ field.name }}"
type="{{ field.type }}" autocomplete="{{ field.autocomplete }}"
{% if field.maxlength %}maxlength="{{ field.maxlength }}"{% endif %}
required>
{% endfor %}
<button type="submit">{{ button_text }}</button>
</form>
<div class="footer">{{ footer|safe }}</div>
</main>
</body>
</html>
"""


def auth_page(title, subtitle, fields, button_text, error, footer):
    return render_template_string(
        AUTH_HTML,
        title=title,
        subtitle=subtitle,
        fields=fields,
        button_text=button_text,
        error=error,
        footer=footer,
        csrf_token=csrf_token()
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    error = None

    if request.method == "POST":
        if not valid_csrf():
            error = "Your session expired. Refresh and try again."
        else:
            identity = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            with get_db() as conn:
                user = conn.execute(
                    """
                    SELECT user_id, username, email, password_hash, role
                    FROM app_users
                    WHERE lower(username)=lower(?) OR lower(email)=lower(?)
                    LIMIT 1
                    """,
                    (identity, identity)
                ).fetchone()

            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["user_id"]
                session["username"] = user["username"]
                session["role"] = user["role"]
                session.permanent = True
                return redirect(safe_next_url(request.args.get("next")))

            error = "Invalid username/email or password."

    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    error = None

    if request.method == "POST":
        if not valid_csrf():
            error = "Your session expired. Refresh and try again."
        else:
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")

            if len(username) < 3 or len(username) > 80:
                error = "Username must contain 3 to 80 characters."
            elif not all(c.isalnum() or c in "_.-" for c in username):
                error = "Username can contain letters, numbers, dots, underscores and hyphens."
            elif "@" not in email or len(email) > 255:
                error = "Enter a valid email address."
            elif len(password) < 8:
                error = "Password must contain at least 8 characters."
            elif password != confirm:
                error = "Passwords do not match."
            else:
                try:
                    with get_db() as conn:
                        conn.execute(
                            """
                            INSERT INTO app_users
                            (username, email, password_hash, role)
                            VALUES (?, ?, ?, 'user')
                            """,
                            (username, email, generate_password_hash(password))
                        )
                    return redirect(url_for("login", registered="1"))
                except sqlite3.IntegrityError:
                    error = "That username or email is already registered."
                except Exception:
                    logger.exception("Registration failed")
                    error = "Registration failed. Check the server terminal."

    return render_template("register.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    if not valid_csrf():
        return "Invalid or expired session token. Refresh and try again.", 400
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# ANALYTICS
# =========================================================

def calculate_analytics(start_date=None, end_date=None, category=None, region=None, product_id=None):
    products, orders, items = get_data()

    orders["order_date"] = pd.to_datetime(orders["order_date"], errors="coerce")
    orders = orders.dropna(subset=["order_date"])

    excluded = {"cancelled", "canceled", "pending"}

    eligible = orders[
        ~orders["order_status"].astype(str).str.strip().str.lower().isin(excluded)
    ].copy()

    if start_date:
        eligible = eligible[eligible["order_date"].dt.date >= date.fromisoformat(start_date)]
    if end_date:
        eligible = eligible[eligible["order_date"].dt.date <= date.fromisoformat(end_date)]
    if region:
        eligible = eligible[eligible["region"].astype(str) == region]

    joined = items.merge(
        eligible[["order_id", "order_date", "region", "order_status"]],
        on="order_id",
        how="inner"
    )

    product_columns = ["product_id", "product_name", "category"]
    if "unit_cost" in products.columns:
        product_columns.append("unit_cost")

    joined = joined.merge(products[product_columns], on="product_id", how="left")

    if category:
        joined = joined[joined["category"].astype(str) == category]
    if product_id:
        joined = joined[joined["product_id"].astype(str) == str(product_id)]

    joined["quantity"] = pd.to_numeric(joined["quantity"], errors="coerce").fillna(0)
    joined["unit_price"] = pd.to_numeric(joined["unit_price"], errors="coerce").fillna(0)
    joined["gross_sales"] = joined["quantity"] * joined["unit_price"]

    for column in ("discount_amount", "return_amount"):
        if column not in joined.columns:
            joined[column] = 0
        joined[column] = pd.to_numeric(joined[column], errors="coerce").fillna(0).clip(lower=0)

    joined["net_sales"] = (
        joined["gross_sales"] - joined["discount_amount"] - joined["return_amount"]
    ).clip(lower=0)

    if "unit_cost" in joined.columns:
        joined["unit_cost"] = pd.to_numeric(joined["unit_cost"], errors="coerce").fillna(0).clip(lower=0)
        joined["estimated_cost"] = joined["quantity"] * joined["unit_cost"]
    else:
        joined["estimated_cost"] = 0.0

    joined["estimated_profit"] = joined["net_sales"] - joined["estimated_cost"]

    gross = float(joined["gross_sales"].sum())
    net = float(joined["net_sales"].sum())
    cost = float(joined["estimated_cost"].sum())
    profit = float(joined["estimated_profit"].sum())
    # Count only orders represented by the currently filtered product/category/region selection.
    order_count = int(joined["order_id"].nunique()) if not joined.empty else 0

    def records(frame):
        frame = frame.copy()
        for col in frame.select_dtypes(include="number").columns:
            frame[col] = frame[col].fillna(0)
        return frame.astype(object).where(pd.notna(frame), None).to_dict("records")

    monthly = (
        joined.assign(month=joined["order_date"].dt.strftime("%Y-%m"))
        .groupby("month", as_index=False)
        .agg(sales=("net_sales", "sum"), orders=("order_id", "nunique"))
        .sort_values("month")
    )

    categories = (
        joined.groupby("category", dropna=False, as_index=False)
        .agg(sales=("net_sales", "sum"), quantity=("quantity", "sum"))
        .sort_values("sales", ascending=False)
    )

    regions = (
        joined.groupby("region", dropna=False, as_index=False)
        .agg(sales=("net_sales", "sum"), orders=("order_id", "nunique"))
        .sort_values("sales", ascending=False)
    )

    top_products = (
        joined.groupby(["product_name", "category"], dropna=False, as_index=False)
        .agg(sales=("net_sales", "sum"), quantity=("quantity", "sum"))
        .sort_values("sales", ascending=False)
        .head(10)
    )

    status_data = orders.copy()
    if start_date:
        status_data = status_data[status_data["order_date"].dt.date >= date.fromisoformat(start_date)]
    if end_date:
        status_data = status_data[status_data["order_date"].dt.date <= date.fromisoformat(end_date)]

    # When product/category filters are active, show statuses only for orders matching them.
    if category or product_id:
        matching_order_ids = joined["order_id"].dropna().unique().tolist()
        status_data = status_data[status_data["order_id"].isin(matching_order_ids)]
    if region:
        status_data = status_data[status_data["region"].astype(str) == region]
    statuses = status_data.groupby("order_status", dropna=False).size().reset_index(name="orders")

    daily = (
        joined.assign(day=joined["order_date"].dt.strftime("%Y-%m-%d"))
        .groupby("day", as_index=False)
        .agg(sales=("net_sales", "sum"))
        .sort_values("day")
        .tail(31)
    )

    profit_categories = (
        joined.groupby("category", dropna=False, as_index=False)
        .agg(
            sales=("net_sales", "sum"),
            estimated_cost=("estimated_cost", "sum"),
            estimated_profit=("estimated_profit", "sum")
        )
        .sort_values("estimated_profit", ascending=False)
    )

    forecast = []
    if not monthly.empty:
        recent = monthly["sales"].tail(3).astype(float).tolist()
        baseline = sum(recent) / len(recent) if recent else 0
        last_month = pd.Period(monthly.iloc[-1]["month"], freq="M")
        for step in range(1, 4):
            forecast.append({
                "month": str(last_month + step),
                "forecast_sales": round(max(baseline, 0), 2)
            })

    return {
        "kpis": {
            "gross_sales": round(gross, 2),
            "net_sales": round(net, 2),
            "orders": order_count,
            "aov": round(net / order_count, 2) if order_count else 0,
            "estimated_cost": round(cost, 2),
            "estimated_profit": round(profit, 2),
            "profit_margin": round(profit / net * 100, 2) if net else 0,
            "growth": None
        },
        "monthly": records(monthly),
        "categories": records(categories),
        "regions": records(regions),
        "top_products": records(top_products),
        "statuses": records(statuses),
        "daily": records(daily),
        "profit_categories": records(profit_categories),
        "forecast": forecast
    }


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")
@login_required
def dashboard():
    today = date.today()
    start = request.args.get("start", (today - timedelta(days=180)).isoformat())
    end = request.args.get("end", today.isoformat())
    category = request.args.get("category", "").strip()
    region = request.args.get("region", "").strip()
    product_id = request.args.get("product_id", "").strip()

    try:
        parsed_start = date.fromisoformat(start)
        parsed_end = date.fromisoformat(end)

        if parsed_start > parsed_end:
            raise ValueError("Start date cannot be after end date.")

        products, orders, _ = get_data()

        category_options = sorted(
            products["category"].dropna().astype(str).unique().tolist()
        )
        region_options = sorted(
            orders["region"].dropna().astype(str).unique().tolist()
        )
        product_options = (
            products[["product_id", "product_name", "category"]]
            .dropna(subset=["product_id", "product_name"])
            .sort_values("product_name")
            .to_dict("records")
        )

        data = calculate_analytics(
            start_date=start,
            end_date=end,
            category=category or None,
            region=region or None,
            product_id=product_id or None
        )

        return render_template(
            "dashboard.html",
            start=start,
            end=end,
            selected_category=category,
            selected_region=region,
            selected_product_id=product_id,
            category_options=category_options,
            region_options=region_options,
            product_options=product_options,
            error=None,
            **data
        )

    except Exception as exc:
        logger.exception("Dashboard route failed")
        return (
            f"<h2>Dashboard error</h2><p>{str(exc)}</p>"
            "<p>Check the VS Code terminal for details.</p>"
            '<p><a href="/login">Return to login</a></p>',
            500
        )


# =========================================================
# CSV EXPORT
# =========================================================

@app.route("/export")
@login_required
def export_csv():
    try:
        start = request.args.get("start")
        end = request.args.get("end")
        category = request.args.get("category", "").strip()
        region = request.args.get("region", "").strip()
        product_id = request.args.get("product_id", "").strip()

        products, orders, items = get_data()
        orders["order_date"] = pd.to_datetime(orders["order_date"], errors="coerce")
        orders = orders.dropna(subset=["order_date"])

        excluded = {"cancelled", "canceled", "pending"}
        eligible = orders[
            ~orders["order_status"].astype(str).str.strip().str.lower().isin(excluded)
        ].copy()

        if start:
            eligible = eligible[eligible["order_date"].dt.date >= date.fromisoformat(start)]
        if end:
            eligible = eligible[eligible["order_date"].dt.date <= date.fromisoformat(end)]
        if region:
            eligible = eligible[eligible["region"].astype(str) == region]

        data = items.merge(
            eligible[["order_id", "order_date", "region", "order_status"]],
            on="order_id", how="inner"
        ).merge(
            products[["product_id", "product_name", "category"]],
            on="product_id", how="left"
        )

        if category:
            data = data[data["category"].astype(str) == category]
        if product_id:
            data = data[data["product_id"].astype(str) == product_id]

        data["quantity"] = pd.to_numeric(data["quantity"], errors="coerce").fillna(0)
        data["unit_price"] = pd.to_numeric(data["unit_price"], errors="coerce").fillna(0)
        data["gross_sales"] = data["quantity"] * data["unit_price"]

        for column in ("discount_amount", "return_amount"):
            if column not in data.columns:
                data[column] = 0
            data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0).clip(lower=0)

        data["net_sales"] = (
            data["gross_sales"] - data["discount_amount"] - data["return_amount"]
        ).clip(lower=0)

        csv_data = data.to_csv(index=False)
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=ecommerce_analytics.csv"}
        )

    except Exception:
        logger.exception("CSV export failed")
        return "CSV export failed. Check the terminal for details.", 500


# =========================================================
# HEALTH CHECK & STARTUP
# =========================================================

@app.route("/health")
def health():
    return jsonify({"status": "ok", "database": str(DB_PATH)})


with app.app_context():
    init_db()

if __name__ == "__main__":
    logger.info("Starting E-Commerce BI Dashboard")
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1"
    )