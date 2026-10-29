"""SmartBiz AI - AI-Powered Smart Business Management System.

Run:  python app.py   then open http://127.0.0.1:5000  (login: admin / admin123)
"""
import os
from collections import OrderedDict
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, redirect, render_template, request, send_file,
                   session, url_for)
from werkzeug.security import check_password_hash

import ml_engine as ml
import reports as rp
from database import close_db, get_db, row, rows, scalar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-secret-key"),
    DATABASE=os.environ.get("DATABASE", os.path.join(BASE_DIR, "instance", "business.db")),
    BUSINESS_NAME=os.environ.get("BUSINESS_NAME", "SmartBiz AI"),
)
app.teardown_appcontext(close_db)

# First run: create the database with demo data so the app works out of the box.
if not os.path.exists(app.config["DATABASE"]):
    from seed_data import seed
    seed(app.config["DATABASE"])

CATEGORIES = ["Groceries", "Personal Care", "Household", "Stationery", "Electronics", "Other"]
PAYMENT_METHODS = ["UPI", "Cash", "Card"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def inr(value, decimals=0):
    """Format a number in Indian style: 12,34,567."""
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return value
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail, groups = whole[:-3], whole[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{sign}₹{whole}" + (f".{frac}" if frac else "")


app.jinja_env.filters["inr"] = inr


@app.template_filter("dt")
def format_dt(value, fmt="%d %b %Y, %I:%M %p"):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)).strftime(fmt)
    except ValueError:
        return value


@app.context_processor
def inject_globals():
    return {"business_name": app.config["BUSINESS_NAME"], "now": datetime.now()}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Only the owner/admin can do that.", "danger")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def parse_range(default_days=30):
    today = date.today()
    try:
        end = date.fromisoformat(request.args.get("end", ""))
    except ValueError:
        end = today
    try:
        start = date.fromisoformat(request.args.get("start", ""))
    except ValueError:
        start = end - timedelta(days=default_days - 1)
    if start > end:
        start, end = end, start
    return start.isoformat(), end.isoformat()


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = row("SELECT * FROM users WHERE username = ?",
                   (request.form.get("username", "").strip(),))
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], username=user["username"],
                           full_name=user["full_name"], role=user["role"])
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//")
                            else url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@app.route("/")
@login_required
def dashboard():
    db = get_db()
    today = date.today()
    t, m = today.isoformat(), today.replace(day=1).isoformat()
    d30 = (today - timedelta(days=29)).isoformat()

    kpi = {
        "today_revenue": scalar("SELECT COALESCE(SUM(total),0) FROM sales WHERE date(sale_date)=?", (t,)),
        "today_orders": scalar("SELECT COUNT(*) FROM sales WHERE date(sale_date)=?", (t,)),
        "month_revenue": scalar("SELECT COALESCE(SUM(total),0) FROM sales WHERE date(sale_date)>=?", (m,)),
        "month_orders": scalar("SELECT COUNT(*) FROM sales WHERE date(sale_date)>=?", (m,)),
        "customers": scalar("SELECT COUNT(*) FROM customers"),
        "low_stock": scalar("SELECT COUNT(*) FROM products WHERE stock <= reorder_level"),
        "stock_value": scalar("SELECT COALESCE(SUM(stock*cost),0) FROM products"),
    }
    top_products = rows(
        """SELECT p.id, p.name, SUM(si.quantity) AS qty, SUM(si.line_total) AS revenue
           FROM sale_items si JOIN sales s ON s.id=si.sale_id JOIN products p ON p.id=si.product_id
           WHERE date(s.sale_date) >= ? GROUP BY p.id ORDER BY revenue DESC LIMIT 5""", (d30,))
    by_category = rows(
        """SELECT p.category, SUM(si.line_total) AS revenue
           FROM sale_items si JOIN sales s ON s.id=si.sale_id JOIN products p ON p.id=si.product_id
           WHERE date(s.sale_date) >= ? GROUP BY p.category ORDER BY revenue DESC""", (d30,))
    recent = rows(
        """SELECT s.*, COALESCE(c.name,'Walk-in') AS customer FROM sales s
           LEFT JOIN customers c ON c.id=s.customer_id ORDER BY s.sale_date DESC LIMIT 6""")

    forecast = ml.forecast_sales(db, horizon=7, history=30)
    insights = ml.headline_insights(db, forecast=forecast)
    return render_template(
        "dashboard.html", kpi=kpi, top_products=top_products, recent=recent,
        forecast=forecast, insights=insights,
        category_chart={"labels": [r["category"] for r in by_category],
                        "values": [round(r["revenue"], 2) for r in by_category]})


# --------------------------------------------------------------------------- #
# Sales
# --------------------------------------------------------------------------- #
@app.route("/sales")
@login_required
def sales():
    start, end = parse_range()
    q = request.args.get("q", "").strip()
    sql = """SELECT s.*, COALESCE(c.name,'Walk-in') AS customer,
                    (SELECT SUM(quantity) FROM sale_items WHERE sale_id=s.id) AS units
             FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
             WHERE date(s.sale_date) BETWEEN ? AND ?"""
    args = [start, end]
    if q:
        sql += " AND (s.invoice_no LIKE ? OR c.name LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    data = rows(sql + " ORDER BY s.sale_date DESC LIMIT 500", args)
    total = sum(r["total"] for r in data)
    return render_template("sales.html", sales=data, start=start, end=end, q=q, total=total)


@app.route("/sales/new", methods=["GET", "POST"])
@login_required
def sales_new():
    db = get_db()
    products = rows("SELECT * FROM products ORDER BY name")
    customers = rows("SELECT id, name, phone FROM customers ORDER BY name")

    if request.method == "POST":
        errors, wanted = [], OrderedDict()
        for pid, qty in zip(request.form.getlist("product_id"), request.form.getlist("quantity")):
            if not pid:
                continue
            try:
                qty = int(qty)
            except ValueError:
                errors.append("Quantities must be whole numbers.")
                continue
            if qty <= 0:
                errors.append("Quantities must be greater than zero.")
                continue
            wanted[int(pid)] = wanted.get(int(pid), 0) + qty

        lines = []
        for pid, qty in wanted.items():
            p = row("SELECT * FROM products WHERE id=?", (pid,))
            if p is None:
                errors.append("A selected product no longer exists.")
            elif qty > p["stock"]:
                errors.append(f"Only {p['stock']} unit(s) of {p['name']} in stock.")
            else:
                lines.append((p, qty))
        if not wanted and not errors:
            errors.append("Add at least one product to the bill.")

        customer_id = request.form.get("customer_id") or None
        if customer_id and not row("SELECT id FROM customers WHERE id=?", (customer_id,)):
            errors.append("Selected customer not found.")
        method = request.form.get("payment_method", "Cash")
        if method not in PAYMENT_METHODS:
            method = "Cash"

        if errors:
            for e in dict.fromkeys(errors):
                flash(e, "danger")
            return render_template("sale_form.html", products=products, customers=customers,
                                   methods=PAYMENT_METHODS, form=request.form), 400

        # Totals are always computed on the server - never trusted from the browser.
        total = round(sum(p["price"] * q for p, q in lines), 2)
        now = datetime.now()
        cur = db.execute(
            "INSERT INTO sales (invoice_no, customer_id, sale_date, total, payment_method, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"TMP-{now.timestamp()}", customer_id, now.strftime("%Y-%m-%d %H:%M:%S"),
             total, method, session["user_id"]))
        sale_id = cur.lastrowid
        invoice = f"INV-{now:%Y%m%d}-{sale_id:05d}"
        db.execute("UPDATE sales SET invoice_no=? WHERE id=?", (invoice, sale_id))
        for p, q in lines:
            db.execute("INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, line_total) "
                       "VALUES (?, ?, ?, ?, ?)", (sale_id, p["id"], q, p["price"], p["price"] * q))
            db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (q, p["id"]))
        db.commit()
        flash(f"Sale {invoice} saved - {inr(total, 2)}. Stock updated.", "success")
        return redirect(url_for("sales_detail", sale_id=sale_id))

    return render_template("sale_form.html", products=products, customers=customers,
                           methods=PAYMENT_METHODS, form={})


@app.route("/sales/<int:sale_id>")
@login_required
def sales_detail(sale_id):
    sale = row("""SELECT s.*, c.name AS customer, c.phone, c.city, u.full_name AS cashier
                  FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                  LEFT JOIN users u ON u.id=s.created_by WHERE s.id=?""", (sale_id,))
    if sale is None:
        abort(404)
    items = rows("""SELECT si.*, p.name, p.sku FROM sale_items si
                    JOIN products p ON p.id=si.product_id WHERE si.sale_id=?""", (sale_id,))
    return render_template("sale_detail.html", sale=sale, items=items)


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
@app.route("/inventory")
@login_required
def inventory():
    category = request.args.get("category", "")
    q = request.args.get("q", "").strip()
    reorder = {r["id"]: r for r in ml.reorder_suggestions(get_db())}
    sql, args = "SELECT * FROM products WHERE 1=1", []
    if category:
        sql += " AND category=?"
        args.append(category)
    if q:
        sql += " AND (name LIKE ? OR sku LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    products = rows(sql + " ORDER BY category, name", args)
    cats = [r[0] for r in rows("SELECT DISTINCT category FROM products ORDER BY category")]
    return render_template("inventory.html", products=products, reorder=reorder,
                           categories=cats, category=category, q=q)


def _product_from_form(form):
    errors = []
    data = {k: form.get(k, "").strip() for k in
            ("sku", "name", "category", "price", "cost", "stock", "reorder_level", "supplier")}
    if not data["sku"] or not data["name"]:
        errors.append("SKU and product name are required.")
    for key, cast in (("price", float), ("cost", float), ("stock", int), ("reorder_level", int)):
        try:
            data[key] = cast(data[key] or 0)
            if data[key] < 0:
                raise ValueError
        except ValueError:
            errors.append(f"{key.replace('_', ' ').title()} must be a non-negative number.")
    if not errors and data["cost"] > data["price"]:
        flash("Note: cost is higher than selling price.", "warning")
    return data, errors


@app.route("/inventory/new", methods=["GET", "POST"])
@login_required
@admin_required
def inventory_new():
    if request.method == "POST":
        data, errors = _product_from_form(request.form)
        if not errors and row("SELECT id FROM products WHERE sku=?", (data["sku"],)):
            errors.append("That SKU already exists.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("product_form.html", product=request.form,
                                   categories=CATEGORIES, is_new=True), 400
        db = get_db()
        cur = db.execute(
            "INSERT INTO products (sku, name, category, price, cost, stock, reorder_level, supplier) "
            "VALUES (:sku, :name, :category, :price, :cost, :stock, :reorder_level, :supplier)", data)
        db.commit()
        flash(f"Product {data['name']} added.", "success")
        return redirect(url_for("inventory_detail", product_id=cur.lastrowid))
    return render_template("product_form.html", product={}, categories=CATEGORIES, is_new=True)


@app.route("/inventory/<int:product_id>", methods=["GET", "POST"])
@login_required
def inventory_detail(product_id):
    db = get_db()
    product = row("SELECT * FROM products WHERE id=?", (product_id,))
    if product is None:
        abort(404)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "restock":
            try:
                qty = int(request.form.get("quantity", 0))
                unit_cost = float(request.form.get("unit_cost") or product["cost"])
                if qty <= 0 or unit_cost < 0:
                    raise ValueError
            except ValueError:
                flash("Enter a positive quantity and a valid cost.", "danger")
                return redirect(url_for("inventory_detail", product_id=product_id))
            db.execute("INSERT INTO purchases (product_id, quantity, unit_cost, supplier, purchase_date) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (product_id, qty, unit_cost, request.form.get("supplier") or product["supplier"],
                        date.today().isoformat()))
            db.execute("UPDATE products SET stock = stock + ?, cost = ? WHERE id = ?",
                       (qty, unit_cost, product_id))
            db.commit()
            flash(f"Added {qty} unit(s) to stock.", "success")
        elif action == "update":
            if session.get("role") != "admin":
                flash("Only the owner/admin can edit products.", "danger")
                return redirect(url_for("inventory_detail", product_id=product_id))
            data, errors = _product_from_form(request.form)
            clash = row("SELECT id FROM products WHERE sku=? AND id<>?", (data.get("sku"), product_id))
            if clash:
                errors.append("That SKU belongs to another product.")
            if errors:
                for e in errors:
                    flash(e, "danger")
            else:
                data["id"] = product_id
                db.execute("""UPDATE products SET sku=:sku, name=:name, category=:category, price=:price,
                              cost=:cost, stock=:stock, reorder_level=:reorder_level, supplier=:supplier
                              WHERE id=:id""", data)
                db.commit()
                flash("Product updated.", "success")
        return redirect(url_for("inventory_detail", product_id=product_id))

    ai = next((r for r in ml.reorder_suggestions(db) if r["id"] == product_id), None)
    history = rows("SELECT * FROM purchases WHERE product_id=? ORDER BY purchase_date DESC LIMIT 10",
                   (product_id,))
    weekly = rows("""SELECT strftime('%Y-%W', s.sale_date) AS wk, MIN(date(s.sale_date)) AS day,
                            SUM(si.quantity) AS qty
                     FROM sale_items si JOIN sales s ON s.id=si.sale_id
                     WHERE si.product_id=? GROUP BY wk ORDER BY wk DESC LIMIT 12""", (product_id,))
    weekly = list(reversed(weekly))
    chart = {"labels": [format_dt(w["day"], "%d %b") for w in weekly], "values": [w["qty"] for w in weekly]}
    return render_template("product_detail.html", product=dict(product), ai=ai, history=history,
                           chart=chart, categories=CATEGORIES)


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #
@app.route("/customers")
@login_required
def customers():
    q = request.args.get("q", "").strip()
    segment = request.args.get("segment", "")
    seg = ml.customer_segments(get_db())
    sql = """SELECT c.*, COUNT(s.id) AS orders, COALESCE(SUM(s.total),0) AS spent,
                    MAX(s.sale_date) AS last_purchase
             FROM customers c LEFT JOIN sales s ON s.customer_id=c.id"""
    args = []
    if q:
        sql += " WHERE c.name LIKE ? OR c.phone LIKE ? OR c.city LIKE ?"
        args = [f"%{q}%"] * 3
    data = rows(sql + " GROUP BY c.id ORDER BY spent DESC", args)
    if segment:
        data = [c for c in data if seg["by_customer"].get(c["id"]) == segment]
    return render_template("customers.html", customers=data, segments=seg, q=q,
                           segment=segment, segment_names=ml.SEGMENTS)


@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def customers_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if not name:
            flash("Customer name is required.", "danger")
            return render_template("customer_form.html", form=request.form), 400
        if phone and (not phone.isdigit() or len(phone) != 10):
            flash("Phone number should be 10 digits.", "danger")
            return render_template("customer_form.html", form=request.form), 400
        db = get_db()
        cur = db.execute("INSERT INTO customers (name, phone, email, city, created_at) VALUES (?, ?, ?, ?, ?)",
                         (name, phone, request.form.get("email", "").strip(),
                          request.form.get("city", "").strip(), date.today().isoformat()))
        db.commit()
        flash(f"Customer {name} added.", "success")
        return redirect(url_for("customers_detail", customer_id=cur.lastrowid))
    return render_template("customer_form.html", form={})


@app.route("/customers/<int:customer_id>")
@login_required
def customers_detail(customer_id):
    customer = row("SELECT * FROM customers WHERE id=?", (customer_id,))
    if customer is None:
        abort(404)
    history = rows("""SELECT s.*, (SELECT SUM(quantity) FROM sale_items WHERE sale_id=s.id) AS units
                      FROM sales s WHERE s.customer_id=? ORDER BY s.sale_date DESC""", (customer_id,))
    favourites = rows("""SELECT p.name, SUM(si.quantity) AS qty FROM sale_items si
                         JOIN sales s ON s.id=si.sale_id JOIN products p ON p.id=si.product_id
                         WHERE s.customer_id=? GROUP BY p.id ORDER BY qty DESC LIMIT 5""", (customer_id,))
    seg = ml.customer_segments(get_db())
    segment = seg["by_customer"].get(customer_id)
    stats = {"orders": len(history), "spent": sum(h["total"] for h in history),
             "avg": (sum(h["total"] for h in history) / len(history)) if history else 0,
             "last": history[0]["sale_date"] if history else None}
    return render_template("customer_detail.html", customer=customer, history=history[:25],
                           favourites=favourites, segment=segment, stats=stats,
                           action=ml.SEGMENT_ACTIONS.get(segment))


# --------------------------------------------------------------------------- #
# AI insights
# --------------------------------------------------------------------------- #
@app.route("/insights")
@login_required
def insights():
    db = get_db()
    forecast = ml.forecast_sales(db, horizon=14, history=60)
    reorder = ml.reorder_suggestions(db)
    segments = ml.customer_segments(db)
    anomalies = ml.detect_anomalies(db)
    return render_template("insights.html", forecast=forecast,
                           reorder=[r for r in reorder if r["status"] != "Healthy"],
                           healthy=sum(1 for r in reorder if r["status"] == "Healthy"),
                           segments=segments, anomalies=anomalies,
                           lead=ml.LEAD_TIME_DAYS, cover=ml.COVER_DAYS)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
@app.route("/reports")
@login_required
def reports():
    kind = request.args.get("kind", "sales")
    if kind not in rp.REPORT_TYPES:
        kind = "sales"
    start, end = parse_range()
    report = rp.build_report(get_db(), kind, start, end)

    fmt = request.args.get("format")
    filename = f"{kind}_{start}_to_{end}"
    if fmt == "csv":
        return send_file(rp.to_csv(report), mimetype="text/csv",
                         as_attachment=True, download_name=f"{filename}.csv")
    if fmt == "xlsx":
        return send_file(rp.to_xlsx(report), as_attachment=True, download_name=f"{filename}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt == "pdf":
        return send_file(rp.to_pdf(report, app.config["BUSINESS_NAME"]), mimetype="application/pdf",
                         as_attachment=True, download_name=f"{filename}.pdf")
    return render_template("reports.html", report=report, types=rp.REPORT_TYPES, kind=kind)


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="That page or record doesn't exist."), 404


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)
