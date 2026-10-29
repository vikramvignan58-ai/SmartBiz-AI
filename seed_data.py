"""Create the database and fill it with realistic demo data.

Run directly to reset the demo:  python seed_data.py
"""
import math
import os
import random
import sqlite3
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

from database import SCHEMA

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "business.db")

# sku, name, category, price, cost, reorder_level, supplier, popularity weight
PRODUCTS = [
    ("GRC-001", "Basmati Rice 5 kg", "Groceries", 650, 520, 15, "Sri Lakshmi Traders", 9),
    ("GRC-002", "Toor Dal 1 kg", "Groceries", 165, 130, 25, "Sri Lakshmi Traders", 10),
    ("GRC-003", "Sunflower Oil 1 L", "Groceries", 155, 125, 25, "Deccan Oils", 11),
    ("GRC-004", "Wheat Atta 10 kg", "Groceries", 480, 395, 12, "Sri Lakshmi Traders", 7),
    ("GRC-005", "Sugar 1 kg", "Groceries", 48, 40, 30, "Sri Lakshmi Traders", 12),
    ("GRC-006", "Tea Powder 500 g", "Groceries", 265, 205, 15, "Assam Tea Co.", 8),
    ("GRC-007", "Instant Coffee 200 g", "Groceries", 340, 270, 10, "Assam Tea Co.", 4),
    ("GRC-008", "Biscuits Family Pack", "Groceries", 60, 45, 40, "Bharat Foods", 14),
    ("PRC-001", "Bath Soap (Pack of 4)", "Personal Care", 185, 140, 20, "CleanCo Distributors", 8),
    ("PRC-002", "Shampoo 340 ml", "Personal Care", 225, 170, 15, "CleanCo Distributors", 6),
    ("PRC-003", "Toothpaste 150 g", "Personal Care", 115, 85, 25, "CleanCo Distributors", 9),
    ("PRC-004", "Hand Wash Refill", "Personal Care", 99, 72, 15, "CleanCo Distributors", 5),
    ("HSH-001", "Detergent Powder 2 kg", "Household", 385, 300, 12, "CleanCo Distributors", 7),
    ("HSH-002", "Dishwash Gel 750 ml", "Household", 145, 110, 15, "CleanCo Distributors", 6),
    ("HSH-003", "Steel Water Bottle 1 L", "Household", 420, 290, 8, "HomeWare India", 3),
    ("HSH-004", "Pressure Cooker 5 L", "Household", 1850, 1400, 4, "HomeWare India", 1.2),
    ("STN-001", "Notebook (Pack of 6)", "Stationery", 240, 170, 15, "Vidya Stationers", 4),
    ("STN-002", "Ball Pens (Pack of 10)", "Stationery", 100, 65, 20, "Vidya Stationers", 5),
    ("ELE-001", "LED Bulb 9 W", "Electronics", 125, 80, 20, "Bright Electricals", 5),
    ("ELE-002", "Extension Board 4-way", "Electronics", 460, 330, 6, "Bright Electricals", 2),
    ("ELE-003", "Wired Earphones", "Electronics", 699, 420, 8, "Bright Electricals", 2),
    ("ELE-004", "Fast Phone Charger", "Electronics", 549, 360, 8, "Bright Electricals", 2.5),
    ("ELE-005", "Power Bank 10000 mAh", "Electronics", 1299, 920, 5, "Bright Electricals", 1.5),
]

FIRST = ["Aarav", "Vivaan", "Aditya", "Sai", "Arjun", "Rohan", "Karthik", "Rahul", "Vikram",
         "Ananya", "Diya", "Priya", "Sneha", "Kavya", "Lakshmi", "Meera", "Divya", "Pooja",
         "Harsha", "Naveen", "Suresh", "Ramesh", "Swathi", "Bhavana", "Teja", "Srinivas",
         "Manoj", "Keerthi", "Nikhil", "Sravani"]
LAST = ["Reddy", "Rao", "Sharma", "Kumar", "Naidu", "Varma", "Gupta", "Patel", "Iyer",
        "Chowdary", "Goud", "Singh", "Nair", "Menon", "Shetty"]
CITIES = ["Hyderabad", "Hyderabad", "Hyderabad", "Secunderabad", "LB Nagar", "Kukatpally",
          "Dilsukhnagar", "Gachibowli"]

DOW_FACTOR = [0.9, 0.85, 0.9, 0.95, 1.1, 1.4, 1.3]  # Mon..Sun


def _poisson(rng, lam):
    # Knuth's algorithm - fine for the small rates used here.
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def seed(path=DEFAULT_DB, days=180, seed_value=7):
    rng = random.Random(seed_value)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO users (username, full_name, password_hash, role) VALUES (?, ?, ?, ?)",
        [("admin", "Store Owner", generate_password_hash("admin123"), "admin"),
         ("staff", "Counter Staff", generate_password_hash("staff123"), "staff")])

    conn.executemany(
        "INSERT INTO products (sku, name, category, price, cost, stock, reorder_level, supplier) "
        "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
        [(p[0], p[1], p[2], p[3], p[4], p[5], p[6]) for p in PRODUCTS])
    product_ids = [r[0] for r in conn.execute("SELECT id FROM products ORDER BY id")]
    prices = {pid: PRODUCTS[i][3] for i, pid in enumerate(product_ids)}
    weights = [p[7] for p in PRODUCTS]

    today = date.today()
    start = today - timedelta(days=days - 1)

    # Customers, each with a personal "loyalty" weight so some shop far more than others.
    customers = []
    used = set()
    while len(customers) < 80:
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if name in used:
            continue
        used.add(name)
        phone = f"9{rng.randint(100000000, 999999999)}"
        email = f"{name.lower().replace(' ', '.')}@example.com"
        joined = start - timedelta(days=rng.randint(0, 200))
        customers.append((name, phone, email, rng.choice(CITIES), joined.isoformat()))
    conn.executemany(
        "INSERT INTO customers (name, phone, email, city, created_at) VALUES (?, ?, ?, ?, ?)",
        customers)
    customer_ids = [r[0] for r in conn.execute("SELECT id FROM customers ORDER BY id")]
    loyalty = [rng.choice([0.3, 0.6, 1, 1, 2, 3, 5]) for _ in customer_ids]
    # A group of customers who used to shop but stopped ~2 months ago (churn to detect).
    churned = set(rng.sample(customer_ids, 12))
    churn_cutoff = today - timedelta(days=rng.randint(55, 75))

    sales, items = [], []
    sale_id = item_id = 0
    sold_qty = {pid: 0 for pid in product_ids}
    recent_qty = {pid: 0 for pid in product_ids}

    def add_order(day, customer_id, lines):
        nonlocal sale_id, item_id
        sale_id += 1
        ts = datetime.combine(day, datetime.min.time()) + timedelta(
            hours=rng.randint(9, 21), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
        total = 0.0
        for pid, qty in lines:
            item_id += 1
            line_total = prices[pid] * qty
            total += line_total
            items.append((item_id, sale_id, pid, qty, prices[pid], line_total))
            sold_qty[pid] += qty
            if (today - day).days < 30:
                recent_qty[pid] += qty
        method = rng.choices(["UPI", "Cash", "Card"], [50, 32, 18])[0]
        sales.append((sale_id, f"INV-{day:%Y%m%d}-{sale_id:05d}", customer_id,
                      ts.strftime("%Y-%m-%d %H:%M:%S"), round(total, 2), method, 1))

    for d in range(days):
        day = start + timedelta(days=d)
        trend = 1 + 0.004 * d
        n_orders = _poisson(rng, 13 * trend * DOW_FACTOR[day.weekday()])
        for _ in range(n_orders):
            customer_id = None
            if rng.random() < 0.72:
                customer_id = rng.choices(customer_ids, loyalty)[0]
                if customer_id in churned and day > churn_cutoff:
                    customer_id = None
            n_lines = rng.choices([1, 2, 3, 4], [38, 32, 20, 10])[0]
            chosen = set()
            while len(chosen) < n_lines:
                chosen.add(rng.choices(product_ids, weights)[0])
            lines = [(pid, rng.choice([1, 1, 1, 2, 2, 3])) for pid in chosen]
            add_order(day, customer_id, lines)

    # A handful of genuinely unusual orders for the anomaly detector to find.
    expensive = product_ids[-5:] + [product_ids[15]]
    for offset in rng.sample(range(5, days - 2), 5):
        day = start + timedelta(days=offset)
        lines = [(rng.choice(expensive), rng.randint(18, 35)), (rng.choice(expensive), rng.randint(10, 20))]
        lines = list({pid: q for pid, q in lines}.items())
        add_order(day, rng.choice(customer_ids), lines)

    conn.executemany("INSERT INTO sales (id, invoice_no, customer_id, sale_date, total, "
                     "payment_method, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)", sales)
    conn.executemany("INSERT INTO sale_items (id, sale_id, product_id, quantity, unit_price, "
                     "line_total) VALUES (?, ?, ?, ?, ?, ?)", items)

    # Current stock: mostly healthy, a few running low, one sold out - so reorder AI has work.
    low = set(rng.sample(product_ids, 5))
    out = rng.choice([p for p in product_ids if p not in low])
    purchases = []
    for i, pid in enumerate(product_ids):
        per_day = max(recent_qty[pid] / 30, 0.2)
        if pid == out:
            stock = 0
        elif pid in low:
            stock = max(1, int(per_day * rng.uniform(1.5, 6)))
        else:
            stock = int(per_day * rng.uniform(25, 60)) + PRODUCTS[i][5]
        conn.execute("UPDATE products SET stock = ? WHERE id = ?", (stock, pid))
        # Monthly restock history
        for m in range(0, days, 30):
            qty = max(int(sold_qty[pid] / (days / 30) * rng.uniform(0.9, 1.2)), 5)
            purchases.append((pid, qty, PRODUCTS[i][4], PRODUCTS[i][6],
                              (start + timedelta(days=m)).isoformat()))
    conn.executemany("INSERT INTO purchases (product_id, quantity, unit_cost, supplier, "
                     "purchase_date) VALUES (?, ?, ?, ?, ?)", purchases)

    conn.commit()
    conn.close()
    return {"sales": len(sales), "items": len(items), "customers": len(customer_ids),
            "products": len(product_ids)}


if __name__ == "__main__":
    stats = seed()
    print(f"Demo database created at {DEFAULT_DB}")
    print(f"  {stats['products']} products, {stats['customers']} customers, "
          f"{stats['sales']} sales, {stats['items']} line items")
    print("  Login: admin / admin123   (or staff / staff123)")
