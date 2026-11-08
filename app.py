"""
Vertex Travel LLC — Agency Manager
A Streamlit app for running a travel agency: bookings, CRM, suppliers,
expenses, workflow automation, invoicing, P&L and financial position.
"""
import io
from html import escape
import random
import sqlite3
import datetime as dt
from contextlib import closing

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Vertex Travel LLC", page_icon="✈️", layout="wide")

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
DB_PATH = "vertex_travel.db"

SERVICE_TYPES = [
    "Flight", "Hotel", "Holiday Package", "Umrah / Hajj Package", "Visa Service",
    "Travel Insurance", "Car Rental", "Cruise", "Tour / Excursion", "Rail", "Other",
]
STATUSES = ["Inquiry", "Quoted", "Confirmed", "Ticketed", "Completed", "Cancelled"]
# Statuses that count as a sale (revenue). For cancellations, set Sell = fee kept,
# Cost = supplier penalty, so only the retained margin is recognised.
SALE_STATUSES = ["Confirmed", "Ticketed", "Completed", "Cancelled"]
EXPENSE_CATEGORIES = [
    "Rent", "Salaries & Wages", "Marketing & Ads", "Software & GDS",
    "Merchant / Bank Fees", "Insurance", "Professional Fees (Legal/CPA)",
    "Utilities & Phone", "Licenses & Bonds", "Travel & Fam Trips",
    "Office Supplies", "Other",
]
CAPITAL_TYPES = ["Owner Contribution", "Owner Draw", "Loan Received", "Loan Repayment"]
SUPPLIER_CATEGORIES = ["Airline / Consolidator", "Hotel / Bedbank", "Tour Operator / DMC",
                       "Cruise Line", "Car Rental", "Insurance", "Visa Agent", "Other"]
LEAD_SOURCES = ["Referral", "Website", "Social Media", "Walk-in", "Phone", "Repeat Client", "Other"]
PAY_METHODS = ["Bank Transfer", "Credit Card", "Debit Card", "Cash", "Check", "Zelle / ACH"]
TABLES = ["clients", "suppliers", "bookings", "expenses", "capital", "tasks", "settings"]

DEFAULT_SETTINGS = {
    "company_name": "Vertex Travel LLC",
    "company_address": "United States",
    "company_email": "info@vertextravel.com",
    "company_phone": "",
    "currency": "$",
    "opening_cash": "0",
    "tax_rate": "25",
    "revenue_basis": "Booking date",
    "auto_tasks": "1",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, phone TEXT,
  country TEXT, source TEXT, notes TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS suppliers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT, contact TEXT,
  email TEXT, phone TEXT, terms_days INTEGER DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, client_id INTEGER, supplier_id INTEGER,
  service_type TEXT, destination TEXT, booking_date TEXT, travel_date TEXT, return_date TEXT,
  pax INTEGER DEFAULT 1, sell_price REAL DEFAULT 0, cost_price REAL DEFAULT 0,
  client_paid REAL DEFAULT 0, supplier_paid REAL DEFAULT 0, status TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT, description TEXT,
  amount REAL, method TEXT);
CREATE TABLE IF NOT EXISTS capital(
  id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, type TEXT, amount REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, due_date TEXT, related_ref TEXT,
  priority TEXT, status TEXT DEFAULT 'Open', created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

# ----------------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------------
def connect():
    return sqlite3.connect(DB_PATH)


def run(sql, params=()):
    with closing(connect()) as c, c:
        return c.execute(sql, params).lastrowid


def q(sql, params=()):
    with closing(connect()) as c:
        return pd.read_sql_query(sql, c, params=params)


def init_db():
    with closing(connect()) as c, c:
        c.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))


def get_setting(key):
    df = q("SELECT value FROM settings WHERE key=?", (key,))
    return df["value"].iloc[0] if len(df) else DEFAULT_SETTINGS.get(key, "")


def set_setting(key, value):
    run("INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def fnum(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def money(x):
    cur = get_setting("currency")
    x = fnum(x)
    sign = "-" if x < 0 else ""
    return f"{sign}{cur}{abs(x):,.2f}"


def to_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    try:
        ts = pd.to_datetime(v)
        return None if pd.isna(ts) else ts.date()
    except Exception:
        return None


def iso(d):
    return d.isoformat() if d else None


# ----------------------------------------------------------------------------
# Data loaders
# ----------------------------------------------------------------------------
def clients_df():
    return q("SELECT * FROM clients ORDER BY name")


def suppliers_df():
    return q("SELECT * FROM suppliers ORDER BY name")


def bookings_df():
    df = q("""SELECT b.*, c.name AS client, s.name AS supplier
              FROM bookings b
              LEFT JOIN clients c ON c.id = b.client_id
              LEFT JOIN suppliers s ON s.id = b.supplier_id
              ORDER BY b.booking_date DESC, b.id DESC""")
    for col in ["booking_date", "travel_date", "return_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["sell_price", "cost_price", "client_paid", "supplier_paid"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["profit"] = df["sell_price"] - df["cost_price"]
    df["margin_pct"] = (df["profit"] / df["sell_price"].where(df["sell_price"] != 0)) * 100
    df["client_balance"] = df["sell_price"] - df["client_paid"]
    df["supplier_balance"] = df["cost_price"] - df["supplier_paid"]
    df["is_sale"] = df["status"].isin(SALE_STATUSES)
    return df


def expenses_df():
    df = q("SELECT * FROM expenses ORDER BY date DESC, id DESC")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df


def capital_df():
    df = q("SELECT * FROM capital ORDER BY date DESC, id DESC")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df


def tasks_df():
    df = q("SELECT * FROM tasks ORDER BY status DESC, due_date ASC")
    df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce")
    return df


def basis_col():
    return "travel_date" if get_setting("revenue_basis") == "Travel date" else "booking_date"


# ----------------------------------------------------------------------------
# Business logic
# ----------------------------------------------------------------------------
def next_ref():
    year = dt.date.today().year
    df = q("SELECT ref FROM bookings WHERE ref LIKE ?", (f"VTX-{year}-%",))
    n = 0
    for r in df["ref"]:
        try:
            n = max(n, int(str(r).split("-")[-1]))
        except ValueError:
            pass
    return f"VTX-{year}-{n + 1:04d}"


def create_auto_tasks(ref, travel_date, return_date, client_balance, supplier_balance):
    """Workflow automation: generate the standard follow-up tasks for a confirmed sale."""
    if get_setting("auto_tasks") != "1":
        return 0
    today = dt.date.today()

    def due(d):
        return max(d, today).isoformat()

    items = []
    if travel_date:
        if client_balance > 0:
            items.append((f"Collect client balance — {ref}", due(travel_date - dt.timedelta(days=30)), "High"))
        if supplier_balance > 0:
            items.append((f"Pay supplier — {ref}", due(travel_date - dt.timedelta(days=21)), "High"))
        items.append((f"Send e-tickets / vouchers & itinerary — {ref}", due(travel_date - dt.timedelta(days=7)), "Medium"))
        items.append((f"Pre-departure check-in call — {ref}", due(travel_date - dt.timedelta(days=2)), "Medium"))
    if return_date:
        items.append((f"Post-trip feedback & review request — {ref}", due(return_date + dt.timedelta(days=2)), "Low"))
    for title, d, pr in items:
        run("INSERT INTO tasks(title, due_date, related_ref, priority, status, created_at) "
            "VALUES(?,?,?,?, 'Open', ?)", (title, d, ref, pr, today.isoformat()))
    return len(items)


def pnl(start, end):
    b, e = bookings_df(), expenses_df()
    col = basis_col()
    s = b[b["is_sale"] & (b[col] >= start) & (b[col] <= end)]
    ex = e[(e["date"] >= start) & (e["date"] <= end)]
    revenue = float(s["sell_price"].sum())
    cogs = float(s["cost_price"].sum())
    gross = revenue - cogs
    opex = float(ex["amount"].sum())
    net = gross - opex
    rate = fnum(get_setting("tax_rate")) / 100
    tax = max(net, 0) * rate
    return {
        "revenue": revenue, "cogs": cogs, "gross": gross,
        "gross_margin": (gross / revenue * 100) if revenue else 0.0,
        "opex": opex, "net": net, "tax": tax, "net_after_tax": net - tax,
        "net_margin": (net / revenue * 100) if revenue else 0.0,
        "bookings": int(len(s)), "pax": int(pd.to_numeric(s["pax"], errors="coerce").fillna(0).sum()),
    }, s, ex


def financial_position():
    """Current balance sheet. Balances by construction: Assets - Liabilities = Equity."""
    b, e, k = bookings_df(), expenses_df(), capital_df()
    opening = fnum(get_setting("opening_cash"))

    def ksum(t):
        return float(k.loc[k["type"] == t, "amount"].sum())

    contrib, draws = ksum("Owner Contribution"), ksum("Owner Draw")
    loan_in, loan_out = ksum("Loan Received"), ksum("Loan Repayment")

    cash = (opening + contrib + loan_in - draws - loan_out
            + float(b["client_paid"].sum()) - float(b["supplier_paid"].sum())
            - float(e["amount"].sum()))

    sale, pre = b[b["is_sale"]], b[~b["is_sale"]]
    ar = float(sale["client_balance"].clip(lower=0).sum())
    client_credits = float((-sale["client_balance"]).clip(lower=0).sum()) + float(pre["client_paid"].sum())
    ap = float(sale["supplier_balance"].clip(lower=0).sum())
    supplier_prepay = float((-sale["supplier_balance"]).clip(lower=0).sum()) + float(pre["supplier_paid"].sum())
    loans = loan_in - loan_out

    assets = cash + ar + supplier_prepay
    liabilities = ap + client_credits + loans
    equity = assets - liabilities
    owner_capital = opening + contrib - draws
    retained = float(sale["profit"].sum()) - float(e["amount"].sum())
    return {
        "cash": cash, "ar": ar, "supplier_prepay": supplier_prepay, "assets": assets,
        "ap": ap, "client_deposits": client_credits, "loans": loans, "liabilities": liabilities,
        "equity": equity, "owner_capital": owner_capital, "retained": retained,
        "check": equity - (owner_capital + retained),
        "contrib": contrib, "draws": draws, "loan_in": loan_in, "loan_out": loan_out,
        "client_receipts": float(b["client_paid"].sum()),
        "supplier_payments": float(b["supplier_paid"].sum()),
        "expenses_paid": float(e["amount"].sum()), "opening": opening,
    }


def monthly_summary(b, e):
    col = basis_col()
    s = b[b["is_sale"]].dropna(subset=[col]).copy()
    ex = e.dropna(subset=["date"]).copy()
    if s.empty and ex.empty:
        return pd.DataFrame(columns=["month", "revenue", "cogs", "opex", "gross", "net"])
    s["month"] = s[col].dt.to_period("M").dt.to_timestamp()
    ex["month"] = ex["date"].dt.to_period("M").dt.to_timestamp()
    m = s.groupby("month").agg(revenue=("sell_price", "sum"), cogs=("cost_price", "sum"))
    em = ex.groupby("month")["amount"].sum().rename("opex")
    df = m.join(em, how="outer").fillna(0.0)
    df.index.name = "month"
    df["gross"] = df["revenue"] - df["cogs"]
    df["net"] = df["gross"] - df["opex"]
    return df.reset_index().sort_values("month")


def period_picker(key, default=3):
    today = dt.date.today()
    opts = ["This month", "Last month", "This quarter", "Year to date",
            "Last 12 months", "All time", "Custom"]
    opt = st.selectbox("Reporting period", opts, index=default, key=key)

    def month_end(d):
        return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)

    if opt == "This month":
        s = today.replace(day=1); e = month_end(today)
    elif opt == "Last month":
        e = today.replace(day=1) - dt.timedelta(days=1); s = e.replace(day=1)
    elif opt == "This quarter":
        qm = 3 * ((today.month - 1) // 3) + 1
        s = dt.date(today.year, qm, 1); e = month_end(dt.date(today.year, qm + 2, 1))
    elif opt == "Year to date":
        s = dt.date(today.year, 1, 1); e = dt.date(today.year, 12, 31)
    elif opt == "Last 12 months":
        s = today - dt.timedelta(days=365); e = today
    elif opt == "All time":
        s = dt.date(1900, 1, 1); e = dt.date(2999, 12, 31)
    else:
        c1, c2 = st.columns(2)
        s = c1.date_input("From", today.replace(day=1), key=f"{key}_from")
        e = c2.date_input("To", today, key=f"{key}_to")
    return pd.Timestamp(s), pd.Timestamp(e), opt


# ----------------------------------------------------------------------------
# Demo data
# ----------------------------------------------------------------------------
def load_demo_data():
    rnd = random.Random(42)
    today = dt.date.today()
    clients = [
        ("Ahmed Khan", "ahmed.k@example.com", "+1 713 555 0101", "USA", "Referral"),
        ("Sarah Johnson", "sarah.j@example.com", "+1 212 555 0144", "USA", "Website"),
        ("Fatima Malik", "fatima.m@example.com", "+1 832 555 0177", "USA", "Social Media"),
        ("David Miller", "d.miller@example.com", "+1 415 555 0123", "USA", "Repeat Client"),
        ("Ayesha Siddiqui", "ayesha.s@example.com", "+1 469 555 0190", "USA", "Referral"),
        ("Global Tech Inc. (Corporate)", "travel@globaltech.example", "+1 650 555 0110", "USA", "Phone"),
        ("Omar Farooq", "omar.f@example.com", "+1 646 555 0165", "USA", "Walk-in"),
        ("Emily Chen", "emily.c@example.com", "+1 312 555 0188", "USA", "Website"),
    ]
    for c in clients:
        run("INSERT INTO clients(name,email,phone,country,source,notes,created_at) VALUES(?,?,?,?,?,'',?)",
            (*c, today.isoformat()))
    suppliers = [
        ("SkyLink Consolidators", "Airline / Consolidator", 7),
        ("BedBank Global", "Hotel / Bedbank", 14),
        ("Makkah Premier Tours", "Tour Operator / DMC", 30),
        ("Oceanic Cruises", "Cruise Line", 45),
        ("SafeTrip Insurance", "Insurance", 0),
    ]
    for name, cat, terms in suppliers:
        run("INSERT INTO suppliers(name,category,contact,email,phone,terms_days,notes) VALUES(?,?,'','','',?,'')",
            (name, cat, terms))
    cids = q("SELECT id FROM clients")["id"].tolist()
    sids = q("SELECT id, category FROM suppliers")
    svc_map = {
        "Flight": ("Airline / Consolidator", 400, 1800, 0.08),
        "Hotel": ("Hotel / Bedbank", 300, 2500, 0.15),
        "Umrah / Hajj Package": ("Tour Operator / DMC", 2500, 7000, 0.12),
        "Holiday Package": ("Tour Operator / DMC", 1500, 6000, 0.14),
        "Cruise": ("Cruise Line", 1800, 5000, 0.12),
        "Travel Insurance": ("Insurance", 60, 300, 0.30),
    }
    dests = ["Dubai", "Makkah & Madinah", "London", "Istanbul", "Cancun", "Paris", "Bali", "Caribbean", "Karachi", "Tokyo"]
    year = today.year
    for i in range(45):
        svc = rnd.choice(list(svc_map.keys()))
        cat, lo, hi, mg = svc_map[svc]
        sid = int(sids.loc[sids["category"] == cat, "id"].iloc[0])
        bdate = today - dt.timedelta(days=rnd.randint(0, 330))
        tdate = bdate + dt.timedelta(days=rnd.randint(10, 120))
        rdate = tdate + dt.timedelta(days=rnd.randint(3, 15))
        sell = round(rnd.uniform(lo, hi), 2)
        cost = round(sell * (1 - mg * rnd.uniform(0.7, 1.3)), 2)
        if tdate < today:
            status = "Completed"
        else:
            status = rnd.choice(["Confirmed", "Ticketed", "Quoted", "Confirmed"])
        if rnd.random() < 0.05:
            status, sell, cost = "Cancelled", round(sell * 0.10, 2), round(sell * 0.05, 2)
        if status == "Quoted":
            cpaid = spaid = 0.0
        elif status in ("Completed", "Cancelled"):
            cpaid, spaid = sell, cost
        else:
            cpaid = round(sell * rnd.choice([0.3, 0.5, 1.0]), 2)
            spaid = round(cost * rnd.choice([0.0, 0.5, 1.0]), 2)
        ref = f"VTX-{bdate.year}-{i + 1:04d}"
        run("""INSERT INTO bookings(ref,client_id,supplier_id,service_type,destination,booking_date,
               travel_date,return_date,pax,sell_price,cost_price,client_paid,supplier_paid,status,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'')""",
            (ref, rnd.choice(cids), sid, svc, rnd.choice(dests), bdate.isoformat(),
             tdate.isoformat(), rdate.isoformat(), rnd.randint(1, 5), sell, cost, cpaid, spaid, status))
        if status in ("Confirmed", "Ticketed"):
            create_auto_tasks(ref, tdate, rdate, sell - cpaid, cost - spaid)
    # Monthly operating expenses for the last 11 months
    for m in range(11, -1, -1):
        d = (today.replace(day=1) - dt.timedelta(days=30 * m)).replace(day=5)
        if d > today:
            continue
        for cat, amt in [("Rent", 1200), ("Software & GDS", 250), ("Marketing & Ads", rnd.randint(300, 900)),
                         ("Utilities & Phone", 140), ("Merchant / Bank Fees", rnd.randint(80, 220)),
                         ("Salaries & Wages", 2800)]:
            run("INSERT INTO expenses(date,category,description,amount,method) VALUES(?,?,?,?,?)",
                (d.isoformat(), cat, f"{cat} — {d:%b %Y}", amt, "Bank Transfer"))
    run("INSERT INTO capital(date,type,amount,notes) VALUES(?,?,?,?)",
        ((today - dt.timedelta(days=340)).isoformat(), "Owner Contribution", 25000, "Initial capital"))
    run("INSERT INTO capital(date,type,amount,notes) VALUES(?,?,?,?)",
        ((today - dt.timedelta(days=60)).isoformat(), "Owner Draw", 4000, "Owner distribution"))


def reset_all():
    with closing(connect()) as c, c:
        for t in TABLES:
            if t != "settings":
                c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM sqlite_sequence")


# ----------------------------------------------------------------------------
# Documents & templates
# ----------------------------------------------------------------------------
def invoice_html(row):
    name = get_setting("company_name")
    addr, email, phone = get_setting("company_address"), get_setting("company_email"), get_setting("company_phone")
    td = row["travel_date"].strftime("%b %d, %Y") if pd.notna(row["travel_date"]) else "—"
    rd = row["return_date"].strftime("%b %d, %Y") if pd.notna(row["return_date"]) else "—"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Invoice {row['ref']}</title>
<style>
body{{font-family:Helvetica,Arial,sans-serif;color:#1d2433;max-width:780px;margin:32px auto;padding:0 16px}}
.top{{display:flex;justify-content:space-between;border-bottom:3px solid #0B3C5D;padding-bottom:12px}}
h1{{color:#0B3C5D;margin:0}} table{{width:100%;border-collapse:collapse;margin-top:24px}}
th,td{{padding:10px;border-bottom:1px solid #e3e7ee;text-align:left}} th{{background:#f3f6fa}}
.r{{text-align:right}} .tot td{{font-weight:bold}} .muted{{color:#6b7385;font-size:13px}}
</style></head><body>
<div class="top"><div><h1>{escape(name)}</h1><div class="muted">{escape(addr)}<br>{escape(email)} {('· ' + phone) if phone else ''}</div></div>
<div class="r"><h2 style="margin:0">INVOICE</h2><div class="muted">No. {row['ref']}<br>Date: {dt.date.today():%b %d, %Y}</div></div></div>
<p><b>Bill to:</b> {escape(str(row['client'] or '—'))}</p>
<table><tr><th>Description</th><th>Travel dates</th><th>Pax</th><th class="r">Amount</th></tr>
<tr><td>{escape(str(row['service_type']))} — {escape(str(row['destination'] or ''))}</td><td>{td} → {rd}</td><td>{int(row['pax'] or 1)}</td><td class="r">{money(row['sell_price'])}</td></tr>
<tr class="tot"><td colspan="3" class="r">Total</td><td class="r">{money(row['sell_price'])}</td></tr>
<tr><td colspan="3" class="r">Paid to date</td><td class="r">{money(row['client_paid'])}</td></tr>
<tr class="tot"><td colspan="3" class="r">Balance due</td><td class="r">{money(row['client_balance'])}</td></tr></table>
<p class="muted">Thank you for travelling with {name}. Fares and availability are subject to supplier terms
until ticketed. Cancellation and change fees may apply.</p></body></html>"""


def message_template(kind, row):
    name = get_setting("company_name")
    client = row["client"] or "Valued Client"
    td = row["travel_date"].strftime("%B %d, %Y") if pd.notna(row["travel_date"]) else "TBA"
    if kind == "Booking confirmation":
        return (f"Subject: Booking Confirmed — {row['ref']}\n\nDear {client},\n\n"
                f"Thank you for booking with {name}. Your {row['service_type'].lower()} to "
                f"{row['destination']} departing {td} is confirmed.\n\nBooking reference: {row['ref']}\n"
                f"Total: {money(row['sell_price'])}\nPaid: {money(row['client_paid'])}\n"
                f"Balance: {money(row['client_balance'])}\n\nWe will send your documents before departure.\n\n"
                f"Kind regards,\n{name}")
    if kind == "Payment reminder":
        return (f"Subject: Payment Reminder — {row['ref']}\n\nDear {client},\n\n"
                f"This is a friendly reminder that a balance of {money(row['client_balance'])} is due for "
                f"your trip to {row['destination']} departing {td}.\n\nPlease complete payment at your "
                f"earliest convenience so we can issue your tickets and vouchers.\n\nKind regards,\n{name}")
    if kind == "Pre-departure checklist":
        return (f"Subject: Getting ready for {row['destination']} — {row['ref']}\n\nDear {client},\n\n"
                f"Your trip departs on {td}. Please check:\n• Passport valid 6+ months\n• Visa / ESTA / eVisa approved\n"
                f"• Travel insurance documents\n• Online check-in (opens 24–48h before)\n• Arrive at the airport 3h early for international flights\n\n"
                f"Safe travels!\n{name}")
    if kind == "Quotation":
        return (f"Subject: Your Travel Quote — {row['ref']}\n\nDear {client},\n\n"
                f"As requested, here is our quote for {row['service_type'].lower()} to {row['destination']} "
                f"({int(row['pax'] or 1)} traveller(s), departing {td}):\n\nTotal price: {money(row['sell_price'])}\n\n"
                f"Prices are subject to availability until confirmed with a deposit. Reply to this email to secure it.\n\n"
                f"Kind regards,\n{name}")
    return (f"Subject: How was your trip? — {row['ref']}\n\nDear {client},\n\nWelcome back from {row['destination']}! "
            f"We'd love your feedback — a short review helps us a lot.\n\nThank you for choosing {name}.")


# ----------------------------------------------------------------------------
# Auth (optional — set APP_PASSWORD in Streamlit secrets)
# ----------------------------------------------------------------------------
def check_password():
    try:
        pw = st.secrets.get("APP_PASSWORD", None)
    except Exception:
        pw = None
    if not pw or st.session_state.get("auth_ok"):
        return True
    st.title("✈️ Vertex Travel LLC")
    entered = st.text_input("Password", type="password")
    if st.button("Sign in", type="primary"):
        if entered == pw:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------
def page_dashboard():
    st.title(f"✈️ {get_setting('company_name')} — Dashboard")
    b = bookings_df()
    if b.empty:
        st.info("No data yet. Add bookings, or load sample data to explore the app.")
        if st.button("Load sample data", type="primary"):
            load_demo_data(); st.rerun()
        return

    start, end, label = period_picker("dash_period")
    p, s, ex = pnl(start, end)
    pos = financial_position()

    c = st.columns(4)
    c[0].metric("Revenue (gross sales)", money(p["revenue"]), f"{p['bookings']} bookings")
    c[1].metric("Gross profit", money(p["gross"]), f"{p['gross_margin']:.1f}% margin")
    c[2].metric("Operating expenses", money(p["opex"]))
    c[3].metric("Net profit", money(p["net"]), f"{p['net_margin']:.1f}% net margin",
                delta_color="normal" if p["net"] >= 0 else "inverse")
    c = st.columns(4)
    c[0].metric("Cash position", money(pos["cash"]))
    c[1].metric("Client receivables", money(pos["ar"]))
    c[2].metric("Supplier payables", money(pos["ap"]))
    c[3].metric("Owner's equity", money(pos["equity"]))

    # Alerts
    today = pd.Timestamp(dt.date.today())
    active = b[b["status"].isin(["Confirmed", "Ticketed"])]
    departing = active[(active["travel_date"] >= today) & (active["travel_date"] <= today + pd.Timedelta(days=14))]
    owing = active[(active["client_balance"] > 0.01) & (active["travel_date"] <= today + pd.Timedelta(days=30))]
    t = tasks_df()
    overdue = t[(t["status"] == "Open") & (t["due_date"] < today)]
    a = st.columns(3)
    a[0].warning(f"🛫 {len(departing)} departures in the next 14 days")
    a[1].error(f"💳 {len(owing)} clients owe {money(owing['client_balance'].sum())} (travel ≤ 30 days)")
    a[2].info(f"✅ {len(overdue)} overdue workflow tasks")

    st.subheader("Monthly performance")
    m = monthly_summary(b, expenses_df())
    if not m.empty:
        m = m[m["month"] >= today - pd.DateOffset(months=12)]
        fig = go.Figure()
        fig.add_bar(x=m["month"], y=m["revenue"], name="Revenue", marker_color="#0B3C5D")
        fig.add_bar(x=m["month"], y=m["cogs"] + m["opex"], name="Total costs", marker_color="#C9D6E3")
        fig.add_scatter(x=m["month"], y=m["net"], name="Net profit", mode="lines+markers",
                        line=dict(color="#F2A541", width=3))
        fig.update_layout(barmode="group", height=380, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, width="stretch")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"Profit by service — {label}")
        if not s.empty:
            g = s.groupby("service_type", as_index=False)[["sell_price", "profit"]].sum().sort_values("profit")
            fig = px.bar(g, x="profit", y="service_type", orientation="h", color_discrete_sequence=["#328CC1"],
                         labels={"profit": "Gross profit", "service_type": ""})
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No sales in this period.")
    with col2:
        st.subheader(f"Expense breakdown — {label}")
        if not ex.empty:
            g = ex.groupby("category", as_index=False)["amount"].sum()
            fig = px.pie(g, names="category", values="amount", hole=0.5)
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No expenses in this period.")

    st.subheader("Top clients by revenue")
    if not s.empty:
        top = (s.groupby("client", as_index=False)
                .agg(bookings=("ref", "count"), revenue=("sell_price", "sum"), profit=("profit", "sum"))
                .sort_values("revenue", ascending=False).head(10))
        st.dataframe(top, hide_index=True, width="stretch",
                     column_config={"revenue": st.column_config.NumberColumn(format="$%.2f"),
                                    "profit": st.column_config.NumberColumn(format="$%.2f")})


def booking_form(prefix, defaults=None):
    """Renders booking input widgets; returns dict of values."""
    d = defaults or {}
    cl, sp = clients_df(), suppliers_df()
    cmap = dict(zip(cl["name"], cl["id"]))
    smap = {"— none —": None, **dict(zip(sp["name"], sp["id"]))}
    cnames = list(cmap.keys())
    snames = list(smap.keys())

    c1, c2, c3 = st.columns(3)
    cur_client = next((n for n, i in cmap.items() if i == d.get("client_id")), cnames[0] if cnames else None)
    client = c1.selectbox("Client *", cnames, index=cnames.index(cur_client) if cur_client in cnames else 0,
                          key=f"{prefix}_client")
    cur_sup = next((n for n, i in smap.items() if i == d.get("supplier_id")), "— none —")
    supplier = c2.selectbox("Supplier", snames, index=snames.index(cur_sup), key=f"{prefix}_supplier")
    svc = c3.selectbox("Service type", SERVICE_TYPES,
                       index=SERVICE_TYPES.index(d["service_type"]) if d.get("service_type") in SERVICE_TYPES else 0,
                       key=f"{prefix}_svc")

    c1, c2, c3, c4 = st.columns(4)
    dest = c1.text_input("Destination", d.get("destination") or "", key=f"{prefix}_dest")
    bdate = c2.date_input("Booking date", to_date(d.get("booking_date")) or dt.date.today(), key=f"{prefix}_bdate")
    tdate = c3.date_input("Travel date", to_date(d.get("travel_date")), key=f"{prefix}_tdate")
    rdate = c4.date_input("Return date", to_date(d.get("return_date")), key=f"{prefix}_rdate")

    c1, c2, c3, c4 = st.columns(4)
    pax = c1.number_input("Pax", min_value=1, value=int(d.get("pax") or 1), key=f"{prefix}_pax")
    sell = c2.number_input("Sell price (client pays)", min_value=0.0, value=fnum(d.get("sell_price")),
                           step=50.0, key=f"{prefix}_sell")
    cost = c3.number_input("Cost price (net to supplier)", min_value=0.0, value=fnum(d.get("cost_price")),
                           step=50.0, key=f"{prefix}_cost")
    status = c4.selectbox("Status", STATUSES,
                          index=STATUSES.index(d["status"]) if d.get("status") in STATUSES else 2,
                          key=f"{prefix}_status")

    c1, c2, c3 = st.columns(3)
    cpaid = c1.number_input("Received from client", min_value=0.0, value=fnum(d.get("client_paid")),
                            step=50.0, key=f"{prefix}_cpaid")
    spaid = c2.number_input("Paid to supplier", min_value=0.0, value=fnum(d.get("supplier_paid")),
                            step=50.0, key=f"{prefix}_spaid")
    profit = sell - cost
    c3.metric("Booking profit", money(profit), f"{(profit / sell * 100) if sell else 0:.1f}% margin")
    notes = st.text_area("Notes", d.get("notes") or "", key=f"{prefix}_notes", height=70)
    if status == "Cancelled":
        st.caption("For a cancellation, set Sell = fee you keep and Cost = supplier penalty.")
    return dict(client_id=cmap.get(client), supplier_id=smap.get(supplier), service_type=svc,
                destination=dest, booking_date=iso(bdate), travel_date=iso(tdate), return_date=iso(rdate),
                pax=int(pax), sell_price=sell, cost_price=cost, client_paid=cpaid, supplier_paid=spaid,
                status=status, notes=notes)


def page_bookings():
    st.title("🧳 Bookings")
    if clients_df().empty:
        st.warning("Add at least one client first (Clients & Suppliers page).")
        return
    tab_new, tab_edit, tab_list = st.tabs(["➕ New booking", "✏️ Update / payments", "📋 All bookings"])

    with tab_new:
        ref = next_ref()
        st.caption(f"Reference will be **{ref}**")
        v = booking_form("new")
        if st.button("Save booking", type="primary", key="save_new"):
            run("""INSERT INTO bookings(ref,client_id,supplier_id,service_type,destination,booking_date,
                   travel_date,return_date,pax,sell_price,cost_price,client_paid,supplier_paid,status,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ref, v["client_id"], v["supplier_id"], v["service_type"], v["destination"], v["booking_date"],
                 v["travel_date"], v["return_date"], v["pax"], v["sell_price"], v["cost_price"],
                 v["client_paid"], v["supplier_paid"], v["status"], v["notes"]))
            n = 0
            if v["status"] in SALE_STATUSES and v["status"] != "Cancelled":
                n = create_auto_tasks(ref, to_date(v["travel_date"]), to_date(v["return_date"]),
                                      v["sell_price"] - v["client_paid"], v["cost_price"] - v["supplier_paid"])
            st.success(f"Booking {ref} saved." + (f" {n} workflow tasks created." if n else ""))

    b = bookings_df()
    with tab_edit:
        if b.empty:
            st.info("No bookings yet.")
        else:
            labels = {r.ref: f"{r.ref} · {r.client} · {r.destination} · {r.status}" for r in b.itertuples()}
            sel = st.selectbox("Select booking", list(labels), format_func=labels.get, key="edit_sel")
            row = b[b["ref"] == sel].iloc[0]
            st.markdown("**Quick payment**")
            c1, c2, c3 = st.columns([2, 2, 1])
            ptype = c1.radio("Type", ["Client payment received", "Supplier payment made"], horizontal=True,
                             key=f"ptype_{row['id']}")
            amt = c2.number_input("Amount", min_value=0.0, step=50.0, key=f"pamt_{row['id']}")
            if c3.button("Record", key=f"prec_{row['id']}") and amt > 0:
                col = "client_paid" if ptype.startswith("Client") else "supplier_paid"
                run(f"UPDATE bookings SET {col} = {col} + ? WHERE id=?", (amt, int(row["id"])))
                st.success(f"Recorded {money(amt)}."); st.rerun()
            st.divider()
            raw = q("SELECT * FROM bookings WHERE id=?", (int(row["id"]),)).iloc[0].to_dict()
            v = booking_form(f"edit_{row['id']}", raw)
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("Update booking", type="primary", key=f"upd_{row['id']}"):
                run("""UPDATE bookings SET client_id=?,supplier_id=?,service_type=?,destination=?,booking_date=?,
                       travel_date=?,return_date=?,pax=?,sell_price=?,cost_price=?,client_paid=?,supplier_paid=?,
                       status=?,notes=? WHERE id=?""",
                    (v["client_id"], v["supplier_id"], v["service_type"], v["destination"], v["booking_date"],
                     v["travel_date"], v["return_date"], v["pax"], v["sell_price"], v["cost_price"],
                     v["client_paid"], v["supplier_paid"], v["status"], v["notes"], int(row["id"])))
                if raw["status"] not in SALE_STATUSES and v["status"] in ["Confirmed", "Ticketed"]:
                    create_auto_tasks(row["ref"], to_date(v["travel_date"]), to_date(v["return_date"]),
                                      v["sell_price"] - v["client_paid"], v["cost_price"] - v["supplier_paid"])
                if v["status"] == "Cancelled":
                    run("UPDATE tasks SET status='Cancelled' WHERE related_ref=? AND status='Open'", (row["ref"],))
                st.success("Booking updated."); st.rerun()
            if c2.button("Delete", key=f"del_{row['id']}"):
                st.session_state["confirm_del"] = int(row["id"])
            if st.session_state.get("confirm_del") == int(row["id"]):
                st.warning(f"Delete {row['ref']} permanently?")
                if st.button("Yes, delete", key=f"delyes_{row['id']}"):
                    run("DELETE FROM bookings WHERE id=?", (int(row["id"]),))
                    run("DELETE FROM tasks WHERE related_ref=?", (row["ref"],))
                    st.session_state.pop("confirm_del", None); st.rerun()

    with tab_list:
        if b.empty:
            st.info("No bookings yet.")
        else:
            c1, c2, c3 = st.columns(3)
            fs = c1.multiselect("Status", STATUSES, default=[], key="flt_status")
            fv = c2.multiselect("Service", SERVICE_TYPES, default=[], key="flt_svc")
            txt = c3.text_input("Search client / destination / ref", key="flt_txt")
            f = b.copy()
            if fs: f = f[f["status"].isin(fs)]
            if fv: f = f[f["service_type"].isin(fv)]
            if txt:
                t = txt.lower()
                f = f[f["client"].fillna("").str.lower().str.contains(t) |
                      f["destination"].fillna("").str.lower().str.contains(t) |
                      f["ref"].fillna("").str.lower().str.contains(t)]
            show = f[["ref", "client", "service_type", "destination", "booking_date", "travel_date", "status",
                      "pax", "sell_price", "cost_price", "profit", "margin_pct", "client_balance",
                      "supplier_balance", "supplier"]]
            st.dataframe(show, hide_index=True, width="stretch", column_config={
                "booking_date": st.column_config.DateColumn("Booked"),
                "travel_date": st.column_config.DateColumn("Travel"),
                "sell_price": st.column_config.NumberColumn("Sell", format="$%.2f"),
                "cost_price": st.column_config.NumberColumn("Cost", format="$%.2f"),
                "profit": st.column_config.NumberColumn("Profit", format="$%.2f"),
                "margin_pct": st.column_config.NumberColumn("Margin %", format="%.1f%%"),
                "client_balance": st.column_config.NumberColumn("Client owes", format="$%.2f"),
                "supplier_balance": st.column_config.NumberColumn("We owe supplier", format="$%.2f"),
            })
            st.caption(f"{len(f)} bookings · Sales {money(f['sell_price'].sum())} · Profit {money(f['profit'].sum())}")
            st.download_button("Download CSV", f.to_csv(index=False).encode(), "bookings.csv", "text/csv")


def page_contacts():
    st.title("👥 Clients & Suppliers")
    tab_c, tab_s = st.tabs(["Clients", "Suppliers"])
    b = bookings_df()
    with tab_c:
        with st.form("add_client", clear_on_submit=True):
            st.markdown("**Add client**")
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Name *"); email = c2.text_input("Email"); phone = c3.text_input("Phone")
            c1, c2, c3 = st.columns(3)
            country = c1.text_input("Country", "USA"); source = c2.selectbox("Lead source", LEAD_SOURCES)
            notes = c3.text_input("Notes (passport expiry, preferences…)")
            if st.form_submit_button("Add client", type="primary"):
                if name.strip():
                    run("INSERT INTO clients(name,email,phone,country,source,notes,created_at) VALUES(?,?,?,?,?,?,?)",
                        (name.strip(), email, phone, country, source, notes, dt.date.today().isoformat()))
                    st.success(f"Added {name}."); st.rerun()
                else:
                    st.error("Name is required.")
        cl = clients_df()
        if not cl.empty:
            stats = (b[b["is_sale"]].groupby("client_id")
                     .agg(bookings=("ref", "count"), lifetime_sales=("sell_price", "sum"),
                          profit=("profit", "sum"), balance_due=("client_balance", "sum")))
            view = cl.merge(stats, left_on="id", right_index=True, how="left").fillna(
                {"bookings": 0, "lifetime_sales": 0, "profit": 0, "balance_due": 0})
            st.dataframe(view.drop(columns=["created_at"]), hide_index=True, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="$%.2f")
                                        for k in ["lifetime_sales", "profit", "balance_due"]})
            with st.expander("Delete a client"):
                dsel = st.selectbox("Client", cl["name"], key="del_client")
                if st.button("Delete client"):
                    cid = int(cl.loc[cl["name"] == dsel, "id"].iloc[0])
                    if (b["client_id"] == cid).any():
                        st.error("This client has bookings — delete or reassign them first.")
                    else:
                        run("DELETE FROM clients WHERE id=?", (cid,)); st.rerun()
    with tab_s:
        with st.form("add_supplier", clear_on_submit=True):
            st.markdown("**Add supplier**")
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Name *"); cat = c2.selectbox("Category", SUPPLIER_CATEGORIES)
            terms = c3.number_input("Payment terms (days before travel)", min_value=0, value=14)
            c1, c2, c3 = st.columns(3)
            contact = c1.text_input("Contact person"); email = c2.text_input("Email"); phone = c3.text_input("Phone")
            if st.form_submit_button("Add supplier", type="primary"):
                if name.strip():
                    run("INSERT INTO suppliers(name,category,contact,email,phone,terms_days,notes) VALUES(?,?,?,?,?,?,'')",
                        (name.strip(), cat, contact, email, phone, int(terms)))
                    st.success(f"Added {name}."); st.rerun()
                else:
                    st.error("Name is required.")
        sp = suppliers_df()
        if not sp.empty:
            stats = (b[b["is_sale"]].groupby("supplier_id")
                     .agg(bookings=("ref", "count"), purchases=("cost_price", "sum"),
                          we_owe=("supplier_balance", "sum")))
            view = sp.merge(stats, left_on="id", right_index=True, how="left").fillna(
                {"bookings": 0, "purchases": 0, "we_owe": 0})
            st.dataframe(view, hide_index=True, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="$%.2f") for k in ["purchases", "we_owe"]})


def page_expenses():
    st.title("💸 Expenses & Capital")
    tab_e, tab_k = st.tabs(["Operating expenses", "Owner capital & loans"])
    with tab_e:
        with st.form("add_exp", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            d = c1.date_input("Date", dt.date.today()); cat = c2.selectbox("Category", EXPENSE_CATEGORIES)
            amt = c3.number_input("Amount", min_value=0.0, step=10.0); method = c4.selectbox("Paid by", PAY_METHODS)
            desc = st.text_input("Description")
            if st.form_submit_button("Add expense", type="primary") and amt > 0:
                run("INSERT INTO expenses(date,category,description,amount,method) VALUES(?,?,?,?,?)",
                    (d.isoformat(), cat, desc, amt, method))
                st.success("Expense added."); st.rerun()
        e = expenses_df()
        if not e.empty:
            st.dataframe(e, hide_index=True, width="stretch", column_config={
                "date": st.column_config.DateColumn(), "amount": st.column_config.NumberColumn(format="$%.2f")})
            with st.expander("Delete an expense"):
                eid = st.selectbox("Expense ID", e["id"], key="del_exp")
                if st.button("Delete expense"):
                    run("DELETE FROM expenses WHERE id=?", (int(eid),)); st.rerun()
    with tab_k:
        st.caption("Record money the owner puts in or takes out, and any business loans. "
                   "These affect cash and equity but are not profit or loss.")
        with st.form("add_cap", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            d = c1.date_input("Date", dt.date.today()); t = c2.selectbox("Type", CAPITAL_TYPES)
            amt = c3.number_input("Amount", min_value=0.0, step=100.0)
            notes = st.text_input("Notes")
            if st.form_submit_button("Add entry", type="primary") and amt > 0:
                run("INSERT INTO capital(date,type,amount,notes) VALUES(?,?,?,?)", (d.isoformat(), t, amt, notes))
                st.success("Entry added."); st.rerun()
        k = capital_df()
        if not k.empty:
            st.dataframe(k, hide_index=True, width="stretch", column_config={
                "date": st.column_config.DateColumn(), "amount": st.column_config.NumberColumn(format="$%.2f")})
            with st.expander("Delete an entry"):
                kid = st.selectbox("Entry ID", k["id"], key="del_cap")
                if st.button("Delete entry"):
                    run("DELETE FROM capital WHERE id=?", (int(kid),)); st.rerun()


def statement_table(rows):
    df = pd.DataFrame(rows, columns=["Line item", "Amount"])
    df["Amount"] = df["Amount"].apply(lambda v: money(v) if isinstance(v, (int, float)) else v)
    st.dataframe(df, hide_index=True, width="stretch")


def page_financials():
    st.title("📊 Financial Statements")
    st.caption(f"Revenue recognised by **{get_setting('revenue_basis').lower()}** (change in Settings).")
    tab_pl, tab_bs, tab_cf, tab_tr = st.tabs(["Profit & Loss", "Financial Position", "Cash Summary", "Trends & Break-even"])

    with tab_pl:
        start, end, label = period_picker("pl_period")
        p, s, ex = pnl(start, end)
        rows = [("REVENUE", "")]
        if not s.empty:
            for svc, v in s.groupby("service_type")["sell_price"].sum().sort_values(ascending=False).items():
                rows.append((f"   {svc}", float(v)))
        rows += [("Total revenue", p["revenue"]), ("Less: cost of sales (supplier net)", -p["cogs"]),
                 ("GROSS PROFIT", p["gross"]), ("Gross margin", f"{p['gross_margin']:.1f}%"),
                 ("OPERATING EXPENSES", "")]
        if not ex.empty:
            for cat, v in ex.groupby("category")["amount"].sum().sort_values(ascending=False).items():
                rows.append((f"   {cat}", -float(v)))
        rows += [("Total operating expenses", -p["opex"]),
                 ("NET PROFIT / (LOSS) BEFORE TAX", p["net"]),
                 ("Net margin", f"{p['net_margin']:.1f}%"),
                 (f"Tax reserve ({fnum(get_setting('tax_rate')):.0f}% of profit, estimate)", -p["tax"]),
                 ("NET PROFIT AFTER TAX RESERVE", p["net_after_tax"])]
        st.subheader(f"{get_setting('company_name')} — Profit & Loss")
        st.caption(f"{start:%b %d, %Y} to {end:%b %d, %Y}" if label != "All time" else "All time")
        statement_table(rows)
        if p["net"] >= 0:
            st.success(f"Profit of {money(p['net'])} on {p['bookings']} bookings ({p['pax']} travellers).")
        else:
            st.error(f"Loss of {money(-p['net'])} for this period.")
        csv = pd.DataFrame(rows, columns=["Line item", "Amount"]).to_csv(index=False).encode()
        st.download_button("Download P&L (CSV)", csv, "profit_and_loss.csv", "text/csv")

    with tab_bs:
        pos = financial_position()
        st.subheader(f"Statement of Financial Position — as of {dt.date.today():%b %d, %Y}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Assets**")
            statement_table([("Cash & bank", pos["cash"]), ("Accounts receivable (clients)", pos["ar"]),
                             ("Supplier prepayments / credits", pos["supplier_prepay"]),
                             ("TOTAL ASSETS", pos["assets"])])
        with c2:
            st.markdown("**Liabilities & Equity**")
            statement_table([("Accounts payable (suppliers)", pos["ap"]),
                             ("Client deposits & credits", pos["client_deposits"]),
                             ("Loans outstanding", pos["loans"]),
                             ("TOTAL LIABILITIES", pos["liabilities"]),
                             ("Owner capital (net of draws)", pos["owner_capital"]),
                             ("Retained earnings (cumulative profit)", pos["retained"]),
                             ("TOTAL EQUITY", pos["equity"]),
                             ("TOTAL LIABILITIES + EQUITY", pos["liabilities"] + pos["equity"])])
        ok = abs(pos["check"]) < 0.01
        (st.success if ok else st.error)("Balance check: " + ("balanced ✔" if ok else f"off by {money(pos['check'])}"))
        cr = pos["assets"] / pos["liabilities"] if pos["liabilities"] else float("inf")
        c = st.columns(3)
        c[0].metric("Working capital", money(pos["assets"] - pos["liabilities"]))
        c[1].metric("Current ratio", "∞" if cr == float("inf") else f"{cr:.2f}")
        c[2].metric("Client money held (deposits)", money(pos["client_deposits"]))
        st.caption("Tax reserve is shown on the P&L only; it is an estimate, not a booked liability.")

    with tab_cf:
        pos = financial_position()
        rows = [("Opening cash", pos["opening"]), ("+ Owner contributions", pos["contrib"]),
                ("+ Loans received", pos["loan_in"]), ("+ Receipts from clients", pos["client_receipts"]),
                ("− Payments to suppliers", -pos["supplier_payments"]),
                ("− Operating expenses paid", -pos["expenses_paid"]),
                ("− Owner draws", -pos["draws"]), ("− Loan repayments", -pos["loan_out"]),
                ("CLOSING CASH", pos["cash"])]
        st.subheader("Cash summary (all time)")
        statement_table(rows)
        fig = go.Figure(go.Waterfall(
            x=[r[0] for r in rows], y=[r[1] for r in rows[:-1]] + [0],
            measure=["absolute"] + ["relative"] * 7 + ["total"],
            connector={"line": {"color": "#999"}},
            increasing={"marker": {"color": "#2E8B57"}}, decreasing={"marker": {"color": "#C0392B"}},
            totals={"marker": {"color": "#0B3C5D"}}))
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")

    with tab_tr:
        m = monthly_summary(bookings_df(), expenses_df())
        if m.empty:
            st.info("No data yet.")
        else:
            fig = px.line(m, x="month", y=["revenue", "gross", "net"], markers=True,
                          labels={"value": "Amount", "month": "", "variable": ""})
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch")
            last = m.tail(6)
            avg_opex = last["opex"].mean()
            gm = last["gross"].sum() / last["revenue"].sum() if last["revenue"].sum() else 0
            c = st.columns(3)
            c[0].metric("Avg monthly overheads (6 mo)", money(avg_opex))
            c[1].metric("Avg gross margin (6 mo)", f"{gm * 100:.1f}%")
            c[2].metric("Break-even sales / month", money(avg_opex / gm) if gm > 0 else "n/a")
            st.caption("Break-even = monthly overheads ÷ gross margin %. Sell at least this much each month to cover costs.")
            st.dataframe(m, hide_index=True, width="stretch", column_config={
                "month": st.column_config.DateColumn(format="MMM YYYY"),
                **{k: st.column_config.NumberColumn(format="$%.2f") for k in ["revenue", "cogs", "opex", "gross", "net"]}})


def page_workflow():
    st.title("⚙️ Workflow Automation")
    tab_t, tab_a, tab_m, tab_i = st.tabs(["✅ Tasks", "🔔 Alerts", "✉️ Message templates", "🧾 Invoices"])
    b = bookings_df()
    today = pd.Timestamp(dt.date.today())

    with tab_t:
        st.caption("Tasks are created automatically when a booking is confirmed: collect balance (T-30), "
                   "pay supplier (T-21), send documents (T-7), pre-departure call (T-2), feedback (return+2).")
        with st.form("add_task", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            title = c1.text_input("New task"); due = c2.date_input("Due", dt.date.today())
            pr = c3.selectbox("Priority", ["High", "Medium", "Low"], index=1)
            refs = ["—"] + b["ref"].tolist()
            ref = c4.selectbox("Booking", refs)
            if st.form_submit_button("Add task") and title.strip():
                run("INSERT INTO tasks(title,due_date,related_ref,priority,status,created_at) VALUES(?,?,?,?, 'Open', ?)",
                    (title, due.isoformat(), None if ref == "—" else ref, pr, dt.date.today().isoformat()))
                st.rerun()
        t = tasks_df()
        show = st.radio("Show", ["Open", "Done", "All"], horizontal=True, key="task_filter")
        if show != "All":
            t = t[t["status"] == show]
        if t.empty:
            st.info("No tasks.")
        for r in t.sort_values("due_date").itertuples():
            overdue = r.status == "Open" and pd.notna(r.due_date) and r.due_date < today
            icon = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}.get(r.priority, "⚪")
            c1, c2, c3 = st.columns([6, 2, 1])
            due_s = r.due_date.strftime("%b %d, %Y") if pd.notna(r.due_date) else "—"
            c1.markdown(f"{icon} {'~~' if r.status == 'Done' else ''}{r.title}{'~~' if r.status == 'Done' else ''}")
            c2.markdown(f"{'⚠️ **' if overdue else ''}{due_s}{'** overdue' if overdue else ''}")
            if r.status == "Open" and c3.button("Done", key=f"done_{r.id}"):
                run("UPDATE tasks SET status='Done' WHERE id=?", (int(r.id),)); st.rerun()

    with tab_a:
        active = b[b["status"].isin(["Confirmed", "Ticketed"])]
        st.subheader("Departing in next 14 days")
        dep = active[(active["travel_date"] >= today) & (active["travel_date"] <= today + pd.Timedelta(days=14))]
        st.dataframe(dep[["ref", "client", "destination", "travel_date", "status", "client_balance"]],
                     hide_index=True, width="stretch")
        st.subheader("Client balances outstanding")
        ow = active[active["client_balance"] > 0.01].sort_values("travel_date")
        st.dataframe(ow[["ref", "client", "travel_date", "sell_price", "client_paid", "client_balance"]],
                     hide_index=True, width="stretch")
        st.subheader("Supplier payments due")
        sp = suppliers_df()[["id", "terms_days"]].rename(columns={"id": "supplier_id"})
        due = active[active["supplier_balance"] > 0.01].merge(sp, on="supplier_id", how="left")
        due["pay_by"] = due["travel_date"] - pd.to_timedelta(due["terms_days"].fillna(0), unit="D")
        st.dataframe(due.sort_values("pay_by")[["ref", "supplier", "pay_by", "cost_price", "supplier_paid", "supplier_balance"]],
                     hide_index=True, width="stretch")
        st.subheader("Open quotes to follow up")
        qt = b[b["status"].isin(["Inquiry", "Quoted"])]
        st.dataframe(qt[["ref", "client", "service_type", "destination", "booking_date", "sell_price"]],
                     hide_index=True, width="stretch")

    with tab_m:
        if b.empty:
            st.info("No bookings yet.")
        else:
            labels = {r.ref: f"{r.ref} · {r.client} · {r.destination}" for r in b.itertuples()}
            ref = st.selectbox("Booking", list(labels), format_func=labels.get, key="tmpl_bk")
            i = int(b.index[b["ref"] == ref][0])
            kind = st.selectbox("Template", ["Booking confirmation", "Payment reminder", "Pre-departure checklist",
                                             "Quotation", "Post-trip feedback"])
            st.text_area("Copy and send", message_template(kind, b.loc[i]), height=300)

    with tab_i:
        if b.empty:
            st.info("No bookings yet.")
        else:
            labels = {r.ref: f"{r.ref} · {r.client} · {money(r.sell_price)}" for r in b.itertuples()}
            ref = st.selectbox("Booking", list(labels), format_func=labels.get, key="inv_bk")
            i = int(b.index[b["ref"] == ref][0])
            html = invoice_html(b.loc[i])
            st.download_button("Download invoice (HTML — open and print to PDF)", html.encode(),
                               f"invoice_{b.loc[i]['ref']}.html", "text/html", type="primary")
            st.html(html)


def page_settings():
    st.title("🛠️ Settings & Data")
    with st.form("settings"):
        st.subheader("Company")
        c1, c2 = st.columns(2)
        name = c1.text_input("Company name", get_setting("company_name"))
        addr = c2.text_input("Address", get_setting("company_address"))
        email = c1.text_input("Email", get_setting("company_email"))
        phone = c2.text_input("Phone", get_setting("company_phone"))
        st.subheader("Accounting")
        c1, c2, c3 = st.columns(3)
        cur = c1.text_input("Currency symbol", get_setting("currency"))
        opening = c2.number_input("Opening cash balance", value=fnum(get_setting("opening_cash")), step=100.0)
        tax = c3.number_input("Tax reserve rate (%)", min_value=0.0, max_value=60.0,
                              value=fnum(get_setting("tax_rate")), step=1.0,
                              help="Planning estimate only. Confirm your actual federal/state rates with a CPA.")
        basis = c1.selectbox("Recognise revenue by", ["Booking date", "Travel date"],
                             index=0 if get_setting("revenue_basis") == "Booking date" else 1)
        auto = c2.checkbox("Auto-create workflow tasks for confirmed bookings", get_setting("auto_tasks") == "1")
        if st.form_submit_button("Save settings", type="primary"):
            for k, v in [("company_name", name), ("company_address", addr), ("company_email", email),
                         ("company_phone", phone), ("currency", cur), ("opening_cash", opening),
                         ("tax_rate", tax), ("revenue_basis", basis), ("auto_tasks", "1" if auto else "0")]:
                set_setting(k, v)
            st.success("Saved."); st.rerun()

    st.subheader("Backup & restore")
    st.caption("Streamlit Community Cloud storage is temporary — the database resets when the app restarts "
               "or redeploys. Download a backup regularly and restore it after a restart.")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for t in TABLES:
            q(f"SELECT * FROM {t}").to_excel(xw, sheet_name=t, index=False)
    st.download_button("⬇️ Download full backup (.xlsx)", buf.getvalue(),
                       f"vertex_travel_backup_{dt.date.today()}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    up = st.file_uploader("Restore from backup (.xlsx)", type=["xlsx"])
    if up is not None and st.button("Restore now (replaces current data)"):
        sheets = pd.read_excel(up, sheet_name=None)
        with closing(connect()) as c, c:
            for t in TABLES:
                if t in sheets:
                    c.execute(f"DELETE FROM {t}")
                    sheets[t].to_sql(t, c, if_exists="append", index=False)
        st.success("Data restored."); st.rerun()

    st.subheader("Sample data")
    c1, c2 = st.columns(2)
    if c1.button("Load sample data"):
        load_demo_data(); st.success("Sample data loaded."); st.rerun()
    if c2.button("Erase all business data"):
        st.session_state["confirm_reset"] = True
    if st.session_state.get("confirm_reset"):
        st.warning("This deletes all clients, suppliers, bookings, expenses, capital and tasks.")
        if st.button("Yes, erase everything"):
            reset_all(); st.session_state.pop("confirm_reset"); st.rerun()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
PAGES = {
    "📈 Dashboard": page_dashboard,
    "🧳 Bookings": page_bookings,
    "👥 Clients & Suppliers": page_contacts,
    "💸 Expenses & Capital": page_expenses,
    "📊 Financial Statements": page_financials,
    "⚙️ Workflow Automation": page_workflow,
    "🛠️ Settings & Data": page_settings,
}


def main():
    init_db()
    if not check_password():
        return
    with st.sidebar:
        st.markdown(f"## ✈️ {get_setting('company_name')}")
        st.caption("Travel Agency Management")
        page = st.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed", key="nav")
        st.divider()
        pos = financial_position()
        st.metric("Cash position", money(pos["cash"]))
        st.metric("Owner's equity", money(pos["equity"]))
        st.caption("Back up your data regularly from Settings & Data.")
    PAGES[page]()


if __name__ == "__main__":
    main()
