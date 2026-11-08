# ✈️ Vertex Travel LLC — Agency Manager

An all-in-one Streamlit app for running a travel agency: bookings, clients, suppliers,
expenses, workflow automation, invoices, and live **Profit & Loss** and **Financial Position**.

## Features

| Module | What it does |
|---|---|
| **Dashboard** | Revenue, gross & net profit, margins, cash, receivables, payables, equity; monthly trend; profit by service; top clients; alerts |
| **Bookings** | Auto reference numbers (`VTX-2026-0001`), sell vs. cost with live margin, status pipeline (Inquiry → Quoted → Confirmed → Ticketed → Completed / Cancelled), quick payment recording, search & CSV export |
| **Clients & Suppliers** | CRM with lead source, lifetime sales and balances; suppliers with payment terms and amounts owed |
| **Expenses & Capital** | Operating expenses by category; owner contributions, draws and loans |
| **Financial Statements** | P&L for any period, balance sheet with automatic balance check, cash-flow waterfall, monthly trends, break-even sales |
| **Workflow Automation** | Tasks auto-created when a booking is confirmed (collect balance T-30, pay supplier T-21, send docs T-7, pre-departure call T-2, feedback after return); alerts for departures, unpaid balances, supplier payments due and open quotes; ready-to-send email templates; printable invoices |
| **Settings & Data** | Company details, tax-reserve rate, revenue basis (booking vs. travel date), Excel backup / restore, sample data |

## How the accounting works

- **Revenue** = sell price of bookings with status Confirmed, Ticketed, Completed or Cancelled.
  **Cost of sales** = net cost to suppliers. **Gross profit** = the difference.
- **Cancellations:** set *Sell* = fee you keep and *Cost* = supplier penalty, so only the retained margin counts.
- **Inquiry / Quoted** bookings are not sales. Any money taken on them shows as *client deposits* (a liability).
- **Net profit** = gross profit − operating expenses. The tax reserve is a planning estimate only —
  confirm your actual federal and state obligations with a CPA.
- **Balance sheet:** Assets (cash, receivables, supplier prepayments) − Liabilities (payables,
  client deposits, loans) = Equity (owner capital + retained earnings). The app checks this every time.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```
Click **Load sample data** on the dashboard to explore with 45 demo bookings.

## Deploy: GitHub + Streamlit Community Cloud

1. Create a new GitHub repository (e.g. `vertex-travel-app`) and upload these files, keeping the
   folder structure (`app.py`, `requirements.txt`, `.streamlit/config.toml`, `.gitignore`, `README.md`).
   ```bash
   git init && git add . && git commit -m "Vertex Travel app"
   git branch -M main
   git remote add origin https://github.com/<your-username>/vertex-travel-app.git
   git push -u origin main
   ```
2. Go to **share.streamlit.io** → *Create app* → pick the repo, branch `main`, main file `app.py` → *Deploy*.
3. **Protect it with a password:** app → *Settings* → *Secrets*, paste
   `APP_PASSWORD = "your-strong-password"` (see `secrets.toml.example`). Also consider making the
   GitHub repo private.

## ⚠️ Important: data persistence

The app stores data in a local SQLite file. On Streamlit Community Cloud that storage is **temporary** —
it resets whenever the app restarts, sleeps for a long time, or you push new code.

- **Now:** use *Settings & Data → Download full backup* regularly (e.g. end of each day) and
  *Restore* after any restart.
- **Later (recommended for production):** move the database to a hosted service such as
  Supabase / Neon (PostgreSQL). Only the `connect()`, `run()` and `q()` helpers in `app.py` need changing.

## Project structure

```
vertex-travel-app/
├── app.py                  # the whole application
├── requirements.txt
├── secrets.toml.example    # template for the optional password
├── .gitignore
└── .streamlit/
    └── config.toml         # brand theme
```
