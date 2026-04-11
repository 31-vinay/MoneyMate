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
from models import db, User, Income, Expense, Goal
from forms import (
    RegistrationForm,
    LoginForm,
    IncomeForm,
    ExpenseForm,
    GoalForm,
    SavingsUpdateForm,
)
from datetime import datetime, timedelta, timezone
import calendar
from sqlalchemy import func
from collections import defaultdict
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import io
import base64
import zipfile
import re
import csv
import imaplib
import email as email_lib
from email.header import decode_header
from email.utils import parsedate_to_datetime
import ssl
import pdfplumber
import openpyxl
import xlrd
import msoffcrypto
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # type: ignore[assignment]

from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView

admin = Admin(app, name="Finance Manager")
app.config["SECRET_KEY"] = os.environ.get(
    "SESSION_SECRET", "your-secret-key-change-in-production"
)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///finance.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


# Protect admin views with login
class AdminModelView(ModelView):
    def is_accessible(self):
        return (
            current_user.is_authenticated and current_user.username == "admin"
        )  # Change to your admin username

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("login"))


# Add your models to admin
admin.add_view(AdminModelView(User, db.session))
admin.add_view(AdminModelView(Income, db.session))
admin.add_view(AdminModelView(Expense, db.session))
admin.add_view(AdminModelView(Goal, db.session))



@app.route("/create_admin")
def create_admin():
    # Check if admin already exists
    admin_user = User.query.filter_by(username="admin").first()
    if not admin_user:
        admin_password = os.environ.get("ADMIN_PASSWORD")
        if not admin_password:
            return (
                "ADMIN_PASSWORD environment variable is not set. Admin user not created.",
                500,
            )
        admin_user = User(
            username="admin", email="admin@example.com", password=admin_password
        )
        db.session.add(admin_user)
        db.session.commit()
        return "Admin user created! Username: admin"
    return "Admin user already exists"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Create tables and run any needed column migrations
with app.app_context():
    db.create_all()
    migration_stmts = [
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
    ]
    for stmt in migration_stmts:
        try:
            with db.engine.connect() as conn:
                conn.execute(db.text(stmt))
                conn.commit()
        except Exception:
            pass
    # Migrate old text priorities (high/medium/low) to numeric
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


# Category hierarchy from ChatGPT
expense_categories = {
    "Housing": {
        "subcategories": [
            "Rent",
            "Mortgage",
            "Property Tax",
            "Home Maintenance",
            "Home Repairs",
            "Furniture",
            "Home Decor",
            "Security System",
            "Cleaning Services",
            "Home Insurance",
        ],
        "classification": {
            "Rent": "need",
            "Mortgage": "need",
            "Property Tax": "need",
            "Home Maintenance": "need",
            "Home Repairs": "need",
            "Furniture": "want",
            "Home Decor": "want",
            "Security System": "need",
            "Cleaning Services": "want",
            "Home Insurance": "need",
        },
    },
    "Food & Groceries": {
        "subcategories": [
            "Groceries",
            "Basic Food Staples",
            "Dining Out",
            "Fast Food",
            "Coffee Shops",
            "Food Delivery",
            "Snacks",
            "Meal Kits",
            "Specialty Foods",
        ],
        "classification": {
            "Groceries": "need",
            "Basic Food Staples": "need",
            "Dining Out": "want",
            "Fast Food": "want",
            "Coffee Shops": "want",
            "Food Delivery": "want",
            "Snacks": "want",
            "Meal Kits": "want",
            "Specialty Foods": "want",
        },
    },
    "Transportation": {
        "subcategories": [
            "Fuel",
            "Public Transport",
            "Taxi/Rideshare",
            "Vehicle Maintenance",
            "Vehicle Insurance",
            "Parking Fees",
            "Tolls",
            "Car Loan Payment",
            "Car Wash",
            "Vehicle Registration",
        ],
        "classification": {
            "Fuel": "need",
            "Public Transport": "need",
            "Taxi/Rideshare": "want",
            "Vehicle Maintenance": "need",
            "Vehicle Insurance": "need",
            "Parking Fees": "need",
            "Tolls": "need",
            "Car Loan Payment": "need",
            "Car Wash": "want",
            "Vehicle Registration": "need",
        },
    },
    "Utilities": {
        "subcategories": [
            "Electricity",
            "Water",
            "Gas",
            "Internet",
            "Mobile Phone",
            "Trash Collection",
            "Sewer Charges",
            "Streaming Bundled with Internet",
        ],
        "classification": {
            "Electricity": "need",
            "Water": "need",
            "Gas": "need",
            "Internet": "need",
            "Mobile Phone": "need",
            "Trash Collection": "need",
            "Sewer Charges": "need",
            "Streaming Bundled with Internet": "want",
        },
    },
    "Healthcare": {
        "subcategories": [
            "Doctor Visits",
            "Hospital Bills",
            "Pharmacy",
            "Health Insurance",
            "Dental Care",
            "Vision Care",
            "Mental Health Therapy",
            "Medical Equipment",
            "Health Supplements",
        ],
        "classification": {
            "Doctor Visits": "need",
            "Hospital Bills": "need",
            "Pharmacy": "need",
            "Health Insurance": "need",
            "Dental Care": "need",
            "Vision Care": "need",
            "Mental Health Therapy": "need",
            "Medical Equipment": "need",
            "Health Supplements": "want",
        },
    },
    "Education": {
        "subcategories": [
            "School Tuition",
            "College Tuition",
            "Online Courses",
            "Books",
            "School Supplies",
            "Professional Certifications",
            "Workshops",
            "Educational Software",
        ],
        "classification": {
            "School Tuition": "need",
            "College Tuition": "need",
            "Online Courses": "want",
            "Books": "need",
            "School Supplies": "need",
            "Professional Certifications": "need",
            "Workshops": "want",
            "Educational Software": "need",
        },
    },
    "Insurance": {
        "subcategories": [
            "Health Insurance",
            "Life Insurance",
            "Vehicle Insurance",
            "Home Insurance",
            "Travel Insurance",
            "Pet Insurance",
        ],
        "classification": {
            "Health Insurance": "need",
            "Life Insurance": "need",
            "Vehicle Insurance": "need",
            "Home Insurance": "need",
            "Travel Insurance": "want",
            "Pet Insurance": "want",
        },
    },
    "Personal & Lifestyle": {
        "subcategories": [
            "Clothing",
            "Shoes",
            "Haircuts",
            "Beauty Products",
            "Gym Membership",
            "Salon Services",
            "Spa",
            "Personal Care Items",
        ],
        "classification": {
            "Clothing": "need",
            "Shoes": "need",
            "Haircuts": "need",
            "Beauty Products": "want",
            "Gym Membership": "want",
            "Salon Services": "want",
            "Spa": "want",
            "Personal Care Items": "need",
        },
    },
    "Entertainment": {
        "subcategories": [
            "Movies",
            "Concerts",
            "Gaming",
            "Streaming Subscriptions",
            "Hobbies",
            "Books & Magazines",
            "Theme Parks",
            "Events & Shows",
        ],
        "classification": {
            "Movies": "want",
            "Concerts": "want",
            "Gaming": "want",
            "Streaming Subscriptions": "want",
            "Hobbies": "want",
            "Books & Magazines": "want",
            "Theme Parks": "want",
            "Events & Shows": "want",
        },
    },
    "Travel": {
        "subcategories": [
            "Flights",
            "Hotels",
            "Vacation Packages",
            "Local Travel",
            "Travel Insurance",
            "Tour Guides",
            "Resort Stay",
        ],
        "classification": {
            "Flights": "want",
            "Hotels": "want",
            "Vacation Packages": "want",
            "Local Travel": "need",
            "Travel Insurance": "want",
            "Tour Guides": "want",
            "Resort Stay": "want",
        },
    },
    "Debt & Financial Obligations": {
        "subcategories": [
            "Credit Card Payment",
            "Loan Repayment",
            "Student Loan Payment",
            "Personal Loan",
            "Bank Fees",
            "Late Fees",
        ],
        "classification": {
            "Credit Card Payment": "need",
            "Loan Repayment": "need",
            "Student Loan Payment": "need",
            "Personal Loan": "need",
            "Bank Fees": "need",
            "Late Fees": "want",
        },
    },
    "Other": {
        "subcategories": ["Other (User Input)"],
        "classification": {"Other (User Input)": "unknown"},
    },
}

# Flatten the needs keywords for backward compatibility
essential_keywords = []
for main_cat, data in expense_categories.items():
    classification_map = data.get("classification", {})
    if isinstance(classification_map, dict):
        for subcat, classification in classification_map.items():
            if classification == "need":
                essential_keywords.append(subcat.lower())
                if main_cat.lower() not in essential_keywords:
                    essential_keywords.append(main_cat.lower())


def auto_categorize_transaction(description):
    """
    Keyword-based categorizer for UPI / bank statement transactions.
    Returns (sub_category, is_essential, is_subscription).
    sub_category matches keys inside expense_categories[*]['subcategories'].
    """
    d = (description or "").upper()

    # For UPI transactions, extract the merchant segment (between 1st and 2nd dash)
    merchant = ""
    if d.startswith("UPI-"):
        parts = description.split("-")
        if len(parts) > 1:
            merchant = parts[1].upper()

    # Tail note (e.g. "DINNER", "ICECREAM", "IMAGICA") — last segment
    note = d.split("-")[-1].strip() if "-" in d else ""

    combined = d + " " + merchant + " " + note

    def hit(*words):
        return any(w in combined for w in words)

    # ── Food Delivery ─────────────────────────────────────────────
    if hit(
        "SWIGGY",
        "ZOMATO",
        "BLINKIT",
        "EATCLUB",
        "FAASOS",
        "REBEL FOODS",
        "BOX8",
        "FRESHMENU",
        "LICIOUS",
        "DUNZO",
        "ZEPTO",
        "GROFERS",
        "MILKBASKET",
        "DAILY NINJA",
        "FRESH TO HOME",
        "COUNTRY DELIGHT",
        "JIOMART",
        "DINEOUT",
    ):
        return ("Food Delivery", False, False)

    # ── Groceries ────────────────────────────────────────────────
    if hit(
        "BIGBASKET",
        "RELIANCE FRESH",
        "RELIANCE SMART",
        "DMART",
        "D-MART",
        "SUPERMART",
        "MORE SUPERMARKET",
        "STAR BAZAR",
        "HYPERCITY",
        "SPAR",
        "METRO CASH",
        "NATURE BASKET",
        "HERITAGE FRESH",
        "RATNADEEP",
        "SMART BAZAR",
        "SUPERMARKET",
        "GROCERY",
        "KIRANA",
    ):
        return ("Groceries", True, False)

    # ── Dining Out / Fast Food ────────────────────────────────────
    if hit(
        "RESTAURANT",
        "CAFE",
        "CANTEEN",
        "CATERING",
        "EATERY",
        "DHABA",
        "BIRYANI",
        "PIZZA",
        "BURGER",
        "BAKERY",
        "KITCHEN",
        "SWEETS",
        "MITHAI",
        "FUSION",
        "GRILL",
        "ROLLS",
        "JUICE BAR",
        "LASSI",
        "STALL",
        "CHAI",
        "ICECREAM",
        "ICE CREAM",
        "HALWAI",
        "TIFFIN",
        "MESS",
        "KFC",
        "MCDONALDS",
        "MCDONALD",
        "SUBWAY",
        "DOMINOS",
        "DOMINO",
        "BURGER KING",
        "BASKIN ROBBINS",
        "STARBUCKS",
        "COSTA COFFEE",
        "BARISTA",
        "CHAAYOS",
        "THEOBROMA",
        "QUICKVEND",
        "VENDING",
        "SWEET FUSION",
        "COSMOS CATERING",
        "JAI GANESH",
        "ROBERTO",
        "ROBERTOS",
    ):
        return ("Dining Out", False, False)

    # note-only hints (for generic UPI alerts that lack merchant name)
    if hit("DINNER", "LUNCH", "BREAKFAST", "SNACK", "COFFEE", "CHAI ", "TEA "):
        return ("Dining Out", False, False)

    # ── Public Transport ──────────────────────────────────────────
    if hit(
        "INDIAN RAILWAYS",
        "IRCTC",
        "RAILWAYS UTS",
        "METRO RAIL",
        "METRO CARD",
        "DMRC",
        "NMMC BUS",
        "MSRTC",
        "KSRTC",
        "TSRTC",
        "UPSRTC",
        "GSRTC",
        "OSRTC",
        "BMTC",
        "PMPML",
        "BEST BUS",
        "APSRTC",
        "NAMMA METRO",
    ):
        return ("Public Transport", True, False)

    # ── Fuel ─────────────────────────────────────────────────────
    if hit(
        "PETROL",
        "DIESEL",
        "CNG FILL",
        "HPCL",
        "BPCL",
        "IOC",
        "INDIANOIL",
        "BHARAT PETRO",
        "HP PETRO",
        "GAS STATION",
        "FILLING STATION",
        "NAYARA",
        "ESSAR OIL",
    ):
        return ("Fuel", True, False)

    # ── Taxi / Rideshare ─────────────────────────────────────────
    if hit(
        "OLA ELECTRIC",
        "OLA ",
        "UBER",
        "RAPIDO",
        "MERU CAB",
        "YULU",
        "BOUNCE",
        "ZOOMCAR",
        "ZOOM CAR",
        "DRIVEZY",
    ):
        return ("Taxi/Rideshare", False, False)

    # ── Parking / Tolls ──────────────────────────────────────────
    if hit("PARKING", "TOLL PLAZA", "FASTAG", "IHMCL", "NHAI"):
        return ("Parking Fees", True, False)

    # ── Electricity ───────────────────────────────────────────────
    if hit(
        "ELECTRICITY",
        "ELECTRIC BILL",
        "MSEDCL",
        "BESCOM",
        "TNEB",
        "UPPCL",
        "CESC",
        "TPDDL",
        "BSES",
        "WBSEDCL",
        "APEPDCL",
        "KPTCL",
        "HESCOM",
        "GESCOM",
        "POWER BILL",
    ):
        return ("Electricity", True, False)

    # ── Water ─────────────────────────────────────────────────────
    if hit("WATER BILL", "WATER SUPPLY", "BWSSB", "WATER TAX", "WATER BOARD"):
        return ("Water", True, False)

    # ── Gas ───────────────────────────────────────────────────────
    if hit(
        "PIPED GAS",
        "PNG GAS",
        "IGL",
        "MGL",
        "MAHANAGAR GAS",
        "ADANI GAS",
        "TORRENT GAS",
        "GUJARAT GAS",
    ):
        return ("Gas", True, False)

    # ── Internet ──────────────────────────────────────────────────
    if hit(
        "BROADBAND",
        "FIBER",
        "FIBRE",
        "ACT FIBERNET",
        "JIOFIBER",
        "HATHWAY",
        "EXCITEL",
        "TIKONA",
        "SPECTRANET",
        "AIRTEL FIBER",
        "WIFI BILL",
    ):
        return ("Internet", True, False)

    # ── Mobile Recharge ───────────────────────────────────────────
    if hit(
        "MOBILE RECHARGE",
        "PREPAID RECHARGE",
        "AIRTEL PREPAID",
        "JIO PREPAID",
        "VODAFONE PREPAID",
        "VI PREPAID",
        "BSNL RECHARGE",
        "TATA DOCOMO",
    ):
        return ("Mobile Phone", True, False)

    # ── Pharmacy ─────────────────────────────────────────────────
    if hit(
        "PHARMACY",
        "MEDICAL STORE",
        "CHEMIST",
        "APOLLO PHARMACY",
        "MEDPLUS",
        "NETMEDS",
        "1MG",
        "PHARMEASY",
        "WELLNESS FOREVER",
        "PRACTO",
    ):
        return ("Pharmacy", True, False)

    # ── Doctor / Hospital ─────────────────────────────────────────
    if hit(
        "HOSPITAL",
        "CLINIC",
        "NURSING HOME",
        "DIAGNOSTIC",
        "PATHOLOGY",
        "RADIOLOGY",
        "DENTIST",
        "DENTAL",
        "EYE CARE",
        "OPTICAL",
        "PHYSIOTHERAPY",
    ):
        return ("Doctor Visits", True, False)

    # ── Streaming / Subscriptions ─────────────────────────────────
    if hit(
        "NETFLIX",
        "HOTSTAR",
        "DISNEY",
        "AMAZON PRIME",
        "PRIME VIDEO",
        "SONYLIV",
        "ZEE5",
        "VOOT",
        "ALT BALAJI",
        "JIOCINEMA",
        "YOUTUBE PREMIUM",
        "SPOTIFY",
        "GAANA",
        "WYNK",
        "JIOSAAVN",
        "APPLE MUSIC",
        "HUNGAMA",
    ):
        return ("Streaming Subscriptions", False, True)

    # ── Movies / Events ───────────────────────────────────────────
    if hit("PVR", "INOX", "CINEPOLIS", "CARNIVAL CINEMA", "BOOKMYSHOW", "MOVIE TICKET"):
        return ("Movies", False, False)

    # ── Gaming ────────────────────────────────────────────────────
    if hit("STEAM", "XBOX", "PLAYSTATION", "GOOGLE PLAY GAMES", "PUBG", "GAMING"):
        return ("Gaming", False, False)

    # ── Theme Parks / Recreation ──────────────────────────────────
    if hit(
        "IMAGICA",
        "WONDERLA",
        "ESSEL WORLD",
        "WATER PARK",
        "THEME PARK",
        "AMUSEMENT PARK",
    ):
        return ("Theme Parks", False, False)

    # ── Travel ────────────────────────────────────────────────────
    if hit(
        "MAKEMYTRIP",
        "GOIBIBO",
        "CLEARTRIP",
        "YATRA",
        "EASEMYTRIP",
        "OYO",
        "TREEBO",
        "ZOSTEL",
        "SPICEJET",
        "INDIGO",
        "VISTARA",
        "AIR INDIA",
        "GOAIR",
    ):
        return ("Local Travel", False, False)

    # ── Clothing / Fashion ────────────────────────────────────────
    if hit(
        "MYNTRA",
        "AJIO",
        "NYKAA FASHION",
        "H&M",
        "ZARA",
        "PANTALOONS",
        "WESTSIDE",
        "MAX FASHION",
        "SHOPPERS STOP",
        "LIFESTYLE STORE",
        "GARMENTS",
        "BOUTIQUE",
        "CLOTHING",
    ):
        return ("Clothing", True, False)

    # ── Beauty / Salon ────────────────────────────────────────────
    if hit(
        "NYKAA",
        "PURPLLE",
        "SALON",
        "BEAUTY PARLOUR",
        "MANICURE",
        "PEDICURE",
        "WAXING",
        "FACIAL",
        "SPA",
    ):
        return ("Beauty Products", False, False)

    # ── Education ─────────────────────────────────────────────────
    if hit(
        "UNACADEMY",
        "BYJUS",
        "BYJU",
        "VEDANTU",
        "TOPPR",
        "COURSERA",
        "UDEMY",
        "EDUREKA",
        "SIMPLILEARN",
        "UPGRAD",
        "SCHOOL FEE",
        "COLLEGE FEE",
        "TUITION",
        "COACHING",
    ):
        return ("Online Courses", False, False)

    # ── Rent ──────────────────────────────────────────────────────
    if hit(
        "HOUSE RENT",
        "FLAT RENT",
        "APARTMENT RENT",
        "LANDLORD",
        "RENTAL PAYMENT",
        "PROPERTY TAX",
    ):
        return ("Rent", True, False)

    # ── Home Maintenance ──────────────────────────────────────────
    if hit(
        "SOCIETY CHARGES",
        "MAINTENANCE CHARGES",
        "HOA",
        "PLUMBER",
        "ELECTRICIAN",
        "CARPENTER",
        "PAINTER",
        "HOME REPAIR",
    ):
        return ("Home Maintenance", True, False)

    # ── Financial / Bank fees / EMI / FD ─────────────────────────
    if hit(
        "CREDIT CARD PAYMENT",
        "LOAN EMI",
        " EMI ",
        "LIC PREMIUM",
        "SBI LIFE",
        "HDFC LIFE",
        "MAX LIFE",
        "BAJAJ ALLIANZ",
        "ICICI PRUDENTIAL",
        "MUTUAL FUND",
        " SIP ",
        "ZERODHA",
        "GROWW",
        "BANK FEE",
        "BANK CHARGES",
        "EURONET",
        "FD THROUGH NET",
        "FIXED DEPOSIT",
        "RECURRING DEPOSIT",
    ):
        return ("Bank Fees", True, False)

    # ── Hair / Grooming ───────────────────────────────────────────
    if hit(
        "HAIR CUTTING", "BARBER", "HAIR SALON", "STYLO HAIR", "HAIR CUT", "GROOMING"
    ):
        return ("Haircuts", False, False)

    # ── Grocery / Food stores (additional merchants) ──────────────
    if hit(
        "PURPLEYAM",
        "SUNSHINE FINE FOOD",
        "FINE FOOD",
        "FRESH FOOD",
        "FOOD MART",
        "FOOD STORE",
        "FOODMART",
    ):
        return ("Food Delivery", False, False)

    # ── UIDAI / Government ────────────────────────────────────────
    if hit(
        "UIDAI",
        "RESIDENT.UIDAI",
        "GOVT.",
        "GOVERNMENT",
        "MUNICIPAL",
        "NAGAR PALIKA",
        "NAGAR NIGAM",
    ):
        return ("Bank Fees", True, False)

    # ── Personal transfers (common UPI peer-to-peer patterns) ─────
    # Names following "UPI-MR ", "UPI-MISS ", "UPI-MRS " are person-to-person
    if hit("UPI-MR ", "UPI-MS ", "UPI-MISS ", "UPI-MRS ", "UPI-DR "):
        return ("Other (User Input)", False, False)

    # Any remaining UPI transaction that didn't match a known merchant
    # is most likely a P2P personal transfer — mark for manual review
    if (
        d.startswith("UPI-")
        and merchant
        and not any(
            biz in merchant
            for biz in (
                "SHOP",
                "STORE",
                "MART",
                "ENTERPRISES",
                "ENTERPRISE",
                "SERVICES",
                "SERVICE",
                "CATERING",
                "AGENCY",
                "LIMITED",
                "LTD",
                "PVT",
                "FOODS",
                "KITCHEN",
                "CENTRE",
                "CENTER",
            )
        )
    ):
        return ("Other (User Input)", False, False)

    # Default — leave for manual review
    return ("Uncategorized", False, False)


def classify_essential(main_category, sub_category, custom_category=None):
    if sub_category is None:
        return False

    if sub_category == "Other (User Input)" and custom_category:
        return classify_essential_keywords(custom_category)

    if main_category and main_category in expense_categories:
        cat_data = expense_categories[main_category]
        if sub_category in cat_data["classification"]:
            classification = cat_data["classification"][sub_category]
            if classification == "need":
                return True
            elif classification == "want":
                return False

    return classify_essential_keywords(sub_category)


def classify_essential_keywords(text):
    if text is None or text == "":
        return False
    text_lower = text.lower()
    for kw in essential_keywords:
        if kw in text_lower:
            return True
    return False


# Helper: detect recurring subscriptions
def detect_subscriptions(user_id, months_back=3):
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

    # First: include any expense explicitly marked as a subscription
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

    # Second: auto-detect by repeated pattern (same category+description, 2+ times, similar amount)
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


# Helper: get spending reduction suggestions
def get_spending_suggestions(user_id, goal):
    # Get last 3 months of expenses
    since_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
    expenses = Expense.query.filter(
        Expense.user_id == user_id,
        Expense.date >= since_date,
        Expense.is_essential == False,  # Only non-essential expenses
    ).all()

    # Group by category and sum
    category_totals = defaultdict(float)
    for exp in expenses:
        category_totals[exp.category] += exp.amount

    # Sort by amount (highest first)
    suggestions = []
    for category, amount in sorted(
        category_totals.items(), key=lambda x: x[1], reverse=True
    )[:5]:
        monthly_avg = amount / 3  # Average monthly spending

        # Suggest reducing by 20% as a starting point
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
    """Monthly rollover: carry recurring entries forward to the new month,
    delete all old-month data, and carry leftover balance into savings."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last_reset = user.last_monthly_reset

    if last_reset is None:
        user.last_monthly_reset = now
        db.session.commit()
        return False, 0, 0

    if now.year == last_reset.year and now.month == last_reset.month:
        return False, 0, 0

    # ── Save the reset timestamp FIRST so a mid-way failure can't re-trigger the reset ──
    user.last_monthly_reset = now
    db.session.commit()

    prev_month_start = datetime(last_reset.year, last_reset.month, 1)
    if last_reset.month == 12:
        prev_month_end = datetime(last_reset.year + 1, 1, 1)
    else:
        prev_month_end = datetime(last_reset.year, last_reset.month + 1, 1)

    new_month_start = datetime(now.year, now.month, 1)

    # ── Calculate previous month totals BEFORE touching anything ──
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

    # ── Roll recurring income forward into the new month ──
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

    # ── Roll recurring subscription expenses forward into the new month ──
    recurring_expenses = Expense.query.filter(
        Expense.user_id == user.id,
        Expense.date >= prev_month_start,
        Expense.date < prev_month_end,
        Expense.is_subscription == True,
    ).all()
    for exp in recurring_expenses:
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

    # ── Delete ALL previous month entries (old recurring copies no longer needed) ──
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

    # ── Fund goals from the Wants budget (user-configured %) ──
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

    # ── Carry true net leftover into cumulative savings_balance ──
    # Net leftover = income − expenses − goals funded this month
    net_leftover = round(max(0.0, prev_income_total - prev_expense_total - goals_funded), 2)
    user.savings_balance = round((user.savings_balance or 0.0) + net_leftover, 2)

    db.session.commit()
    return True, net_leftover, round(goals_funded, 2)


def check_subscription_expiry(user_id):
    """Check for expired or expiring subscriptions and return alerts."""
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
            # Expired
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
            # Expiring soon
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


@app.route("/manifest.json")
def pwa_manifest():
    return send_from_directory(
        "static", "manifest.json", mimetype="application/manifest+json"
    )


@app.route("/sw.js")
def pwa_sw():
    response = send_from_directory("static", "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.route("/offline")
def offline():
    return render_template("offline.html")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            password=form.password.data,
        )
        db.session.add(user)
        db.session.commit()
        flash("Account created! You can now log in.", "success")
        return redirect(url_for("login"))
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
                    if not user.has_seen_tutorial:
                        return redirect(url_for("tutorial"))
                    return redirect(url_for("dashboard"))
                else:
                    flash("Incorrect MPIN. Please try again.", "danger")
                    return render_template(
                        "login.html", form=form, prefill_email=email, show_mpin=True
                    )
            elif password_input:
                if user.password == password_input:
                    login_user(user)
                    if not user.has_seen_tutorial:
                        return redirect(url_for("tutorial"))
                    return redirect(url_for("dashboard"))
                else:
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
        elif current_user.password != current_password:
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
    if current_user.password != current_password:
        flash("Password incorrect. MPIN not removed.", "danger")
    else:
        current_user.mpin = None
        db.session.commit()
        flash("MPIN removed successfully.", "success")
    return redirect(url_for("settings"))


@app.route("/profile")
@login_required
def profile():
    return redirect(url_for("settings"))


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/change-email", methods=["POST"])
@login_required
def change_email():
    new_email = request.form.get("new_email", "").strip()
    current_password = request.form.get("current_password", "").strip()
    if current_user.password != current_password:
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


@app.route("/toggle-notifications", methods=["POST"])
@login_required
def toggle_notifications():
    current_user.notifications_enabled = not current_user.notifications_enabled
    db.session.commit()
    state = "enabled" if current_user.notifications_enabled else "disabled"
    flash(f"Pop notifications {state}.", "success")
    return redirect(url_for("settings"))


@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    current_password = request.form.get("current_password", "").strip()
    if current_user.password != current_password:
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
    if current_user.password != current_password:
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


@app.route("/update-goals-wants-pct", methods=["POST"])
@login_required
def update_goals_wants_pct():
    try:
        pct = float(request.form.get("goals_wants_pct", 30))
        if pct != pct:  # NaN check: NaN is the only value not equal to itself
            raise ValueError("NaN is not a valid percentage")
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


@app.route("/change-password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "").strip()
    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()
    if current_user.password != current_password:
        flash("Current password is incorrect.", "danger")
    elif len(new_password) < 4:
        flash("New password must be at least 4 characters.", "danger")
    elif new_password != confirm_password:
        flash("New passwords do not match.", "danger")
    else:
        current_user.password = new_password
        db.session.commit()
        flash("Password updated successfully!", "success")
    return redirect(url_for("settings"))


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


@app.route("/dashboard")
@login_required
def dashboard():
    # Monthly auto-reset: clear previous month's non-subscription/non-recurring data
    was_reset, net_leftover, goals_funded_reset = run_monthly_reset(current_user)
    if was_reset:
        msg = "A new month has started! Your dashboard has been reset. Subscriptions and recurring income are preserved."
        if net_leftover > 0:
            msg += f" ₹{net_leftover:,.2f} net surplus was added to your savings."
        if goals_funded_reset > 0:
            msg += f" ₹{goals_funded_reset:,.2f} was allocated to your goals from your Wants budget."
        flash(msg, "info")

    # Check subscription expiry
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

    # Allow browsing past months via ?month=YYYY-MM
    selected_month_str = request.args.get("month", "")
    try:
        sel_dt = datetime.strptime(selected_month_str, "%Y-%m")
        view_year, view_month = sel_dt.year, sel_dt.month
    except ValueError:
        view_year, view_month = now.year, now.month
    month_start = datetime(view_year, view_month, 1)
    # End of selected month
    if view_month == 12:
        month_end = datetime(view_year + 1, 1, 1)
    else:
        month_end = datetime(view_year, view_month + 1, 1)
    is_current_month = view_year == now.year and view_month == now.month
    # List last 12 months for the picker
    month_options = []
    for i in range(12):
        mo = now.month - i
        yo = now.year
        while mo <= 0:
            mo += 12
            yo -= 1
        month_options.append(
            (f"{yo:04d}-{mo:02d}", datetime(yo, mo, 1).strftime("%b %Y"))
        )
    selected_month_label = datetime(view_year, view_month, 1).strftime("%B %Y")

    # Expenses this month
    expenses = Expense.query.filter(
        Expense.user_id == current_user.id,
        Expense.date >= month_start,
        Expense.date < month_end,
    ).all()
    total_spent = sum(e.amount for e in expenses)
    essential_spent = sum(e.amount for e in expenses if e.is_essential)
    non_essential_spent = total_spent - essential_spent
    needs_pct = (essential_spent / total_spent * 100) if total_spent else 0
    wants_pct = (non_essential_spent / total_spent * 100) if total_spent else 0
    wants_alert = wants_pct > 50

    # Category breakdown
    categories = {}
    for e in expenses:
        categories[e.category] = categories.get(e.category, 0) + e.amount

    # Income this month
    incomes = Income.query.filter(
        Income.user_id == current_user.id,
        Income.date_received >= month_start,
        Income.date_received < month_end,
    ).all()
    total_income = sum(i.amount for i in incomes)
    source_breakdown = {}
    for inc in incomes:
        source_breakdown[inc.source] = source_breakdown.get(inc.source, 0) + inc.amount
    source_percentages = {
        src: (amt / total_income * 100) if total_income else 0
        for src, amt in source_breakdown.items()
    }

    # Recent transactions: today+yesterday for current month, all entries for past months
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
                Expense.user_id == current_user.id,
                Expense.date >= yesterday_start,
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

    # Burn rate (use actual days elapsed for current month; full month for past months)
    if is_current_month:
        days_passed = max(1, (now - month_start).days + 1)
    else:
        days_passed = max(1, (month_end - month_start).days)
    burn_rate = total_spent / days_passed if days_passed > 0 else 0

    # Subscriptions (detected)
    subscriptions = detect_subscriptions(current_user.id)
    total_sub_cost = sum(s["avg_amount"] for s in subscriptions)

    # Goals
    goals = (
        Goal.query.filter_by(user_id=current_user.id)
        .order_by(Goal.created_at.desc())
        .all()
    )

    monthly_spending = defaultdict(float)
    for exp in expenses:
        monthly_spending[exp.date.strftime("%b")] += exp.amount

    essential = essential_spent
    non_essential = non_essential_spent

    # 50/30/20 Budget Rule
    budget_needs = total_income * 0.50
    budget_wants = total_income * 0.30
    budget_savings = total_income * 0.20

    needs_remaining = budget_needs - essential
    wants_remaining = budget_wants - non_essential

    needs_used_pct = (
        min(100, (essential / budget_needs * 100)) if budget_needs > 0 else 0
    )
    wants_used_pct = (
        min(100, (non_essential / budget_wants * 100)) if budget_wants > 0 else 0
    )

    needs_warning = (needs_remaining > 0) and (needs_remaining <= budget_needs * 0.10)
    wants_warning = (wants_remaining > 0) and (wants_remaining <= budget_wants * 0.10)
    needs_over = needs_remaining < 0
    wants_over = wants_remaining < 0

    # Cumulative savings balance (carries forward month to month)
    total_savings = round(current_user.savings_balance or 0.0, 2)

    # Goals allocation from Wants budget
    goals_wants_pct = max(0.0, min(100.0, current_user.goals_wants_pct or 30.0))
    goals_alloc = round(budget_wants * goals_wants_pct / 100, 2)
    free_wants = round(budget_wants - goals_alloc, 2)

    # Month-end prediction (only meaningful for current month)
    days_in_month = calendar.monthrange(view_year, view_month)[1]
    if is_current_month:
        days_remaining = days_in_month - now.day
    else:
        days_remaining = 0
    projected_month_end_spend = total_spent + (burn_rate * days_remaining)
    predicted_balance = total_income - projected_month_end_spend
    show_month_forecast_warning = (
        is_current_month and (days_remaining <= 10) and (predicted_balance < 0)
    )

    # Personalized saving tips for the warning alert
    shortfall = abs(predicted_balance) if predicted_balance < 0 else 0
    required_daily_savings = (
        round(shortfall / days_remaining, 2) if days_remaining > 0 else shortfall
    )

    # Top non-essential spending categories
    non_essential_categories = {}
    for e in expenses:
        if not e.is_essential:
            non_essential_categories[e.category] = (
                non_essential_categories.get(e.category, 0) + e.amount
            )
    top_non_essential_cats = sorted(
        non_essential_categories.items(), key=lambda x: x[1], reverse=True
    )[:3]

    # Subscriptions to consider pausing
    top_subs = sorted(subscriptions, key=lambda s: s["avg_amount"], reverse=True)[:3]

    # Goal suggestions: recommend allocation from Wants goals budget
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
        # Proportional allocation using inverse-weight: priority 1 gets most
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
        total_spent=total_spent,
        burn_rate=burn_rate,
        source_breakdown=source_breakdown,
        source_percentages=source_percentages,
        essential=essential,
        non_essential=non_essential,
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


@app.route("/add_income", methods=["GET", "POST"])
@login_required
def add_income():
    form = IncomeForm()
    if form.validate_on_submit():
        date_received = form.date_received.data
        if date_received:
            date_received = datetime.combine(date_received, datetime.min.time())
        else:
            date_received = datetime.now(timezone.utc).replace(tzinfo=None)
        income = Income(
            user_id=current_user.id,
            source=form.source.data,
            amount=form.amount.data,
            date_received=date_received,
            description=form.description.data,
            is_recurring=form.is_recurring.data,
        )
        db.session.add(income)
        db.session.commit()
        flash("Income added successfully!", "success")
        return redirect(url_for("dashboard"))
    # Day filter
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


@app.route("/add_expense", methods=["GET", "POST"])
@login_required
def add_expense():
    form = ExpenseForm()
    form.main_category.choices = [("", "-- Select Category --")] + [
        (cat, cat) for cat in expense_categories.keys()
    ]

    if request.method == "POST" and form.main_category.data:
        main_cat = form.main_category.data
        if main_cat in expense_categories:
            subcats = expense_categories[main_cat]["subcategories"]
            form.sub_category.choices = [("", "-- Select Sub Category --")] + [
                (sub, sub) for sub in subcats
            ]

    if request.method == "POST":
        if form.validate_on_submit():
            if (
                form.sub_category.data == "Other (User Input)"
                and form.custom_category.data
            ):
                category = form.custom_category.data
            else:
                category = form.sub_category.data

            is_essential = classify_essential(
                form.main_category.data,
                form.sub_category.data,
                form.custom_category.data,
            )

            exp_date = datetime.now(timezone.utc).replace(tzinfo=None)
            if form.date.data:
                exp_date = datetime.combine(form.date.data, datetime.min.time())
            sub_start = None
            sub_end = None
            if form.is_subscription.data:
                if form.sub_start_date.data:
                    sub_start = datetime.combine(
                        form.sub_start_date.data, datetime.min.time()
                    )
                if form.sub_end_date.data:
                    sub_end = datetime.combine(
                        form.sub_end_date.data, datetime.min.time()
                    )

            expense = Expense(
                user_id=current_user.id,
                category=category,
                amount=form.amount.data,
                date=exp_date,
                description=form.description.data,
                is_essential=is_essential,
                is_subscription=form.is_subscription.data,
                sub_start_date=sub_start,
                sub_end_date=sub_end,
            )
            db.session.add(expense)
            db.session.commit()
            flash("Expense added successfully!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Please check the form and try again.", "danger")
    else:
        form.sub_category.choices = [("", "-- Select Sub Category First --")]

    # Day filter for expense list
    try:
        exp_filter_days = int(request.args.get("days", 0))
        if exp_filter_days <= 0:
            exp_filter_days = None
    except (ValueError, TypeError):
        exp_filter_days = None

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

    expenses = expense_query.order_by(Expense.date.desc()).all()
    return render_template(
        "add_expense.html",
        form=form,
        edit=False,
        expenses=expenses,
        exp_filter_days=exp_filter_days,
        exp_filter_label=exp_filter_label,
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
    form.main_category.choices = [("", "-- Select Category --")] + [
        (cat, cat) for cat in expense_categories.keys()
    ]

    if request.method == "POST" and form.main_category.data:
        main_cat = form.main_category.data
        if main_cat in expense_categories:
            subcats = expense_categories[main_cat]["subcategories"]
            form.sub_category.choices = [("", "-- Select Sub Category --")] + [
                (sub, sub) for sub in subcats
            ]

    if form.validate_on_submit():
        if form.sub_category.data == "Other (User Input)" and form.custom_category.data:
            category = form.custom_category.data
        else:
            category = form.sub_category.data

        expense.category = category
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
        main_cat = None
        for cat, data in expense_categories.items():
            if expense.category in data["subcategories"]:
                main_cat = cat
                break

        if main_cat:
            subcats = expense_categories[main_cat]["subcategories"]
            form.sub_category.choices = [("", "-- Select Sub Category --")] + [
                (sub, sub) for sub in subcats
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
    return render_template("add_expense.html", form=form, edit=True, expenses=expenses)


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
    ids_raw = request.form.getlist("ids")
    ids = [int(i) for i in ids_raw if i.isdigit()]
    if ids:
        Expense.query.filter(
            Expense.id.in_(ids),
            Expense.user_id == current_user.id,
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(f"Deleted {len(ids)} expense{'s' if len(ids) != 1 else ''}.", "success")
    days = request.form.get("days", "")
    return redirect(url_for("add_expense", days=days) if days else url_for("add_expense"))


@app.route("/bulk_edit_expenses", methods=["POST"])
@login_required
def bulk_edit_expenses():
    ids_raw = request.form.getlist("ids")
    ids = [int(i) for i in ids_raw if i.isdigit()]
    new_main = request.form.get("main_category", "").strip()
    new_sub = request.form.get("sub_category", "").strip()
    if ids and new_main and new_sub:
        is_essential = classify_essential(new_main, new_sub)
        exps = Expense.query.filter(
            Expense.id.in_(ids),
            Expense.user_id == current_user.id,
        ).all()
        for exp in exps:
            exp.category = new_sub
            exp.is_essential = is_essential
        db.session.commit()
        flash(f"Updated category for {len(exps)} expense{'s' if len(exps) != 1 else ''}.", "success")
    days = request.form.get("days", "")
    return redirect(url_for("add_expense", days=days) if days else url_for("add_expense"))


@app.route("/bulk_delete_income", methods=["POST"])
@login_required
def bulk_delete_income():
    ids_raw = request.form.getlist("ids")
    ids = [int(i) for i in ids_raw if i.isdigit()]
    if ids:
        Income.query.filter(
            Income.id.in_(ids),
            Income.user_id == current_user.id,
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(f"Deleted {len(ids)} income entr{'y' if len(ids) == 1 else 'ies'}.", "success")
    days = request.form.get("days", "")
    return redirect(url_for("add_income", days=days) if days else url_for("add_income"))


@app.route("/bulk_edit_income", methods=["POST"])
@login_required
def bulk_edit_income():
    ids_raw = request.form.getlist("ids")
    ids = [int(i) for i in ids_raw if i.isdigit()]
    new_source = request.form.get("source", "").strip()
    if ids and new_source:
        incs = Income.query.filter(
            Income.id.in_(ids),
            Income.user_id == current_user.id,
        ).all()
        for inc in incs:
            inc.source = new_source
        db.session.commit()
        flash(f"Updated source for {len(incs)} income entr{'y' if len(incs) == 1 else 'ies'}.", "success")
    days = request.form.get("days", "")
    return redirect(url_for("add_income", days=days) if days else url_for("add_income"))


@app.route("/subscriptions")
@login_required
def subscriptions():
    subs = detect_subscriptions(current_user.id)
    total_cost = sum(s["avg_amount"] for s in subs)
    # Enrich subscriptions with start/end date from the most recent expense
    for sub in subs:
        exps = sub.get("expenses", [])
        if exps:
            latest = max(exps, key=lambda e: e.date)
            sub["sub_start_date"] = latest.sub_start_date
            sub["sub_end_date"] = latest.sub_end_date
            sub["expense_id"] = latest.id
        else:
            sub["sub_start_date"] = None
            sub["sub_end_date"] = None
            sub["expense_id"] = None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return render_template(
        "subscriptions.html", subscriptions=subs, total_cost=total_cost, now=now
    )


@app.route("/goals")
@login_required
def goals():
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
        goal = Goal(
            user_id=current_user.id,
            name=form.name.data,
            target_amount=form.target_amount.data,
            monthly_savings=form.monthly_savings.data,
            target_date=form.target_date.data,
            priority=form.priority.data,
        )
        db.session.add(goal)
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
        goal.priority = form.priority.data
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
        # Add the new amount to existing saved amount instead of replacing
        additional_savings = form.saved_amount.data
        goal.saved_amount = goal.saved_amount + additional_savings
        db.session.commit()
        flash(
            f"Added ₹{additional_savings:,.0f} to your savings! Total saved: ₹{goal.saved_amount:,.0f}",
            "success",
        )
        return redirect(url_for("goal_detail", id=id))

    # Get spending reduction suggestions
    suggestions = get_spending_suggestions(current_user.id, goal)

    # Calculate timeline milestones
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

    remaining = goal.remaining_amount
    months = remaining / total_monthly

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


def make_chart(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110, transparent=True)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return img_b64


def make_chart_png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110, transparent=True)
    buf.seek(0)
    plt.close(fig)
    return buf


def _get_analysis_data(user_id):
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

    categories = {}
    for e in expenses_month:
        categories[e.category] = categories.get(e.category, 0) + e.amount

    monthly_spending = defaultdict(float)
    for exp in all_expenses:
        key = exp.date.strftime("%b %Y")
        monthly_spending[key] += exp.amount
    sorted_months = sorted(
        monthly_spending.keys(), key=lambda m: datetime.strptime(m, "%b %Y")
    )
    monthly_spending_ordered = {m: monthly_spending[m] for m in sorted_months}

    monthly_income = defaultdict(float)
    monthly_expense_all = defaultdict(float)
    for inc in all_incomes:
        monthly_income[inc.date_received.strftime("%b %Y")] += inc.amount
    for exp in all_expenses:
        monthly_expense_all[exp.date.strftime("%b %Y")] += exp.amount

    return (
        categories,
        monthly_spending_ordered,
        dict(monthly_income),
        dict(monthly_expense_all),
    )


def _chart_png_response(buf):
    resp = make_response(send_file(buf, mimetype="image/png"))
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


@app.route("/analysis/chart/dist")
@login_required
def analysis_chart_dist():
    dark_mode = request.cookies.get("darkMode") == "true"
    categories, _, _, _ = _get_analysis_data(current_user.id)
    fig_result = chart_expense_distribution(categories, dark_mode=dark_mode)
    if not fig_result:
        return ("", 204)
    buf = io.BytesIO(base64.b64decode(fig_result))
    return _chart_png_response(buf)


@app.route("/analysis/chart/cats")
@login_required
def analysis_chart_cats():
    dark_mode = request.cookies.get("darkMode") == "true"
    categories, _, _, _ = _get_analysis_data(current_user.id)
    fig_result = chart_category_breakdown(categories, dark_mode=dark_mode)
    if not fig_result:
        return ("", 204)
    buf = io.BytesIO(base64.b64decode(fig_result))
    return _chart_png_response(buf)


@app.route("/analysis/chart/trend")
@login_required
def analysis_chart_trend():
    dark_mode = request.cookies.get("darkMode") == "true"
    _, monthly_spending_ordered, _, _ = _get_analysis_data(current_user.id)
    fig_result = chart_monthly_trend(monthly_spending_ordered, dark_mode=dark_mode)
    if not fig_result:
        return ("", 204)
    buf = io.BytesIO(base64.b64decode(fig_result))
    return _chart_png_response(buf)


@app.route("/analysis/chart/inc_exp")
@login_required
def analysis_chart_inc_exp():
    dark_mode = request.cookies.get("darkMode") == "true"
    _, _, monthly_income, monthly_expense_all = _get_analysis_data(current_user.id)
    fig_result = chart_income_vs_expense(
        monthly_income, monthly_expense_all, dark_mode=dark_mode
    )
    if not fig_result:
        return ("", 204)
    buf = io.BytesIO(base64.b64decode(fig_result))
    return _chart_png_response(buf)


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
    wedges, texts, autotexts = ax.pie(
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
    for i, (m, v) in enumerate(zip(months, values)):
        ax.text(
            i,
            v + max(values) * 0.03,
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
    for bar, val in zip(bars, values[::-1]):
        ax.text(
            bar.get_width() + max(values) * 0.01,
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


@app.route("/analysis")
@login_required
def analysis():
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── Date-range filter ────────────────────────────────────────────
    dr = request.args.get(
        "dr", "this_month"
    )  # this_month | prev_month | 2months | 3months | 6months | custom
    custom_from = request.args.get("from", "")
    custom_to = request.args.get("to", "")

    if dr == "prev_month":
        first_this = datetime(now.year, now.month, 1)
        date_to = first_this - timedelta(seconds=1)
        date_from = datetime(date_to.year, date_to.month, 1)
        range_label = date_from.strftime("%B %Y")
    elif dr == "2months":
        date_from = datetime(now.year, now.month, 1) - timedelta(days=60)
        date_from = datetime(date_from.year, date_from.month, 1)
        date_to = now
        range_label = "Past 2 Months"
    elif dr == "3months":
        date_from = datetime(now.year, now.month, 1) - timedelta(days=90)
        date_from = datetime(date_from.year, date_from.month, 1)
        date_to = now
        range_label = "Past 3 Months"
    elif dr == "6months":
        date_from = datetime(now.year, now.month, 1) - timedelta(days=180)
        date_from = datetime(date_from.year, date_from.month, 1)
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

    total_income = sum(
        i.amount
        for i in Income.query.filter(
            Income.user_id == current_user.id,
            Income.date_received >= date_from,
            Income.date_received <= date_to,
        ).all()
    )
    total_spent = sum(e.amount for e in expenses_range)
    essential = sum(e.amount for e in expenses_range if e.is_essential)
    non_essential = total_spent - essential

    categories = {}
    for e in expenses_range:
        categories[e.category] = categories.get(e.category, 0) + e.amount

    days_in_range = max((date_to - date_from).days + 1, 1)
    burn_rate = total_spent / days_in_range

    has_data = bool(expenses_range) or total_income > 0

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


# ─────────────────────────────────────────────────────────────
#  Bank Statement Parser
# ─────────────────────────────────────────────────────────────

_DATE_FMTS = [
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %b %y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d/%b/%Y",
    "%d/%b/%y",
]


def _parse_date(s):
    s = s.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _clean_amount(s):
    s = re.sub(r"[₹,\s]", "", str(s)).strip()
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _make_txn(date_obj, desc, amount, txn_type):
    return {
        "date": date_obj.strftime("%Y-%m-%d"),
        "description": desc.strip()[:200],
        "amount": round(amount, 2),
        "type": txn_type,
        "sub_cat": "Bank Import",
        "main_cat": "Other Expenses" if txn_type == "expense" else "Other Income",
        "subject": desc.strip()[:200],
    }


def _detect_columns(headers):
    """Return (date_col, desc_col, debit_col, credit_col) indices or None."""
    h = [str(x).lower().strip() for x in headers]
    date_kw = ["date", "txn date", "value date", "transaction date", "posting date"]
    desc_kw = [
        "description",
        "narration",
        "particulars",
        "remarks",
        "details",
        "transaction remarks",
        "transaction details",
    ]
    debit_kw = [
        "debit",
        "withdrawal",
        "dr",
        "debit amount",
        "withdrawal amount",
        "amount (dr)",
    ]
    credit_kw = [
        "credit",
        "deposit",
        "cr",
        "credit amount",
        "deposit amount",
        "amount (cr)",
    ]
    amount_kw = ["amount", "net amount"]

    def find(kws):
        for k in kws:
            for i, hh in enumerate(h):
                if k in hh:
                    return i
        return None

    di = find(date_kw)
    ni = find(desc_kw)
    dbi = find(debit_kw)
    cri = find(credit_kw)
    ami = find(amount_kw) if dbi is None else None
    if di is None or ni is None:
        return None
    return di, ni, dbi, cri, ami


def _rows_to_txns(rows, header_idx):
    headers = rows[header_idx]
    result = _detect_columns(headers)
    if result is None:
        return []
    di, ni, dbi, cri, ami = result
    txns = []
    for row in rows[header_idx + 1 :]:
        if len(row) <= max(x for x in [di, ni, dbi, cri, ami] if x is not None):
            continue
        date_val = _parse_date(str(row[di]))
        if date_val is None:
            continue
        desc = str(row[ni]).strip()
        if not desc or desc.lower() in ("", "nan", "none"):
            continue
        debit = _clean_amount(row[dbi]) if dbi is not None and dbi < len(row) else None
        credit = _clean_amount(row[cri]) if cri is not None and cri < len(row) else None
        amount = _clean_amount(row[ami]) if ami is not None and ami < len(row) else None
        if debit and debit > 0:
            txns.append(_make_txn(date_val, desc, debit, "expense"))
        if credit and credit > 0:
            txns.append(_make_txn(date_val, desc, credit, "income"))
        if amount and dbi is None and cri is None:
            t = "income" if amount > 0 else "expense"
            txns.append(_make_txn(date_val, desc, abs(amount), t))
    return txns


def _decrypt_office_file(file_bytes, password):
    """Decrypt a password-protected .xls/.xlsx file using msoffcrypto.
    Returns decrypted bytes, or raises an exception if decryption fails."""
    enc_file = io.BytesIO(file_bytes)
    dec_file = io.BytesIO()
    office_file = msoffcrypto.OfficeFile(enc_file)
    office_file.load_key(password=password)
    office_file.decrypt(dec_file)
    dec_file.seek(0)
    return dec_file.read()


def _is_encrypted_office(file_bytes):
    """Return True if the file appears to be an encrypted Office file."""
    try:
        enc_file = io.BytesIO(file_bytes)
        office_file = msoffcrypto.OfficeFile(enc_file)
        return office_file.is_encrypted()
    except Exception:
        return False


def parse_bank_statement_csv(content_bytes):
    text = content_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    for i, row in enumerate(rows):
        if _detect_columns(row):
            return _rows_to_txns(rows, i)
    return []


def parse_bank_statement_xlsx(content_bytes):
    """Parse an .xlsx file using openpyxl."""
    wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        cells = [str(c) if c is not None else "" for c in row]
        if any(c.strip() for c in cells):
            rows.append(cells)
    for i, row in enumerate(rows):
        if _detect_columns(row):
            return _rows_to_txns(rows, i)
    return []


def parse_bank_statement_xls(content_bytes):
    """Parse an .xls (legacy Excel 97-2003) file using xlrd."""
    wb = xlrd.open_workbook(file_contents=content_bytes)
    ws = wb.sheet_by_index(0)
    rows = []
    for rx in range(ws.nrows):
        cells = []
        for cx in range(ws.ncols):
            cell = ws.cell(rx, cx)
            if cell.ctype == xlrd.XL_CELL_DATE:
                try:
                    dt = xlrd.xldate_as_datetime(cell.value, wb.datemode)
                    cells.append(dt.strftime("%d/%m/%Y"))
                except Exception:
                    cells.append(str(cell.value))
            elif cell.ctype == xlrd.XL_CELL_NUMBER:
                v = cell.value
                cells.append(str(int(v)) if v == int(v) else str(v))
            else:
                cells.append(str(cell.value).strip())
        if any(c.strip() for c in cells):
            rows.append(cells)
    for i, row in enumerate(rows):
        if _detect_columns(row):
            return _rows_to_txns(rows, i)
    return []


def parse_bank_statement_pdf(content_bytes):
    DATE_RE = re.compile(
        r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}[/\-][A-Za-z]{3}[/\-]\d{2,4})\b"
    )
    AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{2,3})*(?:\.\d{2})?)")
    txns = []
    with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
        for page in pdf.pages:
            # Try table extraction first
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                rows = [[str(c) if c else "" for c in row] for row in table]
                for i, row in enumerate(rows):
                    if _detect_columns(row):
                        txns.extend(_rows_to_txns(rows, i))
                        break
            if txns:
                continue
            # Fallback: line-by-line text parsing
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                dates = DATE_RE.findall(line)
                if not dates:
                    continue
                date_obj = _parse_date(dates[0])
                if not date_obj:
                    continue
                amounts = AMOUNT_RE.findall(line)
                if not amounts:
                    continue
                # Remove date strings from line to get description
                desc = DATE_RE.sub("", line)
                for a in amounts:
                    desc = desc.replace(a, "")
                desc = re.sub(r"\s+", " ", desc).strip(" ,.-/")
                if not desc:
                    desc = "Bank transaction"
                # Last amount is usually balance, second-last is txn amount
                if len(amounts) >= 2:
                    amt = _clean_amount(amounts[-2])
                else:
                    amt = _clean_amount(amounts[-1])
                if amt and amt > 0:
                    # Heuristic: look for Dr/Cr keywords
                    low = line.lower()
                    if re.search(r"\bcr\b|\bcredit\b|\bdeposit\b", low):
                        txns.append(_make_txn(date_obj, desc, amt, "income"))
                    else:
                        txns.append(_make_txn(date_obj, desc, amt, "expense"))
    seen = set()
    unique = []
    for t in txns:
        key = (t["date"], t["amount"], t["type"])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def parse_bank_statement(file_bytes, filename, password=None):
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return parse_bank_statement_pdf(file_bytes)
    elif ext in ("xlsx", "xls"):
        data = file_bytes
        if password:
            try:
                data = _decrypt_office_file(file_bytes, password)
            except Exception:
                raise ValueError("Wrong password or unable to decrypt the file.")
        elif _is_encrypted_office(file_bytes):
            raise ValueError(
                "This file is password-protected. Please enter the statement password."
            )
        if ext == "xls":
            return parse_bank_statement_xls(data)
        else:
            return parse_bank_statement_xlsx(data)
    elif ext == "csv":
        return parse_bank_statement_csv(file_bytes)
    return []


# ─────────────────────────────────────────────────────────────
#  IMAP Email Parsing Helpers
# ─────────────────────────────────────────────────────────────

IMAP_PRESETS = {
    "gmail":   {"host": "imap.gmail.com",           "port": 993},
    "outlook": {"host": "imap-mail.outlook.com",    "port": 993},
    "yahoo":   {"host": "imap.mail.yahoo.com",      "port": 993},
    "hotmail": {"host": "imap-mail.outlook.com",    "port": 993},
    "icloud":  {"host": "imap.mail.me.com",         "port": 993},
}

FINANCIAL_SUBJECT_KEYWORDS = [
    "transaction", "payment", "purchase", "receipt", "order", "invoice",
    "debit", "credit", "charged", "statement", "bill", "transfer",
    "alert", "notification", "confirmation", "refund", "deposit",
    "subscription", "auto-pay", "autopay", "due", "amount",
]

FINANCIAL_SENDER_KEYWORDS = [
    "bank", "paypal", "paytm", "stripe", "amazon", "netflix", "spotify",
    "apple", "google", "microsoft", "hulu", "prime", "uber", "lyft",
    "razorpay", "hdfc", "sbi", "icici", "axis", "netsuite", "venmo",
    "cashapp", "zelle", "chase", "citibank", "wells", "fargo",
]

CATEGORY_KEYWORD_MAP = [
    (["grocery", "supermarket", "safeway", "kroger", "walmart", "costco", "whole foods", "amazon fresh", "trader joe"], ("Food & Groceries", "Groceries")),
    (["restaurant", "dining", "bistro", "cafe", "diner", "eatery", "sushi", "pizza", "burger"], ("Food & Groceries", "Dining Out")),
    (["coffee", "starbucks", "dunkin", "costa"], ("Food & Groceries", "Coffee Shops")),
    (["food delivery", "doordash", "grubhub", "ubereats", "zomato", "swiggy"], ("Food & Groceries", "Food Delivery")),
    (["fast food", "mcdonald", "kfc", "subway", "domino", "taco bell", "wendy", "burger king"], ("Food & Groceries", "Fast Food")),
    (["uber", "lyft", "taxi", "rideshare", "ola", "grab"], ("Transportation", "Taxi/Rideshare")),
    (["fuel", "gas station", "petrol", "shell", "bp ", "chevron", "exxon"], ("Transportation", "Fuel")),
    (["metro", "bus", "transit", "train", "subway pass", "rail"], ("Transportation", "Public Transport")),
    (["netflix", "hulu", "disney+", "hbo", "prime video", "apple tv", "peacock", "paramount"], ("Entertainment", "Streaming Services")),
    (["spotify", "apple music", "tidal", "deezer", "pandora", "youtube music"], ("Entertainment", "Music Streaming")),
    (["gym", "fitness", "planet fitness", "equinox", "crunch"], ("Personal & Lifestyle", "Gym Membership")),
    (["electricity", "electric", "power bill"], ("Utilities", "Electricity")),
    (["water bill"], ("Utilities", "Water")),
    (["internet", "broadband", "comcast", "xfinity", "att", "verizon", "spectrum"], ("Utilities", "Internet")),
    (["mobile", "phone bill", "t-mobile", "sprint", "cricket"], ("Utilities", "Mobile Phone")),
    (["amazon", "ebay", "etsy", "shopify", "online shopping", "shop", "purchase from"], ("Shopping", "Online Shopping")),
    (["doctor", "clinic", "hospital", "medical", "health", "dental", "pharmacy", "prescription"], ("Healthcare", "Doctor Visits")),
    (["insurance", "policy", "premium"], ("Insurance", "Health Insurance")),
    (["school", "tuition", "university", "college", "course", "udemy", "coursera"], ("Education", "School Tuition")),
    (["rent", "lease", "landlord"], ("Housing", "Rent")),
    (["salary", "payroll", "wages", "paycheck"], ("Income", "Salary")),
    (["refund", "cashback", "reward"], ("Income", "Refund")),
]


def _ei_decode_header(raw):
    parts = decode_header(raw or "")
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="ignore")
        else:
            result += str(part)
    return result


def _ei_extract_text(msg):
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            decoded = payload.decode("utf-8", errors="ignore")
            if ctype == "text/plain":
                plain += decoded
            elif ctype == "text/html":
                html += decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = payload.decode("utf-8", errors="ignore")
            if msg.get_content_type() == "text/html":
                html = decoded
            else:
                plain = decoded
    if html and not plain.strip():
        soup = BeautifulSoup(html, "html.parser")
        plain = soup.get_text(separator=" ", strip=True)
    return plain


def _ei_parse_amount(text):
    patterns = [
        r'\$\s*([\d,]+\.?\d*)',
        r'USD\s+([\d,]+\.?\d*)',
        r'Rs\.?\s*([\d,]+\.?\d*)',
        r'INR\s+([\d,]+\.?\d*)',
        r'(?:amount|total|charged|debit|credit)[:\s]+(?:of\s+)?\$?\s*([\d,]+\.?\d*)',
        r'payment of\s+\$?\s*([\d,]+\.?\d*)',
        r'\b([\d,]{1,10}\.\d{2})\b',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if 0.01 <= val <= 999999:
                    return round(val, 2)
            except ValueError:
                continue
    return None


def _ei_guess_category(subject, body):
    combined = (subject + " " + body).lower()
    for keywords, (main_cat, sub_cat) in CATEGORY_KEYWORD_MAP:
        if any(kw in combined for kw in keywords):
            return main_cat, sub_cat
    return "Other Expenses", "Miscellaneous"


def _ei_is_income(subject, body):
    combined = (subject + " " + body).lower()
    income_signals = [
        "received", "credited to your account", "deposit", "refund", "cashback",
        "salary", "payroll", "transfer received", "payment received", "reward",
    ]
    return any(s in combined for s in income_signals)


def _ei_is_financial(subject, from_addr):
    sub_lower  = subject.lower()
    from_lower = from_addr.lower()
    if any(kw in sub_lower  for kw in FINANCIAL_SUBJECT_KEYWORDS):
        return True
    if any(kw in from_lower for kw in FINANCIAL_SENDER_KEYWORDS):
        return True
    return False


def scan_imap_emails(host, port, email_addr, password, days=30):
    ctx  = ssl.create_default_context()
    mail = imaplib.IMAP4_SSL(host, int(port), ssl_context=ctx)
    mail.login(email_addr, password)
    mail.select("INBOX")

    since_date = (datetime.utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, message_ids = mail.search(None, f"SINCE {since_date}")
    msg_ids = message_ids[0].split()
    msg_ids = msg_ids[-300:][::-1]

    transactions = []
    seen_ids = set()

    for mid in msg_ids:
        try:
            _, msg_data = mail.fetch(mid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            subject   = _ei_decode_header(msg.get("Subject", ""))
            from_addr = msg.get("From", "")
            date_str  = msg.get("Date", "")
            msg_id    = msg.get("Message-ID", mid.decode()).strip("<> ")

            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            if not _ei_is_financial(subject, from_addr):
                continue

            body   = _ei_extract_text(msg)
            amount = _ei_parse_amount(subject + " " + body[:3000])
            if not amount:
                continue

            is_income = _ei_is_income(subject, body)
            main_cat, sub_cat = _ei_guess_category(subject, body)
            if is_income:
                main_cat, sub_cat = "Income", "Transfer/Other"

            try:
                txn_date = parsedate_to_datetime(date_str).strftime("%Y-%m-%d")
            except Exception:
                txn_date = datetime.utcnow().strftime("%Y-%m-%d")

            transactions.append({
                "msg_id":      msg_id,
                "subject":     subject[:120],
                "from":        from_addr[:100],
                "date":        txn_date,
                "amount":      amount,
                "type":        "income" if is_income else "expense",
                "main_cat":    main_cat,
                "sub_cat":     sub_cat,
                "description": subject[:200],
            })
        except Exception:
            continue

    mail.logout()
    return transactions


# ─────────────────────────────────────────────────────────────
#  Import Routes (Email + Bank Statement)
# ─────────────────────────────────────────────────────────────

@app.route("/email-import")
@login_required
def email_import():
    imap_connected = "imap_config" in session
    return render_template("email_import.html", imap_connected=imap_connected)


@app.route("/email-import/connect", methods=["POST"])
@login_required
def email_import_connect():
    data       = request.get_json(force=True)
    host       = data.get("host", "").strip()
    port       = int(data.get("port", 993))
    email_addr = data.get("email", "").strip()
    password   = data.get("password", "").strip()

    if not all([host, email_addr, password]):
        return jsonify({"success": False, "message": "All fields are required."})

    try:
        ctx  = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
        mail.login(email_addr, password)
        mail.logout()
        session["imap_config"] = {
            "host": host, "port": port,
            "email": email_addr, "password": password,
        }
        return jsonify({"success": True, "message": f"Connected to {host} successfully!"})
    except imaplib.IMAP4.error as e:
        return jsonify({"success": False, "message": f"Authentication failed — check your email/password or App Password. ({e})"})
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
        return jsonify({"success": False, "message": "Not connected to any email account."})
    days = int(request.get_json(force=True).get("days", 30))
    try:
        transactions = scan_imap_emails(
            cfg["host"], cfg["port"], cfg["email"], cfg["password"], days=days
        )
        return jsonify({"success": True, "transactions": transactions, "count": len(transactions)})
    except imaplib.IMAP4.error as e:
        session.pop("imap_config", None)
        return jsonify({"success": False, "message": f"Email session expired — please reconnect. ({e})"})
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
            amount   = float(txn["amount"])
            desc     = txn.get("description", "")[:200]
            txn_type = txn.get("type", "expense")

            if txn_type == "income":
                inc = Income(
                    user_id=current_user.id,
                    source=txn.get("sub_cat", "Email Import"),
                    amount=amount,
                    date_received=txn_date,
                    description=desc,
                )
                db.session.add(inc)
            else:
                exp = Expense(
                    user_id=current_user.id,
                    category="Uncategorized",
                    amount=amount,
                    date=txn_date,
                    description=desc,
                    is_essential=False,
                    is_subscription=False,
                )
                db.session.add(exp)
            imported_count += 1
        except Exception:
            continue
    db.session.commit()
    return jsonify({"success": True, "imported": imported_count})


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

        # ── Handle ZIP: extract all parseable statement files inside ──
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
                                "message": "No supported statement file found inside the ZIP (expected PDF, Excel, or CSV).",
                            }
                        )
                    all_txns = []
                    parsed_files = []
                    needs_pw = False
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
                            continue
                        except Exception:
                            continue
                    if not all_txns:
                        if needs_pw:
                            return jsonify(
                                {
                                    "success": False,
                                    "needs_password": True,
                                    "message": "One or more files inside the ZIP are password-protected. Please enter the statement password.",
                                }
                            )
                        return jsonify(
                            {
                                "success": False,
                                "message": "No transactions could be detected in any file inside the ZIP. Make sure it contains a standard bank statement.",
                            }
                        )
                    # Deduplicate by (date, amount, type)
                    seen = set()
                    unique = []
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

        # ── Direct file upload ──
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
                exists = Income.query.filter_by(
                    user_id=current_user.id,
                    source="Bank Import",
                    amount=amount,
                    date_received=txn_date,
                    description=desc,
                ).first()
                if exists:
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
                exists = Expense.query.filter_by(
                    user_id=current_user.id,
                    amount=amount,
                    date=txn_date,
                    description=desc,
                ).first()
                if exists:
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
    """Re-run auto-categorization on all 'Uncategorized' expenses for this user."""
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
