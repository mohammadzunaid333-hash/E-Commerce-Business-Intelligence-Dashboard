from pathlib import Path
import os

from sqlalchemy import (
    create_engine,
    text,
    event,
    inspect,
)
from sqlalchemy.engine import Engine


# ============================================================
# E-COMMERCE BUSINESS INTELLIGENCE DASHBOARD
# Database Configuration and Schema Management
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / "ecommerce.db"

# SQLite is the default for easy local development.
# A MySQL DATABASE_URL can be supplied through an environment
# variable when a MySQL server is configured.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DATABASE_PATH.as_posix()}",
)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine_options = {
    "pool_pre_ping": True,
    "future": True,
}

if IS_SQLITE:
    engine_options["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30,
    }

engine = create_engine(
    DATABASE_URL,
    **engine_options,
)


# ------------------------------------------------------------
# Enable SQLite foreign-key enforcement
# ------------------------------------------------------------

if IS_SQLITE:

    @event.listens_for(Engine, "connect")
    def enable_sqlite_foreign_keys(
        dbapi_connection,
        connection_record,
    ):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ------------------------------------------------------------
# Database schema
# ------------------------------------------------------------

SCHEMA_STATEMENTS = [

    """
    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY,
        product_name VARCHAR(150) NOT NULL,
        category VARCHAR(100) NOT NULL,
        unit_cost FLOAT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY,
        order_date DATE NOT NULL,
        order_status VARCHAR(30) NOT NULL,
        region VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS order_items (
        item_id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity >= 0),
        unit_price FLOAT NOT NULL CHECK (unit_price >= 0),
        discount_amount FLOAT NOT NULL DEFAULT 0
            CHECK (discount_amount >= 0),
        return_amount FLOAT NOT NULL DEFAULT 0
            CHECK (return_amount >= 0),

        FOREIGN KEY (order_id)
            REFERENCES orders(order_id)
            ON DELETE CASCADE,

        FOREIGN KEY (product_id)
            REFERENCES products(product_id)
            ON DELETE RESTRICT
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_orders_date
    ON orders(order_date)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_orders_status
    ON orders(order_status)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_orders_region
    ON orders(region)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_products_category
    ON products(category)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_order_items_order
    ON order_items(order_id)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_order_items_product
    ON order_items(product_id)
    """,
]


# ------------------------------------------------------------
# Initialize all tables and indexes
# ------------------------------------------------------------

def init_db():
    """
    Create the database tables and indexes if they do not exist.

    This function is safe to call repeatedly. It does not delete
    existing data.
    """

    with engine.begin() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(text(statement))

    return True


# ------------------------------------------------------------
# Connection health check
# ------------------------------------------------------------

def check_database():
    """
    Return basic database health information.
    """

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        inspector = inspect(engine)

        return {
            "connected": True,
            "database_type": (
                "SQLite" if IS_SQLITE else "MySQL"
            ),
            "tables": inspector.get_table_names(),
            "database_path": (
                str(DATABASE_PATH) if IS_SQLITE else None
            ),
        }

    except Exception as exc:
        return {
            "connected": False,
            "database_type": (
                "SQLite" if IS_SQLITE else "MySQL"
            ),
            "error": str(exc),
        }


# ------------------------------------------------------------
# Database table counts
# ------------------------------------------------------------

def get_table_counts():
    """
    Return row counts for the main business tables.
    """

    init_db()

    table_names = [
        "products",
        "orders",
        "order_items",
    ]

    counts = {}

    with engine.connect() as connection:
        for table_name in table_names:
            result = connection.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            )
            counts[table_name] = result.scalar_one()

    return counts


# ------------------------------------------------------------
# Development entry point
# ------------------------------------------------------------

if __name__ == "__main__":

    init_db()

    print("\n" + "=" * 55)
    print(" E-COMMERCE BUSINESS INTELLIGENCE DATABASE")
    print("=" * 55)

    health = check_database()

    print(f"Connected : {health['connected']}")
    print(f"Database  : {health['database_type']}")

    if health["connected"]:
        print("Tables    :")

        for table_name in health["tables"]:
            print(f"  - {table_name}")

        print("\nCurrent table counts:")

        for table_name, count in get_table_counts().items():
            print(f"  {table_name}: {count}")

    else:
        print(f"Database error: {health['error']}")