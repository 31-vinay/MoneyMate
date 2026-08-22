import io
import os
import re
import ssl
import imaplib
import zipfile
import calendar
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    session,
    send_from_directory,
    send_file,
    make_response,
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from sqlalchemy import func
from werkzeug.middleware.proxy_fix import ProxyFix

from models import (
    db,
    User,
    Income,
    Expense,
    Goal,
    CreditCard,
    CreditCardStatement,
)
from forms import (
    RegistrationForm,
    LoginForm,
    IncomeForm,
    ExpenseForm,
    GoalForm,
    SavingsUpdateForm,
)
from categorizer import (
    expense_categories,
    auto_categorize_transaction,
    classify_essential,
)
from charts import (
    get_analysis_data,
    chart_expense_distribution,
    chart_income_vs_expense,
    chart_monthly_trend,
    chart_category_breakdown,
    chart_png_response,
)
from helpers import (
    detect_subscriptions,
    get_spending_suggestions,
    get_expenses_for_month,
    run_monthly_reset,
    check_subscription_expiry,
    assign_goal_priority,
    normalize_goal_priorities,
)
from parsers import parse_bank_statement, scan_imap_emails, IMAP_PRESETS
from credit_cards import (
    classify_card_transaction,
    cycle_dates,
    possible_card_payment_matches,
    refresh_statement_status,
    statement_month_data,
)

# ── App Setup ─────────────────────────────────────────────────

class _StripCookieVary:
    """Strip 'Cookie' from the Vary header on PWA-critical responses.

    Flask's session interface unconditionally adds 'Vary: Cookie' to every
    response, which causes Chrome's installability checker (which fetches the
    manifest anonymously) to treat the manifest as a session-dependent resource
    and skip the PWA install prompt, falling back to "Create shortcut".
    """
    _PWA_PATHS = frozenset({"/manifest.json", "/sw.js"})

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO") not in self._PWA_PATHS:
            return self.wsgi_app(environ, start_response)

        def _start_response(status, headers, exc_info=None):
            out = []
            for name, value in headers:
                if name.lower() == "vary":
                    parts = [p.strip() for p in value.split(",")
                             if p.strip().lower() != "cookie"]
                    value = ", ".join(parts) or "Accept-Encoding"
                out.append((name, value))
            return start_response(status, out, exc_info)

        return self.wsgi_app(environ, _start_response)


app = Flask(__name__)
app.wsgi_app = _StripCookieVary(ProxyFix(app.wsgi_app, x_proto=1, x_host=1))  # ty:ignore[invalid-assignment]

app.config["SECRET_KEY"] = os.environ.get("SESSION_SECRET", "change-me-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///finance.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"


# ── Flask-Admin ───────────────────────────────────────────────


class AdminModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.username == "admin"

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("login"))


admin = Admin(app, name="Finance Manager")
admin.add_view(AdminModelView(User, db.session))
admin.add_view(AdminModelView(Income, db.session))
admin.add_view(AdminModelView(Expense, db.session))
admin.add_view(AdminModelView(Goal, db.session))


# ── DB Init + Migrations ──────────────────────────────────────

with app.app_context():
    db.create_all()
    _migrations = [
        "ALTER TABLE user ADD COLUMN has_seen_tutorial BOOLEAN DEFAULT 0 NOT NULL",
        "ALTER TABLE user ADD COLUMN last_monthly_reset DATETIME",
        "ALTER TABLE goal ADD COLUMN priority VARCHAR(10) NOT NULL DEFAULT '1'",
        "ALTER TABLE income ADD COLUMN created_at DATETIME",
        "ALTER TABLE income ADD COLUMN is_recurring BOOLEAN DEFAULT 0",
        "ALTER TABLE expense ADD COLUMN created_at DATETIME",
        "ALTER TABLE expense ADD COLUMN sub_start_date DATETIME",
        "ALTER TABLE expense ADD COLUMN sub_end_date DATETIME",
        "ALTER TABLE expense ADD COLUMN sub_expired_notified BOOLEAN DEFAULT 0",
        "ALTER TABLE user ADD COLUMN mpin VARCHAR(6)",
        "ALTER TABLE user ADD COLUMN notifications_enabled BOOLEAN DEFAULT 1",
        "ALTER TABLE user ADD COLUMN savings_balance FLOAT DEFAULT 0.0",
        "ALTER TABLE user ADD COLUMN goals_wants_pct FLOAT DEFAULT 30.0",
        "ALTER TABLE expense ADD COLUMN source_type VARCHAR(30) DEFAULT 'MANUAL'",
        "ALTER TABLE expense ADD COLUMN credit_card_id INTEGER",
        "ALTER TABLE expense ADD COLUMN billing_cycle_id VARCHAR(80)",
        "ALTER TABLE expense ADD COLUMN statement_id INTEGER",
        "ALTER TABLE expense ADD COLUMN transaction_id VARCHAR(120)",
        "ALTER TABLE expense ADD COLUMN merchant VARCHAR(200)",
        "ALTER TABLE expense ADD COLUMN need_want_type VARCHAR(10)",
        "ALTER TABLE expense ADD COLUMN is_settlement BOOLEAN DEFAULT 0",
        "ALTER TABLE credit_card_statement ADD COLUMN outstanding FLOAT DEFAULT 0.0 NOT NULL",
    ]
    for stmt in _migrations:
        try:
            with db.engine.connect() as conn:
                conn.execute(db.text(stmt))
                conn.commit()
        except Exception:
            pass
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("UPDATE goal SET priority='1' WHERE priority='high'"))
            conn.execute(
                db.text("UPDATE goal SET priority='2' WHERE priority='medium'")
            )
            conn.execute(db.text("UPDATE goal SET priority='3' WHERE priority='low'"))
            conn.commit()
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ── Admin Bootstrap ───────────────────────────────────────────


@app.route("/create_admin")
def create_admin():
    admin_user = User.query.filter_by(username="admin").first()
    if not admin_user:
        admin_password = os.environ.get("ADMIN_PASSWORD")
        if not admin_password:
            return "ADMIN_PASSWORD environment variable is not set.", 500
        admin_user = User(username="admin", email="admin@example.com")
        admin_user.set_password(admin_password)
        db.session.add(admin_user)
        db.session.commit()
        return "Admin user created!"
    return "Admin user already exists."


# ── PWA Routes ────────────────────────────────────────────────


@app.route("/manifest.json")
def pwa_manifest():
    response = send_from_directory(
        "static", "manifest.json", mimetype="application/manifest+json"
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Vary"] = "Accept-Encoding"
    return response


@app.route("/sw.js")
def pwa_sw():
    response = send_from_directory("static", "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Vary"] = "Accept-Encoding"
    return response


@app.route("/offline")
def offline():
    return render_template("offline.html")


# ── Public Routes ─────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = RegistrationForm()
    if form.validate_on_submit():
        email_lower = form.email.data.strip().lower()
        if User.query.filter(User.email.ilike(email_lower)).first():
            form.email.errors.append("An account with this email already exists.")
            return render_template("register.html", form=form)
        if User.query.filter(User.username.ilike(form.username.data.strip())).first():
            form.username.errors.append("This username is already taken.")
            return render_template("register.html", form=form)
        try:
            user = User(username=form.username.data.strip(), email=email_lower)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Account created! You can now log in.", "success")
            return redirect(url_for("login"))
        except Exception:
            db.session.rollback()
            flash(
                "Something went wrong creating your account. Please try again.",
                "danger",
            )
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = LoginForm()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        mpin_input = request.form.get("mpin_input", "").strip()
        password_input = request.form.get("password", "").strip()
        user = User.query.filter(User.email.ilike(email)).first()
        if user:
            if mpin_input:
                if user.mpin and user.mpin == mpin_input:
                    login_user(user)
                    return redirect(
                        url_for("tutorial")
                        if not user.has_seen_tutorial
                        else url_for("dashboard")
                    )
                flash("Incorrect MPIN. Please try again.", "danger")
                return render_template(
                    "login.html", form=form, prefill_email=email, show_mpin=True
                )
            elif password_input:
                if user.check_password(password_input):
                    db.session.commit()
                    login_user(user)
                    return redirect(
                        url_for("tutorial")
                        if not user.has_seen_tutorial
                        else url_for("dashboard")
                    )
                flash("Incorrect password. Please try again.", "danger")
                return render_template(
                    "login.html",
                    form=form,
                    prefill_email=email,
                    show_mpin=bool(user.mpin),
                )
        else:
            flash("No account found with that email.", "danger")
    return render_template("login.html", form=form)


@app.route("/check-mpin-status")
def check_mpin_status():
    email = request.args.get("email", "").strip().lower()
    user = User.query.filter(User.email.ilike(email)).first()
    if user:
        return jsonify(
            {"exists": True, "has_mpin": bool(user.mpin), "username": user.username}
        )
    return jsonify({"exists": False, "has_mpin": False})


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/tutorial")
@login_required
def tutorial():
    return render_template("tutorial.html")


@app.route("/complete_tutorial")
@login_required
def complete_tutorial():
    current_user.has_seen_tutorial = True
    db.session.commit()
    return redirect(url_for("dashboard"))


# ── Settings / Account ────────────────────────────────────────


@app.route("/profile")
@login_required
def profile():
    return redirect(url_for("settings"))


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/setup-mpin", methods=["GET", "POST"])
@login_required
def setup_mpin():
    if request.method == "POST":
        new_pin = request.form.get("new_pin", "").strip()
        confirm_pin = request.form.get("confirm_pin", "").strip()
        current_password = request.form.get("current_password", "").strip()
        if len(new_pin) != 6 or not new_pin.isdigit():
            flash("MPIN must be exactly 6 digits.", "danger")
        elif new_pin != confirm_pin:
            flash("PINs do not match.", "danger")
        elif not current_user.check_password(current_password):
            flash("Current password is incorrect.", "danger")
        else:
            current_user.mpin = new_pin
            db.session.commit()
            flash("MPIN set successfully!", "success")
            return redirect(url_for("settings"))
    return render_template("mpin_setup.html", mode="setup")


@app.route("/change-mpin", methods=["GET", "POST"])
@login_required
def change_mpin():
    if request.method == "POST":
        old_pin = request.form.get("old_pin", "").strip()
        new_pin = request.form.get("new_pin", "").strip()
        confirm_pin = request.form.get("confirm_pin", "").strip()
        if current_user.mpin != old_pin:
            flash("Current MPIN is incorrect.", "danger")
        elif len(new_pin) != 6 or not new_pin.isdigit():
            flash("New MPIN must be exactly 6 digits.", "danger")
        elif new_pin != confirm_pin:
            flash("New PINs do not match.", "danger")
        else:
            current_user.mpin = new_pin
            db.session.commit()
            flash("MPIN changed successfully!", "success")
            return redirect(url_for("settings"))
    return render_template("mpin_setup.html", mode="change")


@app.route("/remove-mpin", methods=["POST"])
@login_required
def remove_mpin():
    current_password = request.form.get("current_password", "").strip()
    if not current_user.check_password(current_password):
        flash("Password incorrect. MPIN not removed.", "danger")
    else:
        current_user.mpin = None
        db.session.commit()
        flash("MPIN removed successfully.", "success")
    return redirect(url_for("settings"))


@app.route("/change-email", methods=["POST"])
@login_required
def change_email():
    new_email = request.form.get("new_email", "").strip()
    current_password = request.form.get("current_password", "").strip()
    if not current_user.check_password(current_password):
        flash("Password is incorrect.", "danger")
    elif not new_email or "@" not in new_email:
        flash("Please enter a valid email address.", "danger")
    elif User.query.filter(User.email == new_email, User.id != current_user.id).first():
        flash("That email is already in use by another account.", "danger")
    else:
        current_user.email = new_email
        db.session.commit()
        flash("Email updated successfully!", "success")
    return redirect(url_for("settings"))


@app.route("/change-password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "").strip()
    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()
    if not current_user.check_password(current_password):
        flash("Current password is incorrect.", "danger")
    elif len(new_password) < 4:
        flash("New password must be at least 4 characters.", "danger")
    elif new_password != confirm_password:
        flash("New passwords do not match.", "danger")
    else:
        current_user.set_password(new_password)
        db.session.commit()
        flash("Password updated successfully!", "success")
    return redirect(url_for("settings"))


@app.route("/toggle-notifications", methods=["POST"])
@login_required
def toggle_notifications():
    current_user.notifications_enabled = not current_user.notifications_enabled
    db.session.commit()
    state = "enabled" if current_user.notifications_enabled else "disabled"
    flash(f"Pop notifications {state}.", "success")
    return redirect(url_for("settings"))


@app.route("/update-goals-wants-pct", methods=["POST"])
@login_required
def update_goals_wants_pct():
    try:
        pct = float(request.form.get("goals_wants_pct", 30))
        if pct != pct:
            raise ValueError("NaN")
        pct = max(0.0, min(100.0, pct))
        current_user.goals_wants_pct = round(pct, 1)
        db.session.commit()
        flash(
            f"Goals budget updated: {current_user.goals_wants_pct:.0f}% of your Wants budget will go to goals each month.",
            "success",
        )
    except (ValueError, TypeError):
        flash("Invalid percentage value.", "danger")
    return redirect(url_for("settings"))


@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    current_password = request.form.get("current_password", "").strip()
    if not current_user.check_password(current_password):
        flash("Incorrect password. Account not deleted.", "danger")
        return redirect(url_for("settings"))
    user = current_user
    logout_user()
    Income.query.filter_by(user_id=user.id).delete()
    Expense.query.filter_by(user_id=user.id).delete()
    Goal.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("Your account has been permanently deleted.", "info")
    return redirect(url_for("index"))


@app.route("/reset-account", methods=["POST"])
@login_required
def reset_account():
    current_password = request.form.get("current_password", "").strip()
    if not current_user.check_password(current_password):
        flash("Incorrect password. Account data not reset.", "danger")
        return redirect(url_for("settings"))
    Income.query.filter_by(user_id=current_user.id).delete()
    Expense.query.filter_by(user_id=current_user.id).delete()
    Goal.query.filter_by(user_id=current_user.id).delete()
    current_user.last_monthly_reset = None
    current_user.savings_balance = 0.0
    db.session.commit()
    flash("Your account data has been reset. Your account is still active.", "success")
    return redirect(url_for("dashboard"))


@app.route("/request-account-info")
@login_required
def request_account_info():
    incomes = (
        Income.query.filter_by(user_id=current_user.id)
        .order_by(Income.date_received.desc())
        .all()
    )
    expenses = (
        Expense.query.filter_by(user_id=current_user.id)
        .order_by(Expense.date.desc())
        .all()
    )
    goals = Goal.query.filter_by(user_id=current_user.id).all()
    return render_template(
        "account_info.html",
        incomes=incomes,
        expenses=expenses,
        goals=goals,
        now=datetime.now(timezone.utc).replace(tzinfo=None),
    )


# ── Dashboard ─────────────────────────────────────────────────


@app.route("/dashboard")
@login_required
def dashboard():
    was_reset, net_leftover, goals_funded_reset = run_monthly_reset(current_user)
    if was_reset:
        msg = "A new month has started! Your dashboard has been reset. Subscriptions and recurring income are preserved."
        if net_leftover > 0:
            msg += (
                f" ₹{net_leftover:,.2f} from last month's remaining balance "
                "was added to this month's total income and savings."
            )
        if goals_funded_reset > 0:
            msg += f" ₹{goals_funded_reset:,.2f} was allocated to your goals from your Wants budget."
        flash(msg, "info")

    sub_alerts = check_subscription_expiry(current_user.id)
    for alert in sub_alerts:
        if alert["type"] == "expired":
            flash(
                f"⚠️ Your subscription '{alert['name']}' expired on {alert['end_date'].strftime('%d %b %Y')}. Visit Subscriptions to remove it.",
                "warning",
            )
        elif alert["type"] == "expiring":
            flash(
                f"🔔 Your subscription '{alert['name']}' expires in {alert['days_left']} day(s) on {alert['end_date'].strftime('%d %b %Y')}.",
                "info",
            )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    selected_month_str = request.args.get("month", "")
    try:
        sel_dt = datetime.strptime(selected_month_str, "%Y-%m")
        view_year, view_month = sel_dt.year, sel_dt.month
    except ValueError:
        view_year, view_month = now.year, now.month
    month_start = datetime(view_year, view_month, 1)
    month_end = (
        datetime(view_year + 1, 1, 1)
        if view_month == 12
        else datetime(view_year, view_month + 1, 1)
    )
    is_current_month = view_year == now.year and view_month == now.month

    month_options = []
    for i in range(12):
        mo, yo = now.month - i, now.year
        while mo <= 0:
            mo += 12
            yo -= 1
        month_options.append(
            (f"{yo:04d}-{mo:02d}", datetime(yo, mo, 1).strftime("%b %Y"))
        )
    selected_month_label = datetime(view_year, view_month, 1).strftime("%B %Y")

    expenses = get_expenses_for_month(current_user.id, month_start, month_end)
    card_month = statement_month_data(current_user.id, month_start, month_end)
    regular_expenses = [
        e for e in expenses
        if e.source_type != "CREDIT_CARD" and not e.is_settlement
    ]
    total_spent = sum(e.amount for e in regular_expenses) + card_month["total"]
    essential_spent = (
        sum(e.amount for e in regular_expenses if e.is_essential)
        + card_month["needs"]
    )
    non_essential_spent = (
        sum(e.amount for e in regular_expenses if not e.is_essential)
        + card_month["wants"]
    )
    needs_pct = (essential_spent / total_spent * 100) if total_spent else 0
    wants_pct = (non_essential_spent / total_spent * 100) if total_spent else 0
    wants_alert = wants_pct > 50

    categories = {}
    for e in regular_expenses:
        categories[e.category] = categories.get(e.category, 0) + e.amount
    for category, amount in card_month["categories"].items():
        categories[category] = categories.get(category, 0) + amount

    incomes = Income.query.filter(
        Income.user_id == current_user.id,
        Income.date_received >= month_start,
        Income.date_received < month_end,
    ).all()
    recorded_income = sum(i.amount for i in incomes)
    has_explicit_carry = any(
        i.source == "Previous Month Balance" for i in incomes
    )
    previous_month_balance = sum(
        i.amount for i in incomes if i.source == "Previous Month Balance"
    )
    if not has_explicit_carry:
        previous_month_start = (
            datetime(view_year - 1, 12, 1)
            if view_month == 1
            else datetime(view_year, view_month - 1, 1)
        )
        previous_month_income = (
            db.session.query(func.sum(Income.amount))
            .filter(
                Income.user_id == current_user.id,
                Income.date_received >= previous_month_start,
                Income.date_received < month_start,
            )
            .scalar()
            or 0
        )
        previous_month_expenses = (
            db.session.query(func.sum(Expense.amount))
            .filter(
                Expense.user_id == current_user.id,
                Expense.date >= previous_month_start,
                Expense.date < month_start,
            )
            .scalar()
            or 0
        )
        previous_month_balance = round(
            max(0, previous_month_income - previous_month_expenses), 2
        )
    total_income = recorded_income + (
        previous_month_balance
        if not has_explicit_carry
        else 0
    )
    source_breakdown = {}
    for inc in incomes:
        source_breakdown[inc.source] = source_breakdown.get(inc.source, 0) + inc.amount
    if previous_month_balance > 0 and "Previous Month Balance" not in source_breakdown:
        source_breakdown["Previous Month Balance"] = previous_month_balance
    source_percentages = {
        src: (amt / total_income * 100) if total_income else 0
        for src, amt in source_breakdown.items()
    }

    if is_current_month:
        yesterday_start = datetime(now.year, now.month, now.day) - timedelta(days=1)
        recent_incomes = (
            Income.query.filter(
                Income.user_id == current_user.id,
                Income.date_received >= yesterday_start,
            )
            .order_by(Income.date_received.desc())
            .all()
        )
        recent_expenses = (
            Expense.query.filter(
                Expense.user_id == current_user.id, Expense.date >= yesterday_start
            )
            .order_by(Expense.date.desc())
            .all()
        )
    else:
        recent_incomes = (
            Income.query.filter(
                Income.user_id == current_user.id,
                Income.date_received >= month_start,
                Income.date_received < month_end,
            )
            .order_by(Income.date_received.desc())
            .limit(30)
            .all()
        )
        recent_expenses = (
            Expense.query.filter(
                Expense.user_id == current_user.id,
                Expense.date >= month_start,
                Expense.date < month_end,
            )
            .order_by(Expense.date.desc())
            .limit(30)
            .all()
        )

    days_passed = (
        max(1, (now - month_start).days + 1)
        if is_current_month
        else max(1, (month_end - month_start).days)
    )
    burn_rate = total_spent / days_passed

    subscriptions = detect_subscriptions(current_user.id)
    total_sub_cost = sum(s["avg_amount"] for s in subscriptions)

    goals = (
        Goal.query.filter_by(user_id=current_user.id)
        .order_by(Goal.created_at.desc())
        .all()
    )
    if normalize_goal_priorities(current_user.id):
        db.session.commit()
        goals = (
            Goal.query.filter_by(user_id=current_user.id)
            .order_by(Goal.created_at.desc())
            .all()
        )

    monthly_spending = defaultdict(float)
    for exp in expenses:
        monthly_spending[exp.date.strftime("%b")] += exp.amount

    budget_needs = total_income * 0.50
    budget_wants = total_income * 0.30
    budget_savings = total_income * 0.20

    needs_remaining = budget_needs - essential_spent
    wants_remaining = budget_wants - non_essential_spent
    needs_used_pct = (
        min(100, (essential_spent / budget_needs * 100)) if budget_needs > 0 else 0
    )
    wants_used_pct = (
        min(100, (non_essential_spent / budget_wants * 100)) if budget_wants > 0 else 0
    )
    needs_warning = (needs_remaining > 0) and (needs_remaining <= budget_needs * 0.10)
    wants_warning = (wants_remaining > 0) and (wants_remaining <= budget_wants * 0.10)
    needs_over = needs_remaining < 0
    wants_over = wants_remaining < 0

    total_savings = round(current_user.savings_balance or 0.0, 2)
    goals_wants_pct = max(0.0, min(100.0, current_user.goals_wants_pct or 30.0))
    goals_alloc = round(budget_wants * goals_wants_pct / 100, 2)
    free_wants = round(budget_wants - goals_alloc, 2)

    days_in_month = calendar.monthrange(view_year, view_month)[1]
    days_remaining = days_in_month - now.day if is_current_month else 0
    projected_month_end_spend = total_spent + (burn_rate * days_remaining)
    predicted_balance = total_income - projected_month_end_spend
    show_month_forecast_warning = (
        is_current_month and (days_remaining <= 10) and (predicted_balance < 0)
    )
    shortfall = abs(predicted_balance) if predicted_balance < 0 else 0
    required_daily_savings = (
        round(shortfall / days_remaining, 2) if days_remaining > 0 else shortfall
    )

    non_essential_categories = {}
    for e in expenses:
        if not e.is_essential:
            non_essential_categories[e.category] = (
                non_essential_categories.get(e.category, 0) + e.amount
            )
    top_non_essential_cats = sorted(
        non_essential_categories.items(), key=lambda x: x[1], reverse=True
    )[:3]
    top_subs = sorted(subscriptions, key=lambda s: s["avg_amount"], reverse=True)[:3]

    def goal_priority_num(g):
        try:
            return int(g.priority)
        except (ValueError, TypeError):
            return 99

    active_goals = sorted(
        [g for g in goals if g.remaining_amount > 0], key=goal_priority_num
    )
    goal_suggestions = []
    if total_income > 0 and active_goals and goals_alloc > 0:
        weights = [1.0 / goal_priority_num(g) for g in active_goals]
        total_weight = sum(weights)
        for g, w in zip(active_goals, weights):
            alloc_pct = (
                w / total_weight if total_weight > 0 else 1.0 / len(active_goals)
            )
            suggested = round(min(goals_alloc * alloc_pct, g.remaining_amount), 2)
            goal_suggestions.append(
                {
                    "name": g.name,
                    "priority": goal_priority_num(g),
                    "suggested": suggested,
                    "remaining": g.remaining_amount,
                    "id": g.id,
                }
            )

    return render_template(
        "dashboard.html",
        now=now,
        total_income=total_income,
        previous_month_balance=previous_month_balance,
        total_spent=total_spent,
        burn_rate=burn_rate,
        source_breakdown=source_breakdown,
        source_percentages=source_percentages,
        essential=essential_spent,
        non_essential=non_essential_spent,
        needs_pct=needs_pct,
        wants_pct=wants_pct,
        wants_alert=wants_alert,
        categories=categories,
        subscriptions=subscriptions,
        total_sub_cost=total_sub_cost,
        recent_incomes=recent_incomes,
        recent_expenses=recent_expenses,
        monthly_spending=dict(monthly_spending),
        budget_needs=budget_needs,
        budget_wants=budget_wants,
        budget_savings=budget_savings,
        needs_remaining=needs_remaining,
        wants_remaining=wants_remaining,
        needs_used_pct=needs_used_pct,
        wants_used_pct=wants_used_pct,
        needs_warning=needs_warning,
        wants_warning=wants_warning,
        needs_over=needs_over,
        wants_over=wants_over,
        total_savings=total_savings,
        goals_wants_pct=goals_wants_pct,
        goals_alloc=goals_alloc,
        free_wants=free_wants,
        goal_suggestions=goal_suggestions,
        goals=goals,
        days_remaining=days_remaining,
        days_in_month=days_in_month,
        projected_month_end_spend=projected_month_end_spend,
        predicted_balance=predicted_balance,
        show_month_forecast_warning=show_month_forecast_warning,
        shortfall=shortfall,
        required_daily_savings=required_daily_savings,
        top_non_essential_cats=top_non_essential_cats,
        top_subs=top_subs,
        month_options=month_options,
        selected_month_label=selected_month_label,
        selected_month_str=f"{view_year:04d}-{view_month:02d}",
        is_current_month=is_current_month,
    )


# ── Credit Cards ────────────────────────────────────────────────


def _card_owned(card_id):
    card = db.session.get(CreditCard, card_id)
    return card if card and card.user_id == current_user.id else None


@app.route("/credit-cards", methods=["GET", "POST"])
@login_required
def credit_cards():
    if request.method == "POST":
        last4 = request.form.get("last4", "").strip()
        try:
            credit_limit = float(request.form.get("credit_limit", 0))
            start_day = max(1, min(31, int(request.form.get("billing_cycle_start_day", 1))))
            statement_day = max(1, min(31, int(request.form.get("statement_day", 5))))
            due_day = max(1, min(31, int(request.form.get("due_day", 25))))
            outstanding = max(0.0, float(request.form.get("current_outstanding", 0) or 0))
        except (TypeError, ValueError):
            flash("Please enter valid numeric card details.", "danger")
            return redirect(url_for("credit_cards"))
        if (
            not request.form.get("name", "").strip()
            or not request.form.get("issuer", "").strip()
            or len(last4) != 4
            or not last4.isdigit()
            or credit_limit < 0
        ):
            flash("Enter a card name, issuer, exactly four digits, and a valid limit.", "danger")
            return redirect(url_for("credit_cards"))
        card = CreditCard(
            user_id=current_user.id,
            name=request.form["name"].strip()[:120],
            issuer=request.form["issuer"].strip()[:120],
            last4=last4,
            credit_limit=credit_limit,
            billing_cycle_start_day=start_day,
            statement_day=statement_day,
            due_day=due_day,
            current_outstanding=outstanding,
        )
        db.session.add(card)
        db.session.commit()
        flash("Credit card added successfully.", "success")
        return redirect(url_for("credit_cards"))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cards = CreditCard.query.filter_by(user_id=current_user.id).order_by(CreditCard.created_at.desc()).all()
    card_views = []
    for card in cards:
        statements = card.statements.order_by(CreditCardStatement.statement_date.desc()).all()
        for statement in statements:
            refresh_statement_status(statement, now)
        current_start = datetime(now.year, now.month, 1)
        current_spend = sum(
            exp.amount
            for exp in card.expenses.filter(
                Expense.date >= current_start,
                Expense.date < now + timedelta(days=1),
                Expense.is_settlement == False,
            ).all()
        )
        card_views.append({
            "card": card,
            "statements": statements,
            "current_spend": round(current_spend, 2),
            "last_statement": statements[0] if statements else None,
        })
        if statements:
            db.session.commit()
    return render_template("credit_cards.html", card_views=card_views, now=now)


@app.route("/credit-cards/<int:card_id>/statement", methods=["POST"])
@login_required
def credit_card_statement_import(card_id):
    card = _card_owned(card_id)
    if not card:
        flash("Credit card not found.", "danger")
        return redirect(url_for("credit_cards"))
    try:
        statement_total = round(float(request.form.get("statement_total", 0)), 2)
        statement_date = datetime.strptime(request.form["statement_date"], "%Y-%m-%d")
        due_date_raw = request.form.get("due_date", "").strip()
        due_date = datetime.strptime(due_date_raw, "%Y-%m-%d") if due_date_raw else None
        if statement_total < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        flash("Enter a valid statement total and statement date.", "danger")
        return redirect(url_for("credit_cards"))
    start, end, calculated_due = cycle_dates(card, statement_date)
    due_date = due_date or calculated_due
    cycle_id = f"{card.id}:{start.strftime('%Y-%m-%d')}:{end.strftime('%Y-%m-%d')}"
    if CreditCardStatement.query.filter_by(billing_cycle_id=cycle_id).first():
        flash("That billing cycle has already been imported.", "warning")
        return redirect(url_for("credit_cards"))
    uploaded = request.files.get("statement_file")
    if not uploaded or not uploaded.filename:
        flash("Upload a CSV, Excel, PDF, or supported statement file.", "danger")
        return redirect(url_for("credit_cards"))
    try:
        parsed = parse_bank_statement(uploaded.read(), uploaded.filename)
    except Exception as exc:
        flash(f"Could not parse the credit-card statement: {exc}", "danger")
        return redirect(url_for("credit_cards"))
    if not parsed:
        flash("No transactions were detected in that statement.", "danger")
        return redirect(url_for("credit_cards"))

    statement = CreditCardStatement(
        user_id=current_user.id,
        credit_card_id=card.id,
        billing_cycle_id=cycle_id,
        cycle_start_date=start,
        cycle_end_date=end,
        statement_date=statement_date,
        statement_total=statement_total,
        due_date=due_date,
        payment_status="UNPAID",
    )
    db.session.add(statement)
    db.session.flush()
    calculated_total = 0.0
    imported = 0
    seen = set()
    for index, txn in enumerate(parsed):
        if txn.get("type") != "expense":
            continue
        try:
            txn_date = datetime.strptime(txn["date"], "%Y-%m-%d")
            raw_amount = float(txn["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        description = (txn.get("description") or "Card transaction").strip()[:200]
        category, need_want, amount, is_refund = classify_card_transaction(
            description, amount=raw_amount
        )
        fingerprint = (txn_date.date().isoformat(), description.lower(), round(amount, 2))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        transaction_id = f"cc:{card.id}:{cycle_id}:{index}:{abs(hash(fingerprint))}"
        db.session.add(
            Expense(
                user_id=current_user.id,
                category=category,
                amount=amount,
                date=txn_date,
                description=description,
                merchant=description,
                is_essential=need_want == "NEED",
                need_want_type=need_want,
                source_type="CREDIT_CARD",
                credit_card_id=card.id,
                billing_cycle_id=cycle_id,
                statement_id=statement.id,
                transaction_id=transaction_id,
                is_subscription=False,
            )
        )
        calculated_total += amount
        imported += 1
    statement.calculated_total = round(calculated_total, 2)
    statement.reconciliation_difference = round(statement_total - calculated_total, 2)
    statement.outstanding = statement_total
    card.current_outstanding = round(card.current_outstanding + statement_total, 2)
    db.session.commit()
    if abs(statement.reconciliation_difference) > 0.01:
        flash(
            f"Statement imported with a reconciliation difference of ₹{statement.reconciliation_difference:,.2f}. "
            "Review the statement breakdown.",
            "warning",
        )
    else:
        flash(f"Statement imported: {imported} transactions matched ₹{statement_total:,.2f}.", "success")
    return redirect(url_for("credit_cards"))


@app.route("/credit-cards/statement/<int:statement_id>/pay", methods=["POST"])
@login_required
def credit_card_mark_paid(statement_id):
    statement = db.session.get(CreditCardStatement, statement_id)
    if not statement or statement.user_id != current_user.id:
        flash("Statement not found.", "danger")
        return redirect(url_for("credit_cards"))
    try:
        amount = round(float(request.form.get("amount_paid", 0)), 2)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Enter a valid payment amount.", "danger")
        return redirect(url_for("credit_cards"))
    statement.amount_paid = min(statement.statement_total, (statement.amount_paid or 0) + amount)
    statement.payment_date = datetime.strptime(
        request.form.get("payment_date") or datetime.utcnow().strftime("%Y-%m-%d"), "%Y-%m-%d"
    )
    statement.payment_source = request.form.get("payment_source", "Manual payment").strip()[:120]
    refresh_statement_status(statement)
    statement.credit_card.current_outstanding = max(
        0.0, round(statement.credit_card.current_outstanding - amount, 2)
    )
    db.session.commit()
    flash("Credit-card payment recorded.", "success")
    return redirect(url_for("credit_cards"))


@app.route("/credit-cards/statement/<int:statement_id>/transactions")
@login_required
def credit_card_statement_transactions(statement_id):
    statement = db.session.get(CreditCardStatement, statement_id)
    if not statement or statement.user_id != current_user.id:
        return jsonify({"success": False, "message": "Statement not found."}), 404
    return jsonify({
        "success": True,
        "transactions": [
            {
                "date": exp.date.strftime("%d %b %Y"),
                "description": exp.description,
                "category": exp.category,
                "amount": exp.amount,
                "need_want": exp.need_want_type,
            }
            for exp in statement.transactions.order_by(Expense.date.asc()).all()
        ],
    })


# ── Income Routes ─────────────────────────────────────────────


@app.route("/add_income", methods=["GET", "POST"])
@login_required
def add_income():
    form = IncomeForm()
    if form.validate_on_submit():
        date_received = (
            datetime.combine(form.date_received.data, datetime.min.time())
            if form.date_received.data
            else datetime.now(timezone.utc).replace(tzinfo=None)
        )
        db.session.add(
            Income(
                user_id=current_user.id,
                source=form.source.data,
                amount=form.amount.data,
                date_received=date_received,
                description=form.description.data,
                is_recurring=form.is_recurring.data,
            )
        )
        db.session.commit()
        flash("Income added successfully!", "success")
        return redirect(url_for("dashboard"))

    try:
        inc_filter_days = int(request.args.get("days", 0))
        if inc_filter_days <= 0:
            inc_filter_days = None
    except (ValueError, TypeError):
        inc_filter_days = None

    income_query = Income.query.filter_by(user_id=current_user.id)
    if inc_filter_days:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=inc_filter_days
        )
        income_query = income_query.filter(Income.date_received >= since)
        inc_filter_label = (
            f"Last {inc_filter_days} day{'s' if inc_filter_days != 1 else ''}"
        )
    else:
        inc_filter_label = "All Time"

    incomes = income_query.order_by(Income.date_received.desc()).all()
    return render_template(
        "add_income.html",
        form=form,
        edit=False,
        incomes=incomes,
        inc_filter_days=inc_filter_days,
        inc_filter_label=inc_filter_label,
    )


@app.route("/edit_income/<int:id>", methods=["GET", "POST"])
@login_required
def edit_income(id):
    income = db.get_or_404(Income, id)
    if income.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("dashboard"))
    form = IncomeForm()
    if form.validate_on_submit():
        income.source = form.source.data
        income.amount = form.amount.data
        income.description = form.description.data
        income.is_recurring = form.is_recurring.data
        if form.date_received.data:
            income.date_received = datetime.combine(
                form.date_received.data, datetime.min.time()
            )
        db.session.commit()
        flash("Income updated.", "success")
        return redirect(url_for("add_income"))
    elif request.method == "GET":
        form.source.data = income.source
        form.amount.data = income.amount
        form.description.data = income.description
        form.is_recurring.data = income.is_recurring
        if income.date_received:
            form.date_received.data = income.date_received.date()
    incomes = (
        Income.query.filter_by(user_id=current_user.id)
        .order_by(Income.date_received.desc())
        .all()
    )
    return render_template(
        "add_income.html",
        form=form,
        edit=True,
        incomes=incomes,
        inc_filter_days=None,
        inc_filter_label="All Time",
    )


@app.route("/delete_income/<int:id>")
@login_required
def delete_income(id):
    income = db.get_or_404(Income, id)
    if income.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("dashboard"))
    db.session.delete(income)
    db.session.commit()
    flash("Income deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/bulk_delete_income", methods=["POST"])
@login_required
def bulk_delete_income():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    if ids:
        Income.query.filter(
            Income.id.in_(ids), Income.user_id == current_user.id
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(
            f"Deleted {len(ids)} income entr{'y' if len(ids) == 1 else 'ies'}.",
            "success",
        )
    days_raw = request.form.get("days", "")
    try:
        days = int(days_raw)
        if days <= 0:
            raise ValueError
    except (ValueError, TypeError):
        days = None
    return redirect(url_for("add_income", days=days) if days else url_for("add_income"))


@app.route("/bulk_edit_income", methods=["POST"])
@login_required
def bulk_edit_income():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    new_source = request.form.get("source", "").strip()
    if ids and new_source:
        incs = Income.query.filter(
            Income.id.in_(ids), Income.user_id == current_user.id
        ).all()
        for inc in incs:
            inc.source = new_source
        db.session.commit()
        flash(
            f"Updated source for {len(incs)} income entr{'y' if len(incs) == 1 else 'ies'}.",
            "success",
        )
    days_raw = request.form.get("days", "")
    try:
        days = int(days_raw)
        if days <= 0:
            raise ValueError
    except (ValueError, TypeError):
        days = None
    return redirect(url_for("add_income", days=days) if days else url_for("add_income"))


# ── Expense Routes ────────────────────────────────────────────


@app.route("/get_subcategories/<main_category>")
@login_required
def get_subcategories(main_category):
    if main_category in expense_categories:
        return jsonify(
            {
                "subcategories": expense_categories[main_category]["subcategories"],
                "status": "success",
            }
        )
    return jsonify({"subcategories": [], "status": "error"})


def _build_expense_form_choices(form, main_cat=None):
    form.main_category.choices = [("", "-- Select Category --")] + [
        (cat, cat) for cat in expense_categories.keys()
    ]
    if main_cat and main_cat in expense_categories:
        subcats = expense_categories[main_cat]["subcategories"]
        form.sub_category.choices = [("", "-- Select Sub Category --")] + [
            (s, s) for s in subcats
        ]
    else:
        form.sub_category.choices = [("", "-- Select Sub Category First --")]


@app.route("/add_expense", methods=["GET", "POST"])
@login_required
def add_expense():
    form = ExpenseForm()
    main_cat = request.form.get("main_category", "") if request.method == "POST" else ""
    _build_expense_form_choices(form, main_cat or None)

    if request.method == "POST" and form.validate_on_submit():
        category = (
            form.custom_category.data
            if form.sub_category.data == "Other (User Input)"
            and form.custom_category.data
            else form.sub_category.data
        )
        is_essential = classify_essential(
            form.main_category.data, form.sub_category.data, form.custom_category.data
        )
        exp_date = (
            datetime.combine(form.date.data, datetime.min.time())
            if form.date.data
            else datetime.now(timezone.utc).replace(tzinfo=None)
        )
        sub_start = (
            datetime.combine(form.sub_start_date.data, datetime.min.time())
            if form.is_subscription.data and form.sub_start_date.data
            else None
        )
        sub_end = (
            datetime.combine(form.sub_end_date.data, datetime.min.time())
            if form.is_subscription.data and form.sub_end_date.data
            else None
        )
        db.session.add(
            Expense(
                user_id=current_user.id,
                category=category,
                amount=form.amount.data,
                date=exp_date,
                description=form.description.data,
                is_essential=is_essential,
                is_subscription=form.is_subscription.data,
                sub_start_date=sub_start,
                sub_end_date=sub_end,
                source_type="MANUAL",
            )
        )
        db.session.commit()
        flash("Expense added successfully!", "success")
        return redirect(url_for("dashboard"))
    elif request.method == "POST":
        flash("Please check the form and try again.", "danger")

    try:
        exp_filter_days = int(request.args.get("days", 0))
        if exp_filter_days <= 0:
            exp_filter_days = None
    except (ValueError, TypeError):
        exp_filter_days = None

    only_uncategorized = request.args.get("uncategorized") == "1"
    source_filter = request.args.get("source", "all").lower()

    expense_query = Expense.query.filter_by(user_id=current_user.id)
    if exp_filter_days:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=exp_filter_days
        )
        expense_query = expense_query.filter(Expense.date >= since)
        exp_filter_label = (
            f"Last {exp_filter_days} day{'s' if exp_filter_days != 1 else ''}"
        )
    else:
        exp_filter_label = "All Time"

    if only_uncategorized:
        expense_query = expense_query.filter(Expense.category == "Uncategorized")
        exp_filter_label = "Uncategorized"
    if source_filter in ("bank", "credit_card", "manual"):
        if source_filter == "credit_card":
            expense_query = expense_query.filter(Expense.source_type == "CREDIT_CARD")
        elif source_filter == "bank":
            expense_query = expense_query.filter(Expense.source_type == "BANK")
        else:
            expense_query = expense_query.filter(
                Expense.source_type.notin_(("BANK", "CREDIT_CARD"))
            )

    expenses = expense_query.order_by(Expense.date.desc()).all()
    return render_template(
        "add_expense.html",
        form=form,
        edit=False,
        expenses=expenses,
        exp_filter_days=exp_filter_days,
        exp_filter_label=exp_filter_label,
        only_uncategorized=only_uncategorized,
        source_filter=source_filter,
        expense_categories=expense_categories,
    )


@app.route("/edit_expense/<int:id>", methods=["GET", "POST"])
@login_required
def edit_expense(id):
    expense = db.get_or_404(Expense, id)
    if expense.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("dashboard"))

    form = ExpenseForm()
    main_cat = (
        request.form.get("main_category", "") if request.method == "POST" else None
    )
    _build_expense_form_choices(form, main_cat)

    if form.validate_on_submit():
        expense.category = (
            form.custom_category.data
            if form.sub_category.data == "Other (User Input)"
            and form.custom_category.data
            else form.sub_category.data
        )
        expense.amount = form.amount.data
        expense.description = form.description.data
        expense.is_subscription = form.is_subscription.data
        expense.is_essential = classify_essential(
            form.main_category.data, form.sub_category.data, form.custom_category.data
        )
        if form.date.data:
            expense.date = datetime.combine(form.date.data, datetime.min.time())
        if form.is_subscription.data:
            expense.sub_start_date = (
                datetime.combine(form.sub_start_date.data, datetime.min.time())
                if form.sub_start_date.data
                else None
            )
            expense.sub_end_date = (
                datetime.combine(form.sub_end_date.data, datetime.min.time())
                if form.sub_end_date.data
                else None
            )
        else:
            expense.sub_start_date = None
            expense.sub_end_date = None
        db.session.commit()
        flash("Expense updated.", "success")
        return redirect(url_for("add_expense"))

    elif request.method == "GET":
        main_cat = next(
            (
                cat
                for cat, data in expense_categories.items()
                if expense.category in data["subcategories"]
            ),
            None,
        )
        if main_cat:
            subcats = expense_categories[main_cat]["subcategories"]
            form.sub_category.choices = [("", "-- Select Sub Category --")] + [
                (s, s) for s in subcats
            ]
            form.main_category.data = main_cat
            form.sub_category.data = expense.category
        else:
            form.sub_category.choices = [
                ("", "-- Select Sub Category --"),
                ("Other (User Input)", "Other (User Input)"),
            ]
            form.main_category.data = "Other"
            form.sub_category.data = "Other (User Input)"
            form.custom_category.data = expense.category
        form.main_category.choices = [("", "-- Select Category --")] + [
            (cat, cat) for cat in expense_categories.keys()
        ]
        form.amount.data = expense.amount
        form.description.data = expense.description
        form.is_subscription.data = expense.is_subscription
        if expense.date:
            form.date.data = expense.date.date()
        if expense.sub_start_date:
            form.sub_start_date.data = expense.sub_start_date.date()
        if expense.sub_end_date:
            form.sub_end_date.data = expense.sub_end_date.date()

    expenses = (
        Expense.query.filter_by(user_id=current_user.id)
        .order_by(Expense.date.desc())
        .all()
    )
    return render_template(
        "add_expense.html",
        form=form,
        edit=True,
        expenses=expenses,
        only_uncategorized=False,
        source_filter="all",
        expense_categories=expense_categories,
    )


@app.route("/delete_expense/<int:id>")
@login_required
def delete_expense(id):
    expense = db.get_or_404(Expense, id)
    if expense.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("dashboard"))
    db.session.delete(expense)
    db.session.commit()
    flash("Expense deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/bulk_delete_expenses", methods=["POST"])
@login_required
def bulk_delete_expenses():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    if ids:
        Expense.query.filter(
            Expense.id.in_(ids), Expense.user_id == current_user.id
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(f"Deleted {len(ids)} expense{'s' if len(ids) != 1 else ''}.", "success")
    days_raw = request.form.get("days", "")
    try:
        days = int(days_raw)
        if days <= 0:
            raise ValueError
    except (ValueError, TypeError):
        days = None
    return redirect(
        url_for("add_expense", days=days) if days else url_for("add_expense")
    )


@app.route("/bulk_edit_expenses", methods=["POST"])
@login_required
def bulk_edit_expenses():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    new_main = request.form.get("main_category", "").strip()
    new_sub = request.form.get("sub_category", "").strip()
    if ids and new_main and new_sub:
        is_essential = classify_essential(new_main, new_sub)
        exps = Expense.query.filter(
            Expense.id.in_(ids), Expense.user_id == current_user.id
        ).all()
        for exp in exps:
            exp.category = new_sub
            exp.is_essential = is_essential
        db.session.commit()
        flash(
            f"Updated category for {len(exps)} expense{'s' if len(exps) != 1 else ''}.",
            "success",
        )
    days_raw = request.form.get("days", "")
    try:
        days = int(days_raw)
        if days <= 0:
            raise ValueError
    except (ValueError, TypeError):
        days = None
    return redirect(
        url_for("add_expense", days=days) if days else url_for("add_expense")
    )


# ── Subscriptions ─────────────────────────────────────────────


@app.route("/subscriptions")
@login_required
def subscriptions():
    subs = detect_subscriptions(current_user.id)
    total_cost = sum(s["avg_amount"] for s in subs)
    for sub in subs:
        exps = sub.get("expenses", [])
        if exps:
            latest = max(exps, key=lambda e: e.date)
            sub["sub_start_date"] = latest.sub_start_date
            sub["sub_end_date"] = latest.sub_end_date
            sub["expense_id"] = latest.id
        else:
            sub["sub_start_date"] = sub["sub_end_date"] = sub["expense_id"] = None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return render_template(
        "subscriptions.html", subscriptions=subs, total_cost=total_cost, now=now
    )


@app.route("/remove_expired_subscription/<int:id>")
@login_required
def remove_expired_subscription(id):
    expense = db.get_or_404(Expense, id)
    if expense.user_id != current_user.id:
        flash("Unauthorized.", "danger")
        return redirect(url_for("subscriptions"))
    db.session.delete(expense)
    db.session.commit()
    flash("Subscription removed.", "success")
    return redirect(url_for("subscriptions"))


# ── Goals ─────────────────────────────────────────────────────


@app.route("/goals")
@login_required
def goals():
    if normalize_goal_priorities(current_user.id):
        db.session.commit()
    goals = (
        Goal.query.filter_by(user_id=current_user.id)
        .order_by(Goal.created_at.desc())
        .all()
    )
    return render_template("goals.html", goals=goals)


@app.route("/add_goal", methods=["GET", "POST"])
@login_required
def add_goal():
    form = GoalForm()
    if form.validate_on_submit():
        new_goal = Goal(
            user_id=current_user.id,
            name=form.name.data,
            target_amount=form.target_amount.data,
            monthly_savings=form.monthly_savings.data,
            target_date=form.target_date.data,
        )
        db.session.add(new_goal)
        assign_goal_priority(current_user.id, new_goal, form.priority.data)
        db.session.commit()
        flash("Goal created successfully!", "success")
        return redirect(url_for("goals"))
    goals = (
        Goal.query.filter_by(user_id=current_user.id)
        .order_by(Goal.created_at.desc())
        .all()
    )
    return render_template("add_goal.html", form=form, goals=goals)


@app.route("/goal/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_goal(id):
    goal = db.get_or_404(Goal, id)
    if goal.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("goals"))
    form = GoalForm()
    if form.validate_on_submit():
        goal.name = form.name.data
        goal.target_amount = form.target_amount.data
        goal.monthly_savings = form.monthly_savings.data
        goal.target_date = form.target_date.data
        assign_goal_priority(current_user.id, goal, form.priority.data)
        db.session.commit()
        flash("Goal updated successfully!", "success")
        return redirect(url_for("goal_detail", id=goal.id))
    elif request.method == "GET":
        form.name.data = goal.name
        form.target_amount.data = goal.target_amount
        form.monthly_savings.data = goal.monthly_savings
        form.target_date.data = goal.target_date
        form.priority.data = str(goal.priority)
    return render_template("edit_goal.html", form=form, goal=goal)


@app.route("/goal/<int:id>", methods=["GET", "POST"])
@login_required
def goal_detail(id):
    goal = db.get_or_404(Goal, id)
    if goal.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("goals"))
    form = SavingsUpdateForm()
    if form.validate_on_submit():
        additional_savings = form.saved_amount.data
        goal.saved_amount = goal.saved_amount + additional_savings
        db.session.commit()
        flash(
            f"Added ₹{additional_savings:,.0f} to your savings! Total saved: ₹{goal.saved_amount:,.0f}",
            "success",
        )
        return redirect(url_for("goal_detail", id=id))
    suggestions = get_spending_suggestions(current_user.id, goal)
    milestones = []
    if goal.monthly_savings > 0:
        for month in range(1, min(13, int(goal.estimated_months) + 1)):
            milestone_date = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) + timedelta(days=30 * month)
            milestone_amount = goal.saved_amount + (goal.monthly_savings * month)
            milestones.append(
                {
                    "month": month,
                    "date": milestone_date,
                    "amount": min(milestone_amount, goal.target_amount),
                }
            )
    return render_template(
        "goal_detail.html",
        goal=goal,
        form=form,
        suggestions=suggestions,
        milestones=milestones,
    )


@app.route("/goal/<int:id>/delete")
@login_required
def delete_goal(id):
    goal = db.get_or_404(Goal, id)
    if goal.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("goals"))
    db.session.delete(goal)
    db.session.commit()
    flash("Goal deleted.", "success")
    return redirect(url_for("goals"))


@app.route("/what_if/<int:id>", methods=["POST"])
@login_required
def what_if(id):
    goal = db.get_or_404(Goal, id)
    if goal.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    new_monthly_savings = data.get("monthly_savings", goal.monthly_savings)
    spending_reduction = data.get("spending_reduction", 0)
    total_monthly = new_monthly_savings + spending_reduction
    if total_monthly <= 0:
        return jsonify(
            {"months": float("inf"), "date": None, "progress": goal.progress_percentage}
        )
    months = goal.remaining_amount / total_monthly
    estimated_date = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        days=30 * months
    )
    return jsonify(
        {
            "months": round(months, 1),
            "date": estimated_date.strftime("%d %b %Y"),
            "progress": goal.progress_percentage,
        }
    )


# ── Analysis + Charts ─────────────────────────────────────────


@app.route("/analysis")
@login_required
def analysis():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dr = request.args.get("dr", "this_month")
    custom_from = request.args.get("from", "")
    custom_to = request.args.get("to", "")

    if dr == "prev_month":
        first_this = datetime(now.year, now.month, 1)
        date_to = first_this - timedelta(seconds=1)
        date_from = datetime(date_to.year, date_to.month, 1)
        range_label = date_from.strftime("%B %Y")
    elif dr == "2months":
        date_from = datetime(
            (d := datetime(now.year, now.month, 1) - timedelta(days=60)).year,
            d.month,
            1,
        )
        date_to = now
        range_label = "Past 2 Months"
    elif dr == "3months":
        date_from = datetime(
            (d := datetime(now.year, now.month, 1) - timedelta(days=90)).year,
            d.month,
            1,
        )
        date_to = now
        range_label = "Past 3 Months"
    elif dr == "6months":
        date_from = datetime(
            (d := datetime(now.year, now.month, 1) - timedelta(days=180)).year,
            d.month,
            1,
        )
        date_to = now
        range_label = "Past 6 Months"
    elif dr == "all_time":
        date_from = datetime(2000, 1, 1)
        date_to = now
        range_label = "All Time"
    elif dr == "custom" and custom_from and custom_to:
        try:
            date_from = datetime.strptime(custom_from, "%Y-%m-%d")
            date_to = datetime.strptime(custom_to, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
            range_label = (
                f"{date_from.strftime('%d %b %Y')} – {date_to.strftime('%d %b %Y')}"
            )
        except ValueError:
            date_from = datetime(now.year, now.month, 1)
            date_to = now
            range_label = "This Month"
            dr = "this_month"
    else:
        dr = "this_month"
        date_from = datetime(now.year, now.month, 1)
        date_to = now
        range_label = now.strftime("%B %Y")

    expenses_range = Expense.query.filter(
        Expense.user_id == current_user.id,
        Expense.date >= date_from,
        Expense.date <= date_to,
    ).all()
    regular_expenses_range = [
        e for e in expenses_range
        if e.source_type != "CREDIT_CARD" and not e.is_settlement
    ]
    card_statements = CreditCardStatement.query.filter(
        CreditCardStatement.user_id == current_user.id,
        CreditCardStatement.statement_date >= date_from,
        CreditCardStatement.statement_date <= date_to,
    ).all()
    total_income = sum(
        i.amount
        for i in Income.query.filter(
            Income.user_id == current_user.id,
            Income.date_received >= date_from,
            Income.date_received <= date_to,
        ).all()
    )
    total_spent = sum(e.amount for e in regular_expenses_range) + sum(
        s.statement_total for s in card_statements
    )
    card_needs = sum(
        e.amount for s in card_statements for e in s.transactions.all()
        if e.need_want_type != "WANT"
    )
    card_wants = sum(
        e.amount for s in card_statements for e in s.transactions.all()
        if e.need_want_type == "WANT"
    )
    essential = sum(e.amount for e in regular_expenses_range if e.is_essential) + card_needs
    non_essential = sum(e.amount for e in regular_expenses_range if not e.is_essential) + card_wants
    categories = {}
    for e in regular_expenses_range:
        categories[e.category] = categories.get(e.category, 0) + e.amount
    for statement in card_statements:
        for e in statement.transactions.all():
            categories[e.category] = categories.get(e.category, 0) + e.amount
    days_in_range = max((date_to - date_from).days + 1, 1)
    burn_rate = total_spent / days_in_range
    has_data = bool(expenses_range or card_statements) or total_income > 0

    return render_template(
        "analysis.html",
        categories=categories,
        total_income=total_income,
        total_spent=total_spent,
        essential=essential,
        non_essential=non_essential,
        burn_rate=burn_rate,
        now=now,
        has_data=has_data,
        dr=dr,
        range_label=range_label,
        custom_from=custom_from,
        custom_to=custom_to,
    )


@app.route("/analysis/chart/dist")
@login_required
def analysis_chart_dist():
    import base64

    dark_mode = request.cookies.get("darkMode") == "true"
    categories, _, _, _ = get_analysis_data(current_user.id, Expense, Income)
    result = chart_expense_distribution(categories, dark_mode=dark_mode)
    if not result:
        return ("", 204)
    return chart_png_response(io.BytesIO(base64.b64decode(result)))


@app.route("/analysis/chart/cats")
@login_required
def analysis_chart_cats():
    import base64

    dark_mode = request.cookies.get("darkMode") == "true"
    categories, _, _, _ = get_analysis_data(current_user.id, Expense, Income)
    result = chart_category_breakdown(categories, dark_mode=dark_mode)
    if not result:
        return ("", 204)
    return chart_png_response(io.BytesIO(base64.b64decode(result)))


@app.route("/analysis/chart/trend")
@login_required
def analysis_chart_trend():
    import base64

    dark_mode = request.cookies.get("darkMode") == "true"
    _, monthly_spending_ordered, _, _ = get_analysis_data(
        current_user.id, Expense, Income
    )
    result = chart_monthly_trend(monthly_spending_ordered, dark_mode=dark_mode)
    if not result:
        return ("", 204)
    return chart_png_response(io.BytesIO(base64.b64decode(result)))


@app.route("/analysis/chart/inc_exp")
@login_required
def analysis_chart_inc_exp():
    import base64

    dark_mode = request.cookies.get("darkMode") == "true"
    _, _, monthly_income, monthly_expense_all = get_analysis_data(
        current_user.id, Expense, Income
    )
    result = chart_income_vs_expense(
        monthly_income, monthly_expense_all, dark_mode=dark_mode
    )
    if not result:
        return ("", 204)
    return chart_png_response(io.BytesIO(base64.b64decode(result)))


# ── Email Import ──────────────────────────────────────────────


@app.route("/email-import")
@login_required
def email_import():
    return render_template("email_import.html", imap_connected="imap_config" in session)


@app.route("/email-import/connect", methods=["POST"])
@login_required
def email_import_connect():
    data = request.get_json(force=True)
    host = data.get("host", "").strip()
    port = int(data.get("port", 993))
    email_addr = data.get("email", "").strip()
    password = data.get("password", "").strip()
    if not all([host, email_addr, password]):
        return jsonify({"success": False, "message": "All fields are required."})
    try:
        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
        mail.login(email_addr, password)
        mail.logout()
        session["imap_config"] = {
            "host": host,
            "port": port,
            "email": email_addr,
            "password": password,
        }
        return jsonify(
            {"success": True, "message": f"Connected to {host} successfully!"}
        )
    except imaplib.IMAP4.error as e:
        return jsonify(
            {
                "success": False,
                "message": f"Authentication failed — check your email/password or App Password. ({e})",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": f"Connection failed: {e}"})


@app.route("/email-import/disconnect", methods=["POST"])
@login_required
def email_import_disconnect():
    session.pop("imap_config", None)
    return jsonify({"success": True})


@app.route("/email-import/scan", methods=["POST"])
@login_required
def email_import_scan():
    cfg = session.get("imap_config")
    if not cfg:
        return jsonify(
            {"success": False, "message": "Not connected to any email account."}
        )
    days = int(request.get_json(force=True).get("days", 30))
    try:
        transactions = scan_imap_emails(
            cfg["host"], cfg["port"], cfg["email"], cfg["password"], days=days
        )
        return jsonify(
            {"success": True, "transactions": transactions, "count": len(transactions)}
        )
    except imaplib.IMAP4.error as e:
        session.pop("imap_config", None)
        return jsonify(
            {
                "success": False,
                "message": f"Email session expired — please reconnect. ({e})",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/email-import/import", methods=["POST"])
@login_required
def email_import_do():
    items = request.get_json(force=True).get("transactions", [])
    imported_count = 0
    for txn in items:
        try:
            txn_date = datetime.strptime(txn["date"], "%Y-%m-%d")
            amount = float(txn["amount"])
            desc = txn.get("description", "")[:200]
            if txn.get("type") == "income":
                db.session.add(
                    Income(
                        user_id=current_user.id,
                        source=txn.get("sub_cat", "Email Import"),
                        amount=amount,
                        date_received=txn_date,
                        description=desc,
                    )
                )
            else:
                db.session.add(
                    Expense(
                        user_id=current_user.id,
                        category="Uncategorized",
                        amount=amount,
                        date=txn_date,
                        description=desc,
                        is_essential=False,
                        is_subscription=False,
                        source_type="MANUAL",
                    )
                )
            imported_count += 1
        except Exception:
            continue
    db.session.commit()
    return jsonify({"success": True, "imported": imported_count})


# ── Bank Statement Import ──────────────────────────────────────


@app.route("/bank-statement/upload", methods=["POST"])
@login_required
def bank_statement_upload():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded."})
    f = request.files["file"]
    filename = f.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "xlsx", "xls", "csv", "zip"):
        return jsonify(
            {
                "success": False,
                "message": "Unsupported file type. Please upload a PDF, Excel (.xlsx/.xls), CSV, or ZIP file.",
            }
        )
    try:
        file_bytes = f.read()
        if len(file_bytes) > 20 * 1024 * 1024:
            return jsonify({"success": False, "message": "File too large (max 20 MB)."})
        password = request.form.get("password", "").strip() or None

        if ext == "zip":
            SUPPORTED = {"pdf", "xlsx", "xls", "csv"}
            try:
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                    entries = [
                        n
                        for n in zf.namelist()
                        if not n.startswith("__MACOSX")
                        and not n.endswith("/")
                        and n.rsplit(".", 1)[-1].lower() in SUPPORTED
                    ]
                    if not entries:
                        return jsonify(
                            {
                                "success": False,
                                "message": "No supported statement file found inside the ZIP.",
                            }
                        )
                    all_txns, parsed_files, needs_pw = [], [], False
                    for entry in entries:
                        inner_bytes = zf.read(entry)
                        inner_name = entry.split("/")[-1]
                        try:
                            txns = parse_bank_statement(
                                inner_bytes, inner_name, password=password
                            )
                            if txns:
                                all_txns.extend(txns)
                                parsed_files.append(inner_name)
                        except ValueError as ve:
                            if "password" in str(ve).lower():
                                needs_pw = True
                        except Exception:
                            continue
                    if not all_txns:
                        if needs_pw:
                            return jsonify(
                                {
                                    "success": False,
                                    "needs_password": True,
                                    "message": "One or more files inside the ZIP are password-protected.",
                                }
                            )
                        return jsonify(
                            {
                                "success": False,
                                "message": "No transactions could be detected in any file inside the ZIP.",
                            }
                        )
                    seen, unique = set(), []
                    for t in all_txns:
                        key = (t["date"], t["amount"], t["type"])
                        if key not in seen:
                            seen.add(key)
                            unique.append(t)
                    return jsonify(
                        {
                            "success": True,
                            "transactions": unique,
                            "count": len(unique),
                            "source": f"ZIP ({', '.join(parsed_files)})",
                        }
                    )
            except zipfile.BadZipFile:
                return jsonify(
                    {
                        "success": False,
                        "message": "The uploaded file is not a valid ZIP archive.",
                    }
                )

        try:
            txns = parse_bank_statement(file_bytes, filename, password=password)
        except ValueError as ve:
            msg = str(ve)
            if "password" in msg.lower():
                return jsonify(
                    {"success": False, "needs_password": True, "message": msg}
                )
            return jsonify({"success": False, "message": msg})
        if not txns:
            return jsonify(
                {
                    "success": False,
                    "message": "No transactions could be detected. Make sure the file is a standard bank statement with Date, Description, and Amount columns.",
                }
            )
        return jsonify(
            {
                "success": True,
                "transactions": txns,
                "count": len(txns),
                "source": filename,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": f"Parsing failed: {str(e)}"})


@app.route("/bank-statement/import", methods=["POST"])
@login_required
def bank_statement_import():
    items = request.get_json(force=True).get("transactions", [])
    imported_count = 0
    skipped_count = 0
    for txn in items:
        try:
            txn_date = datetime.strptime(txn["date"], "%Y-%m-%d")
            amount = float(txn["amount"])
            desc = txn.get("description", "")[:200]
            txn_type = txn.get("type", "expense")
            if txn_type == "income":
                if Income.query.filter_by(
                    user_id=current_user.id,
                    source="Bank Import",
                    amount=amount,
                    date_received=txn_date,
                    description=desc,
                ).first():
                    skipped_count += 1
                    continue
                db.session.add(
                    Income(
                        user_id=current_user.id,
                        source="Bank Import",
                        amount=amount,
                        date_received=txn_date,
                        description=desc,
                    )
                )
            else:
                if Expense.query.filter_by(
                    user_id=current_user.id,
                    amount=amount,
                    date=txn_date,
                    description=desc,
                ).first():
                    skipped_count += 1
                    continue
                cat, essential, sub = auto_categorize_transaction(desc)
                db.session.add(
                    Expense(
                        user_id=current_user.id,
                        category=cat,
                        amount=amount,
                        date=txn_date,
                        description=desc,
                        is_essential=essential,
                        is_subscription=sub,
                        source_type="BANK",
                    )
                )
            imported_count += 1
        except Exception:
            continue
    db.session.commit()
    return jsonify(
        {"success": True, "imported": imported_count, "skipped": skipped_count}
    )


@app.route("/retro_categorize", methods=["POST"])
@login_required
def retro_categorize():
    expenses = Expense.query.filter_by(
        user_id=current_user.id, category="Uncategorized"
    ).all()
    updated = 0
    for exp in expenses:
        cat, essential, sub = auto_categorize_transaction(exp.description or "")
        if cat != "Uncategorized":
            exp.category = cat
            exp.is_essential = essential
            exp.is_subscription = sub
            updated += 1
    db.session.commit()
    remaining = Expense.query.filter_by(
        user_id=current_user.id, category="Uncategorized"
    ).count()
    flash(
        f"Auto-categorized {updated} expense{'s' if updated != 1 else ''}. "
        f"{remaining} still need{'s' if remaining == 1 else ''} manual review.",
        "success" if remaining == 0 else "warning",
    )
    return redirect(url_for("add_expense"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
