import io
import base64
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import make_response, send_file


def make_chart(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110, transparent=True)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return img_b64


def chart_png_response(buf):
    resp = make_response(send_file(buf, mimetype="image/png"))
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


def chart_expense_distribution(categories, dark_mode=False):
    if not categories:
        return None
    txt_color = "#e0e0e0" if dark_mode else "#2d3436"
    labels = list(categories.keys())
    values = list(categories.values())
    colors = [
        "#008080",
        "#00CEC9",
        "#FD79A8",
        "#FDCB6E",
        "#55EFC4",
        "#FF924D",
        "#0984E3",
        "#7dd3fc",
        "#00B894",
        "#74B9FF",
    ]
    fig, ax = plt.subplots(figsize=(5, 4))
    fig.patch.set_alpha(0)
    wedges, _, autotexts = ax.pie(
        values,
        labels=None,
        autopct="%1.0f%%",
        colors=colors[: len(values)],
        startangle=140,
        wedgeprops=dict(width=0.6, edgecolor="white", linewidth=2),
        pctdistance=0.78,
    )
    for t in autotexts:
        t.set_fontsize(9)
        t.set_color("white")
        t.set_fontweight("bold")
    legend = ax.legend(
        wedges,
        [f"{l} (₹{v:,.0f})" for l, v in zip(labels, values)],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.22),
        ncol=2,
        fontsize=8,
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(txt_color)
    ax.set_title(
        "Expense Distribution", fontsize=12, fontweight="bold", pad=10, color=txt_color
    )
    return make_chart(fig)


def chart_income_vs_expense(monthly_inc, monthly_exp, dark_mode=False):
    months = sorted(set(list(monthly_inc.keys()) + list(monthly_exp.keys())))
    if not months:
        return None
    txt_color = "#e0e0e0" if dark_mode else "#2d3436"
    sub_color = "#b0b0b0" if dark_mode else "#636e72"
    grid_color = "#444444" if dark_mode else "#dfe6e9"
    inc_vals = [monthly_inc.get(m, 0) for m in months]
    exp_vals = [monthly_exp.get(m, 0) for m in months]
    x = range(len(months))
    fig, ax = plt.subplots(figsize=(7, 3.8))
    fig.patch.set_alpha(0)
    w = 0.35
    bars1 = ax.bar(
        [i - w / 2 for i in x],
        inc_vals,
        width=w,
        color="#00b894",
        label="Income",
        edgecolor="white",
        linewidth=1.2,
        zorder=3,
    )
    bars2 = ax.bar(
        [i + w / 2 for i in x],
        exp_vals,
        width=w,
        color="#FF924D",
        label="Expense",
        edgecolor="white",
        linewidth=1.2,
        zorder=3,
    )
    for bar in list(bars1) + list(bars2):
        if bar.get_height() > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 100,
                f"₹{bar.get_height():,.0f}",
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=sub_color,
            )
    ax.set_xticks(list(x))
    ax.set_xticklabels(months, fontsize=9, color=txt_color)
    ax.tick_params(axis="y", labelsize=8, colors=txt_color)
    ax.tick_params(axis="x", colors=txt_color)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(
            lambda v, _: f"₹{v / 1000:.0f}k" if v >= 1000 else f"₹{v:.0f}"
        )
    )
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=grid_color, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(grid_color)
    ax.spines["bottom"].set_color(grid_color)
    legend = ax.legend(fontsize=9, frameon=False)
    for text in legend.get_texts():
        text.set_color(txt_color)
    ax.set_title(
        "Income vs Expense", fontsize=12, fontweight="bold", pad=10, color=txt_color
    )
    fig.tight_layout()
    return make_chart(fig)


def chart_monthly_trend(monthly_spending, dark_mode=False):
    if not monthly_spending:
        return None
    txt_color = "#e0e0e0" if dark_mode else "#2d3436"
    grid_color = "#444444" if dark_mode else "#dfe6e9"
    months = list(monthly_spending.keys())
    values = list(monthly_spending.values())
    fig, ax = plt.subplots(figsize=(7, 3.8))
    fig.patch.set_alpha(0)
    ax.fill_between(months, values, alpha=0.12, color="#008080", zorder=1)
    ax.plot(
        months,
        values,
        color="#008080",
        linewidth=2.5,
        marker="o",
        markersize=7,
        markerfacecolor="white",
        markeredgecolor="#008080",
        markeredgewidth=2,
        zorder=2,
    )
    max_val = max(values) if values else 1
    for i, (m, v) in enumerate(zip(months, values)):
        ax.text(
            i,
            v + max_val * 0.03,
            f"₹{v:,.0f}",
            ha="center",
            va="bottom",
            fontsize=8,
            color="#008080",
            fontweight="bold",
        )
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(months, fontsize=9, color=txt_color)
    ax.tick_params(axis="y", labelsize=8, colors=txt_color)
    ax.tick_params(axis="x", colors=txt_color)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(
            lambda v, _: f"₹{v / 1000:.0f}k" if v >= 1000 else f"₹{v:.0f}"
        )
    )
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=grid_color, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(grid_color)
    ax.spines["bottom"].set_color(grid_color)
    ax.set_title(
        "Monthly Spending Trend",
        fontsize=12,
        fontweight="bold",
        pad=10,
        color=txt_color,
    )
    fig.tight_layout()
    return make_chart(fig)


def chart_category_breakdown(categories, dark_mode=False):
    if not categories:
        return None
    txt_color = "#e0e0e0" if dark_mode else "#2d3436"
    sub_color = "#b0b0b0" if dark_mode else "#636e72"
    grid_color = "#444444" if dark_mode else "#dfe6e9"
    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:8]
    labels = [c[0] for c in sorted_cats]
    values = [c[1] for c in sorted_cats]
    colors = [
        "#008080",
        "#0984E3",
        "#00CEC9",
        "#00b894",
        "#55EFC4",
        "#FDCB6E",
        "#FF924D",
        "#FD79A8",
    ]
    fig, ax = plt.subplots(figsize=(6, max(3.5, len(labels) * 0.5)))
    fig.patch.set_alpha(0)
    bars = ax.barh(
        labels[::-1],
        values[::-1],
        color=colors[: len(values)],
        edgecolor="white",
        linewidth=1,
        height=0.6,
        zorder=3,
    )
    max_val = max(values) if values else 1
    for bar, val in zip(bars, values[::-1]):
        ax.text(
            bar.get_width() + max_val * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"₹{val:,.0f}",
            va="center",
            fontsize=8.5,
            color=sub_color,
        )
    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color=grid_color, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(grid_color)
    ax.spines["bottom"].set_color(grid_color)
    ax.tick_params(axis="y", labelsize=9, colors=txt_color)
    ax.tick_params(axis="x", labelsize=8, colors=txt_color)
    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(
            lambda v, _: f"₹{v / 1000:.0f}k" if v >= 1000 else f"₹{v:.0f}"
        )
    )
    ax.set_title(
        "Category Breakdown", fontsize=12, fontweight="bold", pad=10, color=txt_color
    )
    fig.tight_layout()
    return make_chart(fig)


def get_analysis_data(user_id, Expense, Income):
    from models import CreditCardStatement
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = datetime(now.year, now.month, 1)
    six_months_ago = now - timedelta(days=180)

    expenses_month = Expense.query.filter(
        Expense.user_id == user_id, Expense.date >= month_start
    ).all()
    all_expenses = Expense.query.filter(
        Expense.user_id == user_id, Expense.date >= six_months_ago
    ).all()
    all_incomes = Income.query.filter(
        Income.user_id == user_id, Income.date_received >= six_months_ago
    ).all()

    regular_month = [
        e for e in expenses_month
        if e.source_type != "CREDIT_CARD" and not e.is_settlement
    ]
    card_statements = CreditCardStatement.query.filter(
        CreditCardStatement.user_id == user_id,
        CreditCardStatement.statement_date >= month_start,
    ).all()
    categories = {}
    for e in regular_month:
        categories[e.category] = categories.get(e.category, 0) + e.amount
    for statement in card_statements:
        for e in statement.transactions.all():
            categories[e.category] = categories.get(e.category, 0) + e.amount

    monthly_spending = defaultdict(float)
    for exp in all_expenses:
        if exp.source_type != "CREDIT_CARD" and not exp.is_settlement:
            key = exp.date.strftime("%b %Y")
            monthly_spending[key] += exp.amount
    for statement in CreditCardStatement.query.filter(
        CreditCardStatement.user_id == user_id,
        CreditCardStatement.statement_date >= six_months_ago,
    ).all():
        key = statement.statement_date.strftime("%b %Y")
        monthly_spending[key] += statement.statement_total
    sorted_months = sorted(
        monthly_spending.keys(), key=lambda m: datetime.strptime(m, "%b %Y")
    )
    monthly_spending_ordered = {m: monthly_spending[m] for m in sorted_months}

    monthly_income = defaultdict(float)
    monthly_expense_all = defaultdict(float)
    for inc in all_incomes:
        monthly_income[inc.date_received.strftime("%b %Y")] += inc.amount
    for exp in all_expenses:
        if exp.source_type != "CREDIT_CARD" and not exp.is_settlement:
            monthly_expense_all[exp.date.strftime("%b %Y")] += exp.amount
    for statement in CreditCardStatement.query.filter(
        CreditCardStatement.user_id == user_id,
        CreditCardStatement.statement_date >= six_months_ago,
    ).all():
        monthly_expense_all[statement.statement_date.strftime("%b %Y")] += statement.statement_total

    return (
        categories,
        monthly_spending_ordered,
        dict(monthly_income),
        dict(monthly_expense_all),
    )
