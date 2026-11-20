# Financial Transaction Analytics Pipeline & BI Dashboard.

An end-to-end financial transaction analytics pipeline built to answer:
**"Am I spending more or less than last month — and in which categories? What is my savings rate?"**

Processes checking, savings, and credit-card transaction exports into a structured
PostgreSQL data warehouse, surfaced through SQL analytical views and a Power BI dashboard.

## Dashboard Preview

![Dashboard](dashboard/dashboard_preview.png)

---

## Project Overview

This pipeline extracts raw bank CSV exports, transforms and categorises each
transaction using Python, and loads the results into a star-schema PostgreSQL
database. SQL views built on top of the warehouse power a Power BI dashboard
that tracks monthly spending, category-level breakdowns, and account balances.

---

## Tech Stack

| Layer        | Technology                              |
|--------------|-----------------------------------------|
| ETL          | Python 3 · Pandas · NumPy               |
| Database     | PostgreSQL · SQLAlchemy · psycopg2      |
| Analytics    | SQL (CTEs, window functions, views)     |
| Visualisation| Power BI Desktop                        |

**Pipeline flow:**

```
Raw CSV exports → Python ETL → PostgreSQL → SQL Views → Power BI Dashboard
```

---

## Key Features

- Extracts raw transaction CSVs from checking, savings, and credit-card accounts
- Transforms and standardises data: dates, categories, transaction types, and descriptions
- Separates ambiguous transactions into a manual-review DataFrame rather than failing silently
- Loads clean data into a PostgreSQL star schema (fact + dimension tables)
- SQL analytical views using joins, CTEs, aggregations, and window functions
- Power BI dashboard covering monthly spending, category-level analysis, and account balances

---

## Database Schema

```
account ──────────────────────────┐
transaction_type ─────────────────┤──► transaction_facts
category (optional) ──────────────┤
date ─────────────────────────────┘
```

See [`database_creation/data_dictionary.md`](database_creation/data_dictionary.md) for full column descriptions and relationships.

---

## SQL Views

| View                      | Purpose                                                              |
|---------------------------|----------------------------------------------------------------------|
| `monthly_spend_summary`   | Monthly totals, prior-month % change, and running yearly total       |
| `monthly_spend_category`  | Spending per category per month, ranked within each month            |
| `daily_spend`             | All purchase transactions with a daily running yearly spend total    |
| `daily_category_balance`  | Running spend per category at daily granularity (Power BI source)   |
| `monthly_account_balances`| End-of-month running balance per account                            |
| `monthly_savings_rate`    | Net savings rate per month — inflows vs outflows as a % of income   |

---

## Project Structure

```
finances-database/
├── transactions_processing/
│   ├── transactions_processing_functions.py   # ETL helper functions
│   ├── cc_processing_example.ipynb            # Credit-card ETL walkthrough
│   ├── checking_processing_example.ipynb      # Checking-account ETL walkthrough
│   └── savings_processing_example.ipynb       # Savings-account ETL walkthrough
│
├── database_creation/
│   ├── final_database_creation_script.sql     # PostgreSQL DDL (schema + tables)
│   ├── data_dictionary.md                     # Column definitions and relationships
│   └── dimensions_data/                       # Seed CSVs for dimension tables
│       ├── account.csv
│       ├── category.csv
│       ├── date.csv
│       └── transaction_type.csv
│
├── database_views/
│   ├── views_creation_script.sql              # Analytical view definitions
│   └── views_overview.ipynb                   # View query examples
│
├── dashboard/
│   ├── gl_analytics_dashboard.pbix            # Power BI dashboard file
│   └── dashboard_preview.png                  # Dashboard screenshot
│
├── .env.example          # Environment variable template
├── .gitignore
├── requirements.txt
└── README.md
```

---

## How to Run

### 1 — Install dependencies

```bash
pip install -r requirements.txt
```

### 2 — Configure environment variables

Copy `.env.example` to `.env` and fill in your PostgreSQL credentials:

```bash
cp .env.example .env
```

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password_here
DB_NAME=gl_transactions
```

> [!CAUTION]
> Never commit `.env` to version control. It is already listed in `.gitignore`.

### 3 — Create the database

```sql
-- In psql or your PostgreSQL client:
CREATE DATABASE gl_transactions;
```

### 4 — Run the schema creation script

```bash
psql -U postgres -d gl_transactions -f database_creation/final_database_creation_script.sql
```

### 5 — Load dimension seed data

Load the CSVs from `database_creation/dimensions_data/` into their respective tables using `psql \copy` or your preferred PostgreSQL client.

### 6 — Run the ETL notebooks

Open and run the notebooks in `transactions_processing/` with your own bank CSV exports:

- `savings_processing_example.ipynb`
- `checking_processing_example.ipynb`
- `cc_processing_example.ipynb`

The notebooks read the input CSV path from a variable at the top of each file — replace it with the path to your own export.

### 7 — Create analytical views

```bash
psql -U postgres -d gl_transactions -f database_views/views_creation_script.sql
```

### 8 — Open the dashboard

Open `dashboard/gl_analytics_dashboard.pbix` in Power BI Desktop and update the data source connection to point to your PostgreSQL instance.

---

## Database Migration Note

The initial schema design was modelled using MySQL Workbench. The project was
subsequently migrated to PostgreSQL, which is the production database for this
pipeline. The DDL script and all Python connection code target PostgreSQL
exclusively.

---

## Contributing / Adaptation

This project was built as a personal financial analytics tool. If you adapt it
for your own use, update the account seed data in
`database_creation/dimensions_data/account.csv` to reflect your own accounts,
and adjust the category mapping in `cc_file_cleanup` to match your bank's
category labels.
