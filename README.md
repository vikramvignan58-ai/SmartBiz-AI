# SmartBiz AI — AI-Powered Smart Business Management System

A web-based system that digitizes everyday business operations — **sales, inventory, customers and reports** — and adds a **machine-learning layer** that forecasts sales, suggests reorders, segments customers and flags unusual transactions.

Built with **Python (Flask)**, **scikit-learn**, **SQLite** and a **Bootstrap + Chart.js** web interface.

---

## Quick start

```bash
# 1. (optional) create a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

# 2. install dependencies
pip install -r requirements.txt

# 3. run
python app.py
```

Open **http://127.0.0.1:5000** and sign in:

| Role  | Username | Password  | Can do |
|-------|----------|-----------|--------|
| Owner | `admin`  | `admin123`| Everything, including adding/editing products |
| Staff | `staff`  | `staff123`| Billing, restocking, customers, reports |

On first run the app creates `instance/business.db` with ~6 months of realistic demo data (23 products, 80 customers, ~3,300 sales). To reset the demo data at any time (do this right before presenting so "today" figures are fresh):

```bash
python seed_data.py
```

---

## Features

| Module | What it does |
|---|---|
| **Dashboard** | Today's and month's revenue, AI 7-day forecast, low-stock count, revenue chart with forecast line, sales by category, top products, recent sales, AI insight cards |
| **Sales tracking** | Billing screen with live total, stock check, automatic stock deduction, printable invoice, searchable sales register |
| **Inventory** | Product catalogue, stock levels, AI demand estimate and days-of-stock left, restock (goods received) with purchase history, weekly sales chart per product |
| **Customers** | Customer profiles, purchase history, favourite products, AI segment with a suggested action |
| **AI Insights** | All four ML models in one place, with explanations |
| **Reports** | Sales register, product-wise sales & profit, inventory status, customer summary — export to **CSV, Excel, PDF** |

### The AI / ML layer (`ml_engine.py`)

| # | Model | Algorithm | Output |
|---|---|---|---|
| 1 | Sales forecasting | Linear regression on trend + day-of-week features | 14-day revenue forecast; accuracy measured on 2 held-out weeks |
| 2 | Smart reordering | Weighted demand (60% last 7 days, 40% last 30) → days of stock left vs. supplier lead time | Status (Out of stock / Critical / Reorder soon / Healthy), order quantity, budget |
| 3 | Customer segmentation | K-Means clustering on RFM (Recency, Frequency, Monetary) | Champions, Loyal, Occasional, At Risk + recommended action |
| 4 | Anomaly detection | Isolation Forest on order value, units and line count | Flagged invoices with a plain-English reason |

### Error minimization
- Totals are always calculated on the server, never trusted from the browser.
- A sale cannot exceed available stock; stock updates automatically on every sale and restock.
- Input validation on every form (non-negative prices, 10-digit phone, unique SKU).
- Database constraints (`CHECK stock >= 0`, foreign keys).

---

## Architecture

```
 Users (owner, staff)
        │  browser
        ▼
 Web interface  ── HTML / Bootstrap / Chart.js  (templates/, static/)
        │  HTTP
        ▼
 Flask application  ── routes, login, validation, business logic   (app.py)
        │                         │
        ▼                         ▼
 SQLite database             ML engine — pandas + scikit-learn     (ml_engine.py)
 (database.py)               Reports — CSV / openpyxl / ReportLab   (reports.py)
```

## Project structure

```
smartbiz-ai/
├── app.py            Flask app: routes for every module
├── database.py       Schema (users, products, customers, sales, sale_items, purchases) + helpers
├── ml_engine.py      Forecasting, reorder, segmentation, anomaly detection
├── reports.py        Report builder and CSV / Excel / PDF export
├── seed_data.py      Generates realistic demo data
├── requirements.txt
├── templates/        Jinja2 pages (dashboard, sales, inventory, customers, insights, reports …)
└── static/           style.css, app.js (charts, billing form)
```

## Database schema

- **users** (id, username, full_name, password_hash, role)
- **products** (id, sku, name, category, price, cost, stock, reorder_level, supplier)
- **customers** (id, name, phone, email, city, created_at)
- **sales** (id, invoice_no, customer_id → customers, sale_date, total, payment_method, created_by → users)
- **sale_items** (id, sale_id → sales, product_id → products, quantity, unit_price, line_total)
- **purchases** (id, product_id → products, quantity, unit_cost, supplier, purchase_date)

## Suggested demo flow (5 minutes)

1. **Login** as admin → **Dashboard**: point out KPIs, the forecast line and AI insights.
2. **New sale**: add two items, show the live total, save → invoice opens; stock drops.
3. **Inventory**: show AI "days left" and suggested order; open a critical product and restock it.
4. **Customers**: filter by **At Risk** segment, open one customer.
5. **AI Insights**: walk through the four models.
6. **Reports**: generate product-wise profit, download as Excel and PDF.

## Future scope
Mobile app, GST invoicing, barcode/QR scanning, WhatsApp/SMS offers to customer segments, multi-branch support, cloud deployment (PostgreSQL), chat-style "ask your data" assistant.

## Configuration
Environment variables (optional): `SECRET_KEY`, `DATABASE` (path to the SQLite file), `BUSINESS_NAME`, `FLASK_DEBUG=1`.
