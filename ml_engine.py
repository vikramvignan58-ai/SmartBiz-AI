"""AI / machine-learning engine.

Four models run on the business's own data:
  1. Sales forecasting      - linear regression on trend + day-of-week
  2. Smart reordering       - demand estimate -> days of stock left -> reorder qty
  3. Customer segmentation  - K-Means clustering on RFM (recency, frequency, monetary)
  4. Anomaly detection      - Isolation Forest on order value, units and lines
"""
import math

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

LEAD_TIME_DAYS = 7   # days a supplier takes to deliver
COVER_DAYS = 14      # days of stock we want after a delivery arrives


def _reference_date(conn):
    last = conn.execute("SELECT MAX(date(sale_date)) FROM sales").fetchone()[0]
    return pd.Timestamp(last) if last else pd.Timestamp.today().normalize()


# --------------------------------------------------------------------------- #
# 1. Sales forecasting
# --------------------------------------------------------------------------- #
def daily_sales(conn):
    df = pd.read_sql_query(
        "SELECT date(sale_date) AS day, SUM(total) AS revenue, COUNT(*) AS orders "
        "FROM sales GROUP BY date(sale_date) ORDER BY day",
        conn,
        parse_dates=["day"],
    )
    if df.empty:
        return df
    full = pd.date_range(df["day"].min(), df["day"].max(), freq="D")
    return (
        df.set_index("day").reindex(full, fill_value=0).rename_axis("day").reset_index()
    )


def _features(dates, start):
    t = np.asarray((dates - start).days, dtype=float).reshape(-1, 1)
    dow = np.eye(7)[dates.dayofweek][:, 1:]          # Monday is the baseline
    return np.hstack([t, dow])


def forecast_sales(conn, horizon=14, history=60):
    df = daily_sales(conn)
    if len(df) < 21:
        return {"ready": False, "message": "At least 21 days of sales are needed to forecast."}

    days = pd.DatetimeIndex(df["day"])
    start = days[0]
    X, y = _features(days, start), df["revenue"].to_numpy(dtype=float)

    # Hold out the most recent two weeks to measure accuracy honestly.
    hold = min(14, len(df) // 4)
    test_model = LinearRegression().fit(X[:-hold], y[:-hold])
    test_pred = np.clip(test_model.predict(X[-hold:]), 0, None)
    error = np.abs(test_pred - y[-hold:]).sum() / max(y[-hold:].sum(), 1)
    accuracy = max(0.0, 1 - error) * 100

    model = LinearRegression().fit(X, y)
    future = pd.date_range(days[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    pred = np.clip(model.predict(_features(future, start)), 0, None)

    hist = df.tail(history)
    last7, next7 = float(y[-7:].sum()), float(pred[:7].sum())
    return {
        "ready": True,
        "model": "Linear regression (trend + day-of-week)",
        "history_labels": [d.strftime("%d %b") for d in hist["day"]],
        "history_values": [round(float(v), 2) for v in hist["revenue"]],
        "forecast_labels": [d.strftime("%d %b") for d in future],
        "forecast_values": [round(float(v), 2) for v in pred],
        "last7": last7,
        "next7": next7,
        "change_pct": (next7 - last7) / last7 * 100 if last7 else 0.0,
        "accuracy": round(accuracy, 1),
        "trend_per_day": float(model.coef_[0]),
    }


# --------------------------------------------------------------------------- #
# 2. Smart reordering
# --------------------------------------------------------------------------- #
STATUS_ORDER = {"Out of stock": 0, "Critical": 1, "Reorder soon": 2, "Healthy": 3}


def reorder_suggestions(conn):
    products = pd.read_sql_query(
        "SELECT id, sku, name, category, stock, reorder_level, cost, supplier FROM products",
        conn,
    )
    if products.empty:
        return []

    ref = _reference_date(conn)
    since30 = (ref - pd.Timedelta(days=29)).strftime("%Y-%m-%d")
    since7 = (ref - pd.Timedelta(days=6)).strftime("%Y-%m-%d")
    sold = pd.read_sql_query(
        """SELECT si.product_id,
                  SUM(CASE WHEN date(s.sale_date) >= ? THEN si.quantity ELSE 0 END) AS q7,
                  SUM(si.quantity) AS q30
           FROM sale_items si JOIN sales s ON s.id = si.sale_id
           WHERE date(s.sale_date) >= ?
           GROUP BY si.product_id""",
        conn,
        params=(since7, since30),
    )
    df = products.merge(sold, left_on="id", right_on="product_id", how="left")
    df[["q7", "q30"]] = df[["q7", "q30"]].fillna(0)

    out = []
    for r in df.itertuples(index=False):
        # Weighted demand: recent week counts more than the month.
        demand = 0.6 * (r.q7 / 7) + 0.4 * (r.q30 / 30)
        days_left = r.stock / demand if demand > 0 else None
        target = demand * (LEAD_TIME_DAYS + COVER_DAYS)

        if r.stock <= 0:
            status = "Out of stock"
        elif days_left is not None and days_left <= LEAD_TIME_DAYS:
            status = "Critical"
        elif r.stock <= r.reorder_level or (
            days_left is not None and days_left <= LEAD_TIME_DAYS + COVER_DAYS / 2
        ):
            status = "Reorder soon"
        else:
            status = "Healthy"

        qty = 0
        if status != "Healthy":
            qty = max(math.ceil(target - r.stock), r.reorder_level * 2 - r.stock, 1)

        out.append({
            "id": int(r.id), "sku": r.sku, "name": r.name, "category": r.category,
            "supplier": r.supplier, "stock": int(r.stock), "reorder_level": int(r.reorder_level),
            "daily_demand": round(demand, 2),
            "days_left": round(days_left, 1) if days_left is not None else None,
            "suggested_qty": int(qty), "est_cost": round(qty * r.cost, 2), "status": status,
        })

    out.sort(key=lambda d: (STATUS_ORDER[d["status"]],
                            d["days_left"] if d["days_left"] is not None else 1e9))
    return out


# --------------------------------------------------------------------------- #
# 3. Customer segmentation (RFM + K-Means)
# --------------------------------------------------------------------------- #
SEGMENTS = ["Champions", "Loyal", "Occasional", "At Risk"]
SEGMENT_ACTIONS = {
    "Champions": "Reward with loyalty points and early access to offers.",
    "Loyal": "Upsell related products and ask for referrals.",
    "Occasional": "Send personalised offers to increase visit frequency.",
    "At Risk": "Win back with a reminder message or a time-limited discount.",
}


def customer_segments(conn):
    df = pd.read_sql_query(
        """SELECT c.id, c.name, c.phone, MAX(date(s.sale_date)) AS last_purchase,
                  COUNT(s.id) AS frequency, SUM(s.total) AS monetary
           FROM customers c JOIN sales s ON s.customer_id = c.id
           GROUP BY c.id""",
        conn,
    )
    if len(df) < 8:
        return {"ready": False, "by_customer": {}, "summary": [], "customers": []}

    ref = _reference_date(conn)
    df["recency"] = (ref - pd.to_datetime(df["last_purchase"])).dt.days
    feats = np.column_stack([df["recency"], np.log1p(df["frequency"]), np.log1p(df["monetary"])])
    Z = StandardScaler().fit_transform(feats)

    km = KMeans(n_clusters=4, n_init=10, random_state=42).fit(Z)
    df["cluster"] = km.labels_
    c = km.cluster_centers_
    value_score = -c[:, 0] + c[:, 1] + c[:, 2]          # recent + frequent + high spend
    ranked = np.argsort(-value_score)
    label = {int(cluster): SEGMENTS[i] for i, cluster in enumerate(ranked)}
    df["segment"] = df["cluster"].map(label)

    summary = []
    for name in SEGMENTS:
        part = df[df["segment"] == name]
        if part.empty:
            continue
        summary.append({
            "segment": name, "customers": int(len(part)),
            "avg_recency": round(float(part["recency"].mean()), 1),
            "avg_orders": round(float(part["frequency"].mean()), 1),
            "avg_spend": round(float(part["monetary"].mean()), 2),
            "revenue": round(float(part["monetary"].sum()), 2),
            "action": SEGMENT_ACTIONS[name],
        })

    customers = df.sort_values("monetary", ascending=False).to_dict("records")
    return {
        "ready": True,
        "by_customer": {int(i): s for i, s in zip(df["id"], df["segment"])},
        "summary": summary,
        "customers": customers,
    }


# --------------------------------------------------------------------------- #
# 4. Anomaly detection (Isolation Forest)
# --------------------------------------------------------------------------- #
def detect_anomalies(conn, contamination=0.01, limit=12):
    df = pd.read_sql_query(
        """SELECT s.id, s.invoice_no, s.sale_date, s.total,
                  COALESCE(c.name, 'Walk-in') AS customer,
                  SUM(si.quantity) AS units, COUNT(si.id) AS lines
           FROM sales s
           JOIN sale_items si ON si.sale_id = s.id
           LEFT JOIN customers c ON c.id = s.customer_id
           GROUP BY s.id""",
        conn,
    )
    if len(df) < 30:
        return []

    X = np.column_stack([np.log1p(df["total"]), df["units"], df["lines"]])
    iso = IsolationForest(contamination=contamination, random_state=42).fit(X)
    df["score"] = -iso.score_samples(X)
    flagged = df[iso.predict(X) == -1].sort_values("score", ascending=False).head(limit)

    med_total, med_units = float(df["total"].median()), float(df["units"].median())
    out = []
    for r in flagged.itertuples(index=False):
        value_ratio = r.total / med_total if med_total else 0
        unit_ratio = r.units / med_units if med_units else 0
        if value_ratio >= 2:
            reason = f"Order value is {value_ratio:.1f}x a typical order"
        elif unit_ratio >= 2:
            reason = f"{int(r.units)} units vs a typical {med_units:.0f}"
        elif value_ratio <= 0.25:
            reason = "Unusually small order value"
        else:
            reason = "Unusual mix of value, units and items"
        out.append({
            "id": int(r.id), "invoice_no": r.invoice_no, "sale_date": r.sale_date,
            "customer": r.customer, "total": float(r.total), "units": int(r.units),
            "lines": int(r.lines), "reason": reason, "score": round(float(r.score), 3),
        })
    return out


# --------------------------------------------------------------------------- #
# Headline insights for the dashboard
# --------------------------------------------------------------------------- #
def headline_insights(conn, forecast=None, reorder=None, segments=None, anomalies=None):
    forecast = forecast or forecast_sales(conn, horizon=7)
    reorder = reorder if reorder is not None else reorder_suggestions(conn)
    segments = segments or customer_segments(conn)
    anomalies = anomalies if anomalies is not None else detect_anomalies(conn)
    items = []

    if forecast.get("ready"):
        ch = forecast["change_pct"]
        items.append({
            "icon": "graph-up-arrow" if ch >= 0 else "graph-down-arrow",
            "tone": "success" if ch >= 0 else "warning",
            "text": f"Revenue for the next 7 days is forecast {'up' if ch >= 0 else 'down'} "
                    f"{abs(ch):.1f}% versus the last 7 days.",
        })

    urgent = [r for r in reorder if r["status"] in ("Out of stock", "Critical")]
    soon = [r for r in reorder if r["status"] == "Reorder soon"]
    if urgent:
        names = ", ".join(r["name"] for r in urgent[:3])
        items.append({"icon": "exclamation-triangle", "tone": "danger",
                      "text": f"{len(urgent)} product(s) need restocking now: {names}."})
    if soon:
        items.append({"icon": "box-seam", "tone": "warning",
                      "text": f"{len(soon)} more product(s) should be reordered this week."})

    if segments.get("ready"):
        risk = next((s for s in segments["summary"] if s["segment"] == "At Risk"), None)
        if risk:
            items.append({"icon": "people", "tone": "info",
                          "text": f"{risk['customers']} customers are at risk of churning; "
                                  f"they haven't bought in about {risk['avg_recency']:.0f} days."})

    if anomalies:
        items.append({"icon": "shield-exclamation", "tone": "danger",
                      "text": f"{len(anomalies)} unusual transaction(s) flagged for review."})
    return items
