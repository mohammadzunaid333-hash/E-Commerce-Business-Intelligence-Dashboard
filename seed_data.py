"""
E-Commerce Business Intelligence Dashboard
------------------------------------------
Sample data generator for:
    products
    orders
    order_items

Requirements:
    database.py must expose:
        engine
        init_db()

The database tables must contain the columns used below.
"""

from datetime import date, timedelta
import random

from sqlalchemy import text
from database import engine, init_db


# Reproducible demo data
random.seed(42)


# ---------------------------------------------------------
# PRODUCT CATALOG
# Format: (product_name, category, unit_price)
# ---------------------------------------------------------

PRODUCTS = [
    ("Laptop Pro 14", "Electronics", 85000.00),
    ("Wireless Mouse", "Electronics", 1200.00),
    ("Mechanical Keyboard", "Electronics", 4500.00),
    ("Smartphone X", "Electronics", 42000.00),
    ("USB-C Hub", "Electronics", 2500.00),
    ("Running Shoes", "Fashion", 3200.00),
    ("Cotton T-Shirt", "Fashion", 800.00),
    ("Denim Jeans", "Fashion", 2200.00),
    ("Travel Backpack", "Fashion", 1800.00),
    ("Classic Watch", "Fashion", 5500.00),
    ("Coffee Maker", "Home & Kitchen", 4200.00),
    ("Mixer Grinder", "Home & Kitchen", 3500.00),
    ("Water Bottle", "Home & Kitchen", 650.00),
    ("Bedsheet Set", "Home & Kitchen", 1600.00),
    ("Desk Lamp", "Home & Kitchen", 1400.00),
    ("Python Programming", "Books", 750.00),
    ("Data Analytics Guide", "Books", 950.00),
    ("Business Intelligence", "Books", 1100.00),
    ("Yoga Mat", "Sports", 1200.00),
    ("Dumbbell Set", "Sports", 2800.00),
]

REGIONS = [
    "North",
    "South",
    "East",
    "West",
    "Central",
]

ORDER_STATUSES = [
    "completed",
    "shipped",
    "delivered",
    "cancelled",
    "pending",
]

STATUS_WEIGHTS = [45, 15, 25, 10, 5]


# ---------------------------------------------------------
# DATABASE SEEDING
# ---------------------------------------------------------

def seed_database():
    """
    Initialize the database and insert demonstration records.

    WARNING:
    This function clears existing products, orders and
    order_items before inserting fresh demo data.
    Do not run it against a database containing important data.
    """

    print("\n" + "=" * 60)
    print(" E-COMMERCE BUSINESS INTELLIGENCE DASHBOARD")
    print(" Database Sample Data Generator")
    print("=" * 60)

    # Create database tables if they do not exist.
    init_db()

    today = date.today()
    start_date = today - timedelta(days=540)

    item_id_counter = 1

    with engine.begin() as connection:

        # -------------------------------------------------
        # 1. CLEAR OLD DEMONSTRATION DATA
        # Delete child records before parent records.
        # -------------------------------------------------

        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM products"))

        print("\nOld demo records cleared.")

        # -------------------------------------------------
        # 2. INSERT PRODUCTS
        # -------------------------------------------------

        product_insert = text("""
            INSERT INTO products (
                product_id,
                product_name,
                category
            )
            VALUES (
                :product_id,
                :product_name,
                :category
            )
        """)

        for product_id, product in enumerate(PRODUCTS, start=1):

            product_name, category, unit_price = product

            connection.execute(
                product_insert,
                {
                    "product_id": product_id,
                    "product_name": product_name,
                    "category": category,
                },
            )

        print(f"Inserted {len(PRODUCTS)} products.")

        # -------------------------------------------------
        # 3. PREPARE ORDER INSERT
        # -------------------------------------------------

        order_insert = text("""
            INSERT INTO orders (
                order_id,
                order_date,
                order_status,
                region
            )
            VALUES (
                :order_id,
                :order_date,
                :order_status,
                :region
            )
        """)

        # -------------------------------------------------
        # 4. PREPARE ORDER ITEM INSERT
        # -------------------------------------------------

        item_insert = text("""
            INSERT INTO order_items (
                item_id,
                order_id,
                product_id,
                quantity,
                unit_price,
                discount_amount,
                return_amount
            )
            VALUES (
                :item_id,
                :order_id,
                :product_id,
                :quantity,
                :unit_price,
                :discount_amount,
                :return_amount
            )
        """)

        # -------------------------------------------------
        # 5. GENERATE ORDERS
        # -------------------------------------------------

        total_orders = 300
        total_items = 0

        for order_id in range(1, total_orders + 1):

            # Select an order date within the previous 18 months.
            random_days = random.randint(0, 540)

            order_date = start_date + timedelta(
                days=random_days
            )

            order_status = random.choices(
                ORDER_STATUSES,
                weights=STATUS_WEIGHTS,
                k=1,
            )[0]

            region = random.choice(REGIONS)

            connection.execute(
                order_insert,
                {
                    "order_id": order_id,
                    "order_date": order_date.isoformat(),
                    "order_status": order_status,
                    "region": region,
                },
            )

            # -------------------------------------------------
            # 6. GENERATE ITEMS FOR EACH ORDER
            # -------------------------------------------------

            number_of_items = random.randint(1, 4)

            for _ in range(number_of_items):

                product_id = random.randint(
                    1,
                    len(PRODUCTS),
                )

                product_name, category, unit_price = (
                    PRODUCTS[product_id - 1]
                )

                quantity = random.randint(1, 4)

                gross_line_amount = unit_price * quantity

                discount_rate = random.choice(
                    [0.00, 0.00, 0.05, 0.10, 0.15]
                )

                discount_amount = round(
                    gross_line_amount * discount_rate,
                    2,
                )

                return_amount = 0.00

                # Generate occasional returns for eligible orders.
                if (
                    order_status in (
                        "completed",
                        "shipped",
                        "delivered",
                    )
                    and random.random() < 0.06
                ):

                    returned_quantity = random.randint(
                        1,
                        quantity,
                    )

                    return_amount = round(
                        unit_price * returned_quantity,
                        2,
                    )

                    # A return cannot exceed the discounted line value.
                    return_amount = min(
                        return_amount,
                        max(
                            0.00,
                            gross_line_amount - discount_amount,
                        ),
                    )

                connection.execute(
                    item_insert,
                    {
                        "item_id": item_id_counter,
                        "order_id": order_id,
                        "product_id": product_id,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "discount_amount": discount_amount,
                        "return_amount": return_amount,
                    },
                )

                item_id_counter += 1
                total_items += 1

        # The transaction commits automatically if everything succeeds.

    # -----------------------------------------------------
    # 7. PRINT SUMMARY
    # -----------------------------------------------------

    print("\n" + "-" * 60)
    print("DATABASE SEEDING COMPLETED SUCCESSFULLY")
    print("-" * 60)
    print(f"Products inserted : {len(PRODUCTS)}")
    print(f"Orders inserted   : {total_orders}")
    print(f"Order items       : {total_items}")
    print(f"Date range        : {start_date} to {today}")
    print(f"Regions           : {len(REGIONS)}")
    print(f"Categories        : 5")
    print("-" * 60)


# ---------------------------------------------------------
# SCRIPT ENTRY POINT
# ---------------------------------------------------------

if __name__ == "__main__":
    try:
        seed_database()

    except Exception as error:
        print("\nDATABASE SEEDING FAILED")
        print(f"Error type   : {type(error).__name__}")
        print(f"Error details: {error}")
        raise