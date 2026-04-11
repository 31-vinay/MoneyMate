# Money Mate - Personal Finance Manager

## Project Overview
A Flask-based personal finance PWA (Progressive Web App) that helps users track income, expenses, savings goals, and subscriptions. It provides spending insights, subscription detection, and budget analysis using the 50/30/20 rule. Installable on mobile as a native-like app.

## Architecture
- **Backend**: Python / Flask
- **Database**: SQLite via SQLAlchemy (`instance/finance.db`)
- **Auth**: Flask-Login (session-based), passwords hashed with Werkzeug `pbkdf2:sha256`
- **Forms**: Flask-WTF / WTForms
- **Admin Panel**: Flask-Admin (accessible at `/admin` for admin user)
- **Frontend**: Jinja2 templates, Bootstrap 5, vanilla JS
- **Charts**: matplotlib (rendered server-side as PNG, loaded lazily via API endpoints)
- **PWA**: Service Worker + Web App Manifest (installable on iOS/Android)

## Directory Structure
```
├── app.py              # Flask routes only (~700 lines, clean and slim)
├── categorizer.py      # Expense categories, auto_categorize_transaction, classify_essential
├── charts.py           # Chart generation functions (pie, bar, line, horizontal bar)
├── parsers.py          # Bank statement parser (CSV/XLS/XLSX/PDF) + IMAP email scanner
├── helpers.py          # Business logic: detect_subscriptions, run_monthly_reset, etc.
├── models.py           # SQLAlchemy models with DB indexes + password hashing methods
├── forms.py            # WTForms form definitions
├── requirements.txt    # Python dependencies (deduplicated)
├── .gitignore          # Ignores __pycache__, .db, .env, venv, etc.
├── scripts/
│   └── post-merge.sh   # Post-merge hook (pip install -r requirements.txt)
├── instance/
│   └── finance.db      # SQLite database (auto-created on first run)
├── templates/          # Jinja2 HTML templates
│   ├── base.html       # Base layout with navbar, bottom nav (mobile), SW registration
│   ├── offline.html    # Offline fallback page (served by service worker)
│   ├── index.html, dashboard.html, login.html, register.html, tutorial.html
│   ├── add_income.html, add_expense.html, add_goal.html, edit_goal.html
│   ├── goal_detail.html, goals.html, subscriptions.html, analysis.html
│   ├── email_import.html, settings.html, mpin_setup.html, account_info.html
└── static/
    ├── style.css       # Custom styles, mobile bottom nav, safe-area insets
    ├── manifest.json   # PWA manifest with shortcuts
    ├── sw.js           # Service worker (v4): caches Bootstrap CDN, offline fallback
    └── icons/          # icon-48.png, icon-192.png, icon-512.png
```

## Module Responsibilities
- **`categorizer.py`**: `expense_categories` dict, `auto_categorize_transaction()`, `classify_essential()`
- **`charts.py`**: `get_analysis_data()`, `chart_expense_distribution()`, `chart_income_vs_expense()`, `chart_monthly_trend()`, `chart_category_breakdown()`
- **`parsers.py`**: `parse_bank_statement()` (CSV/XLS/XLSX/PDF), `scan_imap_emails()`, IMAP presets
- **`helpers.py`**: `detect_subscriptions()`, `get_spending_suggestions()`, `run_monthly_reset()`, `check_subscription_expiry()`

## Security
- Passwords hashed using `werkzeug.security.generate_password_hash` (pbkdf2:sha256)
- `User.set_password(raw)` and `User.check_password(raw)` methods handle hashing/verification
- Legacy plain-text passwords are auto-upgraded to hashed form on first login
- MPIN stored as plain 6-digit string (not sensitive, not a password)

## Database Indexes
- `User`: indexed on `email`, `username`
- `Income`: composite index on `(user_id, date_received)`
- `Expense`: composite indexes on `(user_id, date)` and `(user_id, is_subscription)`
- `Goal`: indexed on `user_id`

## Key Features
- **Dashboard**: Monthly overview with burn rate, 50/30/20 budget tracking, skeleton loaders
- **Expense Tracking**: Category/subcategory system with needs vs wants classification
- **Subscription Detection**: Auto-detects recurring expenses
- **Goal Tracking**: Savings goals with milestones and what-if scenarios
- **Analysis Page**: 4 charts loaded lazily (parallel browser requests to `/analysis/chart/*`), stats shown immediately
- **Bank Statement Import**: Parses CSV, Excel (.xlsx/.xls), PDF, and ZIP files; auto-categorizes expenses
- **Email Import (IMAP)**: Connects to inbox via IMAP/SSL, scans for financial emails, imports transactions
- **Admin Panel**: `/admin` route (requires username "admin")
- **Dark Mode**: Toggle via navbar button (persisted in localStorage + cookie for server-side theming)
- **PWA / Mobile**: Bottom navigation bar on mobile, safe-area insets (notch support), Bootstrap CDN cached, offline fallback page

## Chart API Endpoints (Lazy Loading)
- `GET /analysis/chart/dist` — Expense distribution pie chart (PNG)
- `GET /analysis/chart/cats` — Category breakdown bar chart (PNG)
- `GET /analysis/chart/trend` — Monthly spending trend line chart (PNG)
- `GET /analysis/chart/inc_exp` — Income vs Expense bar chart (PNG)

All chart endpoints use `Cache-Control: private, max-age=300` (5-minute client cache).

## Environment Variables
- `SESSION_SECRET`: Flask secret key for sessions (required in production)
- `ADMIN_PASSWORD`: Password for the `/create_admin` route (optional)

## Running the App
- Development: `python app.py` (runs on port 5000)
- Production: `gunicorn --bind=0.0.0.0:5000 --reuse-port app:app`

## Notes
- The database is auto-created/migrated on startup via `db.create_all()` and ALTER TABLE statements
- Admin user is created via the `/create_admin` route (requires `ADMIN_PASSWORD` env var)
- All datetime operations use naive UTC (`.replace(tzinfo=None)`) for SQLite compatibility
- Monthly reset runs automatically on first dashboard visit of a new calendar month
