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

essential_keywords = []
for _main_cat, _data in expense_categories.items():
    _classification_map = _data.get("classification", {})
    if isinstance(_classification_map, dict):
        for _subcat, _classification in _classification_map.items():
            if _classification == "need":
                essential_keywords.append(_subcat.lower())
                if _main_cat.lower() not in essential_keywords:
                    essential_keywords.append(_main_cat.lower())


def auto_categorize_transaction(description):
    d = (description or "").upper()
    merchant = ""
    if d.startswith("UPI-"):
        parts = description.split("-")
        if len(parts) > 1:
            merchant = parts[1].upper()
    note = d.split("-")[-1].strip() if "-" in d else ""
    combined = d + " " + merchant + " " + note

    def hit(*words):
        return any(w in combined for w in words)

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

    if hit("DINNER", "LUNCH", "BREAKFAST", "SNACK", "COFFEE", "CHAI ", "TEA "):
        return ("Dining Out", False, False)

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

    if hit("PARKING", "TOLL PLAZA", "FASTAG", "IHMCL", "NHAI"):
        return ("Parking Fees", True, False)

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

    if hit("WATER BILL", "WATER SUPPLY", "BWSSB", "WATER TAX", "WATER BOARD"):
        return ("Water", True, False)

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

    if hit("PVR", "INOX", "CINEPOLIS", "CARNIVAL CINEMA", "BOOKMYSHOW", "MOVIE TICKET"):
        return ("Movies", False, False)

    if hit("STEAM", "XBOX", "PLAYSTATION", "GOOGLE PLAY GAMES", "PUBG", "GAMING"):
        return ("Gaming", False, False)

    if hit(
        "IMAGICA",
        "WONDERLA",
        "ESSEL WORLD",
        "WATER PARK",
        "THEME PARK",
        "AMUSEMENT PARK",
    ):
        return ("Theme Parks", False, False)

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

    if hit(
        "HOUSE RENT",
        "FLAT RENT",
        "APARTMENT RENT",
        "LANDLORD",
        "RENTAL PAYMENT",
        "PROPERTY TAX",
    ):
        return ("Rent", True, False)

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

    if hit(
        "HAIR CUTTING", "BARBER", "HAIR SALON", "STYLO HAIR", "HAIR CUT", "GROOMING"
    ):
        return ("Haircuts", False, False)

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

    if hit("UPI-MR ", "UPI-MS ", "UPI-MISS ", "UPI-MRS ", "UPI-DR "):
        return ("Other (User Input)", False, False)

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
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in essential_keywords)
