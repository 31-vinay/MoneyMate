from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta, timezone

db = SQLAlchemy()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    mpin = db.Column(db.String(6), nullable=True)
    has_seen_tutorial = db.Column(db.Boolean, default=False, nullable=False)
    last_monthly_reset = db.Column(db.DateTime, nullable=True)
    notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    savings_balance = db.Column(db.Float, default=0.0, nullable=False)
    goals_wants_pct = db.Column(db.Float, default=30.0, nullable=False)
    incomes = db.relationship("Income", backref="user", lazy=True)
    expenses = db.relationship("Expense", backref="user", lazy=True)
    goals = db.relationship("Goal", backref="user", lazy=True)


class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    source = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date_received = db.Column(db.DateTime, default=_now)
    created_at = db.Column(db.DateTime, default=_now)
    description = db.Column(db.String(200))
    is_recurring = db.Column(db.Boolean, default=False)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=_now)
    created_at = db.Column(db.DateTime, default=_now)
    description = db.Column(db.String(200))
    is_essential = db.Column(db.Boolean, default=False)
    is_subscription = db.Column(db.Boolean, default=False)
    sub_start_date = db.Column(db.DateTime, nullable=True)
    sub_end_date = db.Column(db.DateTime, nullable=True)
    sub_expired_notified = db.Column(db.Boolean, default=False)


class Goal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    target_amount = db.Column(db.Float, nullable=False)
    saved_amount = db.Column(db.Float, default=0.0)
    monthly_savings = db.Column(db.Float, default=0.0)
    target_date = db.Column(db.DateTime, nullable=True)
    priority = db.Column(db.String(10), default="medium", nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    @property
    def remaining_amount(self):
        return max(0, self.target_amount - self.saved_amount)

    @property
    def progress_percentage(self):
        if self.target_amount == 0:
            return 0
        return min(100, (self.saved_amount / self.target_amount) * 100)

    @property
    def estimated_months(self):
        if self.monthly_savings <= 0:
            return float("inf")
        return self.remaining_amount / self.monthly_savings

    @property
    def estimated_date(self):
        if self.estimated_months == float("inf"):
            return None
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            days=30 * self.estimated_months
        )
