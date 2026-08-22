from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

from categorizer import auto_categorize_transaction
from models import CreditCardStatement, Expense, db


WANT_CATEGORIES = {
    "Food Delivery",
    "Dining Out",
    "Fast Food",
    "Coffee Shops",
    "Snacks",
    "Meal Kits",
    "Specialty Foods",
    "Clothing",
    "Shoes",
    "Beauty Products",
    "Gym Membership",
    "Salon Services",
    "Spa",
    "Movies",
    "Concerts",
    "Gaming",
    "Streaming Subscriptions",
    "Hobbies",
    "Books & Magazines",
    "Theme Parks",
    "Events & Shows",
}


def classify_card_transaction(description, category=None, amount=0):
    category = category or auto_categorize_transaction(description or "")[0]
    need_want = "WANT" if category in WANT_CATEGORIES else "NEED"
    text = (description or "").lower()
    is_refund = any(word in text for word in ("refund", "reversal", "cashback", "credit adjustment"))
    if is_refund and amount > 0:
        amount = -abs(amount)
    return category, need_want, round(float(amount), 2), is_refund


def _date_for_day(year, month, day):
    return datetime(year, month, min(max(1, int(day)), monthrange(year, month)[1]))


def cycle_dates(card, statement_date):
    statement_date = statement_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = statement_date
    if end.month == 1:
        previous_month = datetime(end.year - 1, 12, 1)
    else:
        previous_month = datetime(end.year, end.month - 1, 1)
    start = _date_for_day(previous_month.year, previous_month.month, card.billing_cycle_start_day)
    due_month = statement_date.year + (1 if statement_date.month == 12 else 0)
    due_month_number = 1 if statement_date.month == 12 else statement_date.month + 1
    due = _date_for_day(due_month, due_month_number, card.due_day)
    return start, end, due


def refresh_statement_status(statement, now=None):
    now = now or datetime.utcnow()
    statement.amount_paid = round(max(0.0, statement.amount_paid or 0.0), 2)
    statement.outstanding = round(max(0.0, statement.statement_total - statement.amount_paid), 2)
    if statement.amount_paid >= statement.statement_total:
        statement.payment_status = "PAID"
    elif statement.amount_paid > 0:
        statement.payment_status = "PARTIALLY_PAID"
    elif now > statement.due_date and statement.outstanding > 0:
        statement.payment_status = "OVERDUE"
    elif statement.payment_status not in ("UNVERIFIED", "UNPAID"):
        statement.payment_status = "UNPAID"
    elif statement.payment_status == "UNVERIFIED":
        statement.payment_status = "UNPAID"
    return statement


def statement_month_data(user_id, month_start, month_end):
    statements = CreditCardStatement.query.filter(
        CreditCardStatement.user_id == user_id,
        CreditCardStatement.statement_date >= month_start,
        CreditCardStatement.statement_date < month_end,
    ).all()
    total = sum(s.statement_total for s in statements)
    categories = {}
    needs = wants = 0.0
    for statement in statements:
        for expense in statement.transactions.all():
            amount = expense.amount
            categories[expense.category] = categories.get(expense.category, 0.0) + amount
            if expense.need_want_type == "WANT":
                wants += amount
            else:
                needs += amount
    return {
        "total": round(total, 2),
        "needs": round(needs, 2),
        "wants": round(wants, 2),
        "categories": categories,
        "statements": statements,
    }


def possible_card_payment_matches(user_id, description, amount, payment_date):
    normalized = (description or "").lower()
    candidates = CreditCardStatement.query.filter(
        CreditCardStatement.user_id == user_id,
        CreditCardStatement.payment_status.in_(("UNPAID", "PARTIALLY_PAID", "OVERDUE")),
    ).all()
    matches = []
    for statement in candidates:
        card = statement.credit_card
        issuer_hit = card.issuer.lower() in normalized or card.name.lower() in normalized
        last4_hit = card.last4 in normalized
        keyword_hit = any(
            word in normalized
            for word in ("credit card", "card payment", "cc payment", "credit card bill", "card bill", "cc bill")
        )
        outstanding = statement.outstanding
        amount_hit = abs(float(amount) - outstanding) <= 0.01
        days_from_due = abs((payment_date - statement.due_date).days)
        if amount_hit and (issuer_hit or last4_hit or keyword_hit):
            matches.append({
                "statement": statement,
                "confidence": 3 if (issuer_hit or last4_hit) and days_from_due <= 45 else 2,
            })
    return sorted(matches, key=lambda item: item["confidence"], reverse=True)