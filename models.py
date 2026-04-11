from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(256), nullable=False)
    mpin = db.Column(db.String(6), nullable=True)
    has_seen_tutorial = db.Column(db.Boolean, default=False, nullable=False)
    last_monthly_reset = db.Column(db.DateTime, nullable=True)
    notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    savings_balance = db.Column(db.Float, default=0.0, nullable=False)
    goals_wants_pct = db.Column(db.Float, default=30.0, nullable=False)
    incomes = db.relationship("Income", backref="user", lazy="dynamic")
    expenses = db.relationship("Expense", backref="user", lazy="dynamic")
    goals = db.relationship("Goal", backref="user", lazy="dynamic")

    def set_password(self, raw_password):
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        if self.password.startswith("pbkdf2:") or self.password.startswith("scrypt:"):
            return check_password_hash(self.password, raw_password)
        if self.password == raw_password:
            self.set_password(raw_password)
            return True
        return False


class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )
    source = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date_received = db.Column(db.DateTime, default=_now, index=True)
    created_at = db.Column(db.DateTime, default=_now)
    description = db.Column(db.String(200))
    is_recurring = db.Column(db.Boolean, default=False)

    __table_args__ = (db.Index("ix_income_user_date", "user_id", "date_received"),)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )
    category = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=_now, index=True)
    created_at = db.Column(db.DateTime, default=_now)
    description = db.Column(db.String(200))
    is_essential = db.Column(db.Boolean, default=False)
    is_subscription = db.Column(db.Boolean, default=False, index=True)
    sub_start_date = db.Column(db.DateTime, nullable=True)
    sub_end_date = db.Column(db.DateTime, nullable=True)
    sub_expired_notified = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.Index("ix_expense_user_date", "user_id", "date"),
        db.Index("ix_expense_user_sub", "user_id", "is_subscription"),
    )


class Goal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )
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
