import calendar
import copy
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func


def get_expenses_for_month(user_id, month_start, month_end):
    """Return recorded expenses plus any missing active subscription occurrence."""
    from models import Expense

    expenses = Expense.query.filter(
        Expense.user_id == user_id,
        Expense.date >= month_start,
        Expense.date < month_end,
    ).all()

    subscriptions = Expense.query.filter(
        Expense.user_id == user_id,
        Expense.is_subscription == True,
    ).all()
    series = defaultdict(list)
    for expense in subscriptions:
        key = (
            expense.category.strip().lower(),
            expense.description.strip().lower() if expense.description else "",
            expense.sub_start_date,
            expense.sub_end_date,
        )
        series[key].append(expense)

    month_days = calendar.monthrange(month_start.year, month_start.month)[1]
    for records in series.values():
        latest = max(records, key=lambda expense: (expense.date, expense.id))
        start_date = latest.sub_start_date or latest.date
        end_date = latest.sub_end_date
        if start_date >= month_end or (end_date and end_date < month_start):
            continue

        has_recorded_occurrence = any(
            month_start <= expense.date < month_end for expense in records
        )
        if has_recorded_occurrence:
            continue

        occurrence = copy.copy(latest)
        occurrence_date = datetime(
            month_start.year,
            month_start.month,
            min(start_date.day, month_days),
        )
        if end_date and occurrence_date > end_date:
            occurrence_date = end_date
        occurrence.date = occurrence_date
        expenses.append(occurrence)

    return expenses


def detect_subscriptions(user_id, months_back=3):
    from models import Expense

    since_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=30 * months_back
    )
    expenses = Expense.query.filter(
        Expense.user_id == user_id, Expense.date >= since_date
    ).all()

    groups = defaultdict(list)
    for exp in expenses:
        key = (
            exp.category.strip().lower(),
            exp.description.strip().lower() if exp.description else "",
        )
        groups[key].append(exp)

    seen_keys = set()
    subscriptions = []

    for exp in expenses:
        if exp.is_subscription:
            key = (
                exp.category.strip().lower(),
                exp.description.strip().lower() if exp.description else "",
            )
            if key not in seen_keys:
                seen_keys.add(key)
                items = groups[key]
                amounts = [i.amount for i in items]
                avg_amount = sum(amounts) / len(amounts)
                subscriptions.append(
                    {
                        "category": exp.category.strip(),
                        "description": exp.description or "No description",
                        "avg_amount": avg_amount,
                        "frequency": len(items),
                        "last_date": max(i.date for i in items),
                        "expenses": items,
                    }
                )

    for (cat, desc), items in groups.items():
        key = (cat, desc)
        if key in seen_keys:
            continue
        if len(items) >= 2:
            amounts = [i.amount for i in items]
            avg_amount = sum(amounts) / len(amounts)
            if all(abs(a - avg_amount) <= avg_amount * 0.1 for a in amounts):
                seen_keys.add(key)
                subscriptions.append(
                    {
                        "category": cat,
                        "description": desc or "No description",
                        "avg_amount": avg_amount,
                        "frequency": len(items),
                        "last_date": max(i.date for i in items),
                        "expenses": items,
                    }
                )

    return subscriptions


def get_spending_suggestions(user_id, goal):
    from models import Expense

    since_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
    expenses = Expense.query.filter(
        Expense.user_id == user_id,
        Expense.date >= since_date,
        Expense.is_essential == False,
    ).all()

    category_totals = defaultdict(float)
    for exp in expenses:
        category_totals[exp.category] += exp.amount

    suggestions = []
    for category, amount in sorted(
        category_totals.items(), key=lambda x: x[1], reverse=True
    )[:5]:
        monthly_avg = amount / 3
        reduction = monthly_avg * 0.2
        months_saved = (
            goal.remaining_amount / (goal.monthly_savings + reduction)
            if goal.monthly_savings > 0
            else float("inf")
        )
        original_months = goal.estimated_months
        if months_saved != float("inf"):
            time_saved = original_months - months_saved
            suggestions.append(
                {
                    "category": category,
                    "current_spending": monthly_avg,
                    "suggested_reduction": reduction,
                    "new_monthly_savings": goal.monthly_savings + reduction,
                    "months_saved": time_saved,
                    "original_months": original_months,
                    "new_months": months_saved,
                }
            )
    return suggestions


def run_monthly_reset(user):
    from models import db, Income, Expense, Goal

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last_reset = user.last_monthly_reset

    if last_reset is None:
        user.last_monthly_reset = now
        db.session.commit()
        return False, 0, 0

    if now.year == last_reset.year and now.month == last_reset.month:
        return False, 0, 0

    user.last_monthly_reset = now
    db.session.commit()

    prev_month_start = datetime(last_reset.year, last_reset.month, 1)
    if last_reset.month == 12:
        prev_month_end = datetime(last_reset.year + 1, 1, 1)
    else:
        prev_month_end = datetime(last_reset.year, last_reset.month + 1, 1)

    new_month_start = datetime(now.year, now.month, 1)

    prev_income_total = (
        db.session.query(func.sum(Income.amount))
        .filter(
            Income.user_id == user.id,
            Income.date_received >= prev_month_start,
            Income.date_received < prev_month_end,
        )
        .scalar()
        or 0
    )

    prev_expense_total = (
        db.session.query(func.sum(Expense.amount))
        .filter(
            Expense.user_id == user.id,
            Expense.date >= prev_month_start,
            Expense.date < prev_month_end,
        )
        .scalar()
        or 0
    )

    recurring_incomes = Income.query.filter(
        Income.user_id == user.id,
        Income.date_received >= prev_month_start,
        Income.date_received < prev_month_end,
        Income.is_recurring == True,
    ).all()
    for inc in recurring_incomes:
        db.session.add(
            Income(
                user_id=user.id,
                source=inc.source,
                amount=inc.amount,
                date_received=new_month_start,
                description=inc.description,
                is_recurring=True,
            )
        )

    recurring_expenses = Expense.query.filter(
        Expense.user_id == user.id,
        Expense.date >= prev_month_start,
        Expense.date < prev_month_end,
        Expense.is_subscription == True,
    ).all()
    for exp in recurring_expenses:
        if exp.sub_start_date and new_month_start < exp.sub_start_date.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ):
            continue
        if exp.sub_end_date and new_month_start > exp.sub_end_date:
            continue
        db.session.add(
            Expense(
                user_id=user.id,
                category=exp.category,
                amount=exp.amount,
                date=new_month_start,
                description=exp.description,
                is_essential=exp.is_essential,
                is_subscription=True,
                sub_start_date=exp.sub_start_date,
                sub_end_date=exp.sub_end_date,
            )
        )

    Expense.query.filter(
        Expense.user_id == user.id,
        Expense.date >= prev_month_start,
        Expense.date < prev_month_end,
    ).delete(synchronize_session=False)

    Income.query.filter(
        Income.user_id == user.id,
        Income.date_received >= prev_month_start,
        Income.date_received < prev_month_end,
    ).delete(synchronize_session=False)

    goals_wants_pct = max(0.0, min(100.0, user.goals_wants_pct or 30.0))
    goals_alloc_budget = round(prev_income_total * 0.30 * goals_wants_pct / 100, 2)

    active_goals = sorted(
        [
            g
            for g in Goal.query.filter_by(user_id=user.id).all()
            if g.saved_amount < g.target_amount
        ],
        key=lambda g: (int(g.priority) if str(g.priority).isdigit() else 99),
    )
    goals_funded = 0.0
    if active_goals and goals_alloc_budget > 0:
        total_monthly = sum(g.monthly_savings for g in active_goals)
        for g in active_goals:
            share = round(
                goals_alloc_budget * (g.monthly_savings / total_monthly)
                if total_monthly > 0
                else goals_alloc_budget / len(active_goals),
                2,
            )
            g.saved_amount = round(min(g.target_amount, g.saved_amount + share), 2)
            goals_funded += share

    net_leftover = round(
        max(0.0, prev_income_total - prev_expense_total - goals_funded), 2
    )
    user.savings_balance = round((user.savings_balance or 0.0) + net_leftover, 2)

    db.session.commit()
    return True, net_leftover, round(goals_funded, 2)


def check_subscription_expiry(user_id):
    from models import db, Expense

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    alerts = []

    subscriptions = Expense.query.filter(
        Expense.user_id == user_id,
        Expense.is_subscription == True,
        Expense.sub_end_date != None,
    ).all()

    for sub in subscriptions:
        days_left = (sub.sub_end_date - now).days
        if days_left < 0:
            if not sub.sub_expired_notified:
                alerts.append(
                    {
                        "type": "expired",
                        "name": sub.description or sub.category,
                        "id": sub.id,
                        "end_date": sub.sub_end_date,
                    }
                )
                sub.sub_expired_notified = True
                db.session.commit()
        elif days_left <= 7:
            alerts.append(
                {
                    "type": "expiring",
                    "name": sub.description or sub.category,
                    "id": sub.id,
                    "days_left": days_left,
                    "end_date": sub.sub_end_date,
                }
            )

    return alerts
