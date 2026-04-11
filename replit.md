# Money Mate - Personal Finance Manager

## Project Overview
A Flask-based personal finance PWA (Progressive Web App) that helps users track income, expenses, savings goals, and subscriptions. It provides spending insights, subscription detection, and budget analysis using the 50/30/20 rule. Installable on mobile as a native-like app.

## Architecture
- **Backend**: Python / Flask
- **Database**: SQLite via SQLAlchemy (`instance/finance.db`)
- **Auth**: Flask-Login (session-based)
- **Forms**: Flask-WTF / WTForms
- **Admin Panel**: Flask-Admin (accessible at `/admin` for admin user)
- **Frontend**: Jinja2 templates, Bootstrap 5, vanilla JS
- **Charts**: matplotlib (rendered server-side as PNG, loaded lazily via API endpoints)
- **PWA**: Service Worker + Web App Manifest (installable on iOS/Android)

## Directory Structure
```
├── app.py              # Main Flask application, routes, and business logic
├── models.py           # SQLAlchemy database models (User, Income, Expense, Goal)
├── forms.py            # WTForms form definitions
├── requirements.txt    # Python dependencies
├── Readme.txt          # Basic setup instructions
├── scripts/
│   └── post-merge.sh   # Post-merge hook script
├── instance/
│   └── finance.db      # SQLite database (auto-created on first run)
├── templates/          # Jinja2 HTML templates
│   ├── base.html       # Base layout with navbar, bottom nav (mobile), SW registration
│   ├── offline.html    # Offline fallback page (served by service worker)
│   ├── index.html
│   ├── dashboard.html
│   ├── login.html
│   ├── register.html
│   ├── tutorial.html
│   ├── add_income.html
│   ├── add_expense.html
│   ├── add_goal.html
│   ├── edit_goal.html
│   ├── goal_detail.html
│   ├── goals.html
│   ├── subscriptions.html
│   ├── analysis.html   # Lazy-loads charts via /analysis/chart/* endpoints
│   ├── email_import.html
│   ├── settings.html
│   ├── mpin_setup.html
│   └── account_info.html
└── static/
    ├── style.css       # Custom styles, mobile bottom nav, safe-area insets
    ├── manifest.json   # PWA manifest with shortcuts
    ├── sw.js           # Service worker (v4): caches Bootstrap CDN, offline fallback
    └── icons/
        ├── icon-48.png
        ├── icon-192.png
        └── icon-512.png
```

## Key Features
- **Dashboard**: Monthly overview with burn rate, 50/30/20 budget tracking, skeleton loaders
- **Expense Tracking**: Category/subcategory system with needs vs wants classification
- **Subscription Detection**: Auto-detects recurring expenses
- **Goal Tracking**: Savings goals with milestones and what-if scenarios
- **Analysis Page**: 4 charts loaded lazily (parallel browser requests to `/analysis/chart/*`), stats shown immediately
- **Email Import (IMAP)**: Connects to inbox via IMAP/SSL, scans for financial emails, imports transactions
- **Admin Panel**: `/admin` route (requires username "admin")
- **Dark Mode**: Toggle via navbar button (persisted in localStorage + cookie for server-side theming)
- **PWA / Mobile**: Bottom navigation bar on mobile, safe-area insets (notch support), Bootstrap CDN cached, offline fallback page, update notification banner

## Chart API Endpoints (Lazy Loading)
- `GET /analysis/chart/dist` — Expense distribution pie chart (PNG)
- `GET /analysis/chart/cats` — Category breakdown bar chart (PNG)
- `GET /analysis/chart/trend` — Monthly spending trend line chart (PNG)
- `GET /analysis/chart/inc_exp` — Income vs Expense bar chart (PNG)

All chart endpoints use `Cache-Control: private, max-age=300` (5-minute client cache).

## Service Worker Cache Strategy
- **Static assets + Bootstrap CDN**: cache-first
- **Chart endpoints**: network-first, cached fallback
- **Navigation requests**: network-first, cached fallback, then /offline
- **Cache version**: `money-mate-v4` (bump this when making breaking static changes)

## Environment Variables
- `SESSION_SECRET`: Flask secret key for sessions (required)
- `ADMIN_PASSWORD`: Password for the `/create_admin` route (optional)

## Running the App
- Development: `python app.py` (runs on port 5000)
- Production: `gunicorn --bind=0.0.0.0:5000 --reuse-port app:app`

## Notes
- Passwords are stored in plaintext (no hashing) — consider adding bcrypt for production
- The database is auto-created/migrated on startup via `db.create_all()` and ALTER TABLE statements
- Admin user is created via the `/create_admin` route
- All datetime operations use naive UTC (`.replace(tzinfo=None)`) for SQLite compatibility
