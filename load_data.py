# ===== Step 0: build the Northbridge Bank (UK) synthetic loans database =====
# Northbridge Bank is fictional. Every row below is made up. No employer or customer data.
#
# What this program does, in order:
#   1. Deletes any old copy of the database, so we always start clean.
#   2. Creates 20 empty tables (the DDL), with ID columns and the links between tables.
#   3. Fills them with made-up UK mortgage and consumer loan data, from a fixed recipe
#      (same "random seed"), so every run gives exactly the same data.
#   4. Writes the data dictionary (a description for every table and column), with about
#      10% of descriptions deliberately missing or vague, as in real banks.
#   5. Writes the hidden answer key (17 test terms) in a separate "eval" folder.
#      The AI and the MCP server never read that folder.
#   6. Checks every link and code, then prints a row count per table.
#
# Run on the laptop:   python load_data.py
# Run in Colab:        mount Google Drive first, then
#                      !DATA_DIR=/content/drive/MyDrive/northbridge python load_data.py

import csv, os, random, sqlite3
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent / "data"))
EVAL_DIR = DATA_DIR / "eval"                      # hidden from the AI
DB_PATH = DATA_DIR / "northbridge_uk_loans.db"
DICT_PATH = DATA_DIR / "data_dictionary.csv"
TODAY = date(2026, 10, 31)                         # the "reporting date" of the data
BASE_RATE = 4.00                                   # assumed central bank base rate, for pricing


# ---------- 1. Start clean ----------
DATA_DIR.mkdir(parents=True, exist_ok=True)
EVAL_DIR.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
db = sqlite3.connect(DB_PATH)
db.execute("PRAGMA foreign_keys = ON")             # the database itself refuses broken links


# ---------- 2. The DDL: 20 tables, with keys and links ----------
db.executescript("""
CREATE TABLE ref_codes (
  code_set TEXT NOT NULL, code TEXT NOT NULL, meaning TEXT NOT NULL,
  PRIMARY KEY (code_set, code));

CREATE TABLE products (
  product_id INTEGER PRIMARY KEY, product_name TEXT NOT NULL, loan_type TEXT NOT NULL, brand TEXT);

CREATE TABLE brokers (
  broker_id INTEGER PRIMARY KEY, broker_name TEXT NOT NULL, region TEXT);

CREATE TABLE borrowers (
  borrower_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, applicant_role TEXT, age_band TEXT,
  uk_resident_flag TEXT, employment TEXT, relationship_status TEXT);

CREATE TABLE borrower_additional (
  borrower_id INTEGER PRIMARY KEY REFERENCES borrowers(borrower_id),
  dependants INTEGER, first_time_buyer_flag TEXT, second_applicant_flag TEXT);

CREATE TABLE borrower_income (
  borrower_id INTEGER PRIMARY KEY REFERENCES borrowers(borrower_id),
  income_date TEXT, gross_income_gbp REAL, income_verification TEXT,
  debt_to_income_pct REAL, affordability_pass_flag TEXT);

CREATE TABLE credit_bureau (
  bureau_id INTEGER PRIMARY KEY, borrower_id INTEGER NOT NULL REFERENCES borrowers(borrower_id),
  score_date TEXT, bureau_score INTEGER, ccj_count INTEGER, bankruptcy_flag TEXT, prior_arrears_flag TEXT);

CREATE TABLE loans (
  loan_id INTEGER PRIMARY KEY, loan_type TEXT NOT NULL,
  borrower_id INTEGER NOT NULL REFERENCES borrowers(borrower_id),
  product_id INTEGER NOT NULL REFERENCES products(product_id),
  pool_id TEXT, originator TEXT, servicer TEXT, pool_cutoff_date TEXT);

CREATE TABLE applications (
  application_id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL UNIQUE REFERENCES loans(loan_id),
  application_date TEXT, channel TEXT, broker_id INTEGER REFERENCES brokers(broker_id),
  decision TEXT, policy_exception_flag TEXT);

CREATE TABLE mortgage_loans (
  loan_id INTEGER PRIMARY KEY REFERENCES loans(loan_id),
  product_code TEXT, fca_regulated_flag TEXT, original_amount_gbp REAL, balance_gbp REAL,
  ltv_orig_pct REAL, ltv_curr_pct REAL, repayment_type TEXT, rate_type TEXT,
  current_rate_pct REAL, margin_over_base_pct REAL, reversion_rate_pct REAL,
  fixed_rate_end_date TEXT, start_date TEXT, maturity_date TEXT, seasoning_months INTEGER, erc_flag TEXT);

CREATE TABLE consumer_loans (
  loan_id INTEGER PRIMARY KEY REFERENCES loans(loan_id),
  purpose_cd TEXT, cca_regulated_flag TEXT, amount_gbp REAL, term_months INTEGER,
  nominal_rate_pct REAL, apr_pct REAL, monthly_instalment_gbp REAL, total_amount_payable_gbp REAL,
  total_charge_for_credit_gbp REAL, agreement_date TEXT, cooling_off_end_date TEXT,
  early_settlement_charge_gbp REAL, secured_flag TEXT, maturity_date TEXT, seasoning_months INTEGER,
  status_cd TEXT);

CREATE TABLE interest_rate_history (
  loan_id INTEGER NOT NULL REFERENCES loans(loan_id), effective_date TEXT NOT NULL,
  rate_pct REAL, rate_type TEXT, PRIMARY KEY (loan_id, effective_date));

CREATE TABLE properties (
  property_id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL UNIQUE REFERENCES mortgage_loans(loan_id),
  postcode TEXT, region TEXT, property_type TEXT, tenure TEXT, charge_rank INTEGER,
  epc_rating TEXT, occupant_type TEXT, occ_rel_cd TEXT);

CREATE TABLE collateral_valuations (
  valuation_id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL REFERENCES properties(property_id),
  valuation_date TEXT, valuation_gbp REAL, valuation_method TEXT, is_origination TEXT);

CREATE TABLE insurance (
  policy_id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL REFERENCES properties(property_id),
  cover_type TEXT, start_date TEXT);

CREATE TABLE loan_performance_monthly (
  loan_id INTEGER NOT NULL REFERENCES loans(loan_id), month_end TEXT NOT NULL,
  balance_gbp REAL, arrears_balance_gbp REAL, months_in_arrears INTEGER, dpd INTEGER,
  default_flag TEXT, default_date TEXT, PRIMARY KEY (loan_id, month_end));

CREATE TABLE collections (
  action_id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL REFERENCES loans(loan_id),
  action_type TEXT, action_date TEXT, days_since_contact INTEGER);

CREATE TABLE forbearance (
  case_id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL REFERENCES loans(loan_id),
  forbearance_type TEXT, start_date TEXT, end_date TEXT);

CREATE TABLE recoveries (
  loan_id INTEGER PRIMARY KEY REFERENCES loans(loan_id),
  recovery_date TEXT, loss_amount_gbp REAL, recovered_gbp REAL);

CREATE TABLE funding_encumbrance (
  loan_id INTEGER PRIMARY KEY REFERENCES loans(loan_id),
  pledged_to TEXT, pledge_date TEXT, boe_eligible_flag TEXT);
""")


# ---------- 3. Fill the tables with made-up UK data ----------
random.seed(7)
rows = {}   # table name -> list of rows, inserted at the end


def add(table, *values):
    rows.setdefault(table, []).append(values)


def d(x):
    return x.isoformat() if x else None


def months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month)


def add_months(x, n):
    y, m = divmod(x.month - 1 + n, 12)
    return date(x.year + y, m + 1, min(x.day, 28))


# The codebook: what every code means
codes = [
    ("PRODUCT", "BTL", "Buy-to-let mortgage"), ("PRODUCT", "RES", "Residential owner-occupied mortgage"),
    ("RATE_TYPE", "FIX", "Fixed rate"), ("RATE_TYPE", "TRK", "Tracker rate (base rate plus a margin)"),
    ("RATE_TYPE", "SVR", "Standard variable rate"),
    ("REPAY", "REP", "Capital and interest repayment"), ("REPAY", "IO", "Interest only"),
    ("REPAY", "PP", "Part and part (part repayment, part interest only)"),
    ("PURPOSE", "CAR", "Car purchase"), ("PURPOSE", "HI", "Home improvement"),
    ("PURPOSE", "DC", "Debt consolidation"), ("PURPOSE", "OTH", "Other purpose"),
    ("STATUS", "CUR", "Up to date"), ("STATUS", "ARR", "In arrears"), ("STATUS", "DEF", "In default"),
    ("OCC_REL", "F1", "Tenant is a family member of the borrower: sibling"),
    ("OCC_REL", "F2", "Tenant is a family member of the borrower: parent or child"),
    ("OCC_REL", "NR", "Tenant is not related to the borrower"),
    ("TENURE", "FH", "Freehold"), ("TENURE", "LH", "Leasehold"),
    ("VAL_METHOD", "FULL", "Full internal inspection by a surveyor"),
    ("VAL_METHOD", "DESKTOP", "Desktop valuation by a surveyor"),
    ("VAL_METHOD", "AVM", "Automated valuation model"),
    ("VAL_METHOD", "INDEXED", "Earlier valuation updated with a house price index"),
    ("PLEDGE", "UK_COVERED_BOND", "Pledged to the bank's regulated covered bond programme"),
    ("PLEDGE", "RMBS", "Sold into a residential mortgage-backed securitisation"),
    ("PLEDGE", "BOE_PREPOSITIONED", "Pre-positioned with the central bank as loan collateral"),
    ("PLEDGE", "NONE", "Not pledged"),
    ("INCOME_VER", "VERIFIED", "Income checked with payslips, accounts or bank statements"),
    ("INCOME_VER", "SELF_CERT", "Income stated by the borrower and not checked"),
    ("FORB", "PAYMENT_HOLIDAY", "Payments paused for an agreed period"),
    ("FORB", "REDUCED_PAYMENT", "Lower payments for an agreed period"),
    ("FORB", "TERM_EXTENSION", "Loan term made longer"),
    ("COLL_ACTION", "CALL", "Phone call to the borrower"), ("COLL_ACTION", "LETTER", "Arrears letter"),
    ("COLL_ACTION", "VISIT", "Field visit"), ("COLL_ACTION", "DCA", "Passed to a debt collection agency"),
    ("CHANNEL", "DIRECT", "Applied directly to the bank"), ("CHANNEL", "BROKER", "Introduced by a broker"),
    ("EMPLOYMENT", "EMPLOYED", "Employed"), ("EMPLOYMENT", "SELF_EMPLOYED", "Borrower is self-employed"),
    ("EMPLOYMENT", "RETIRED", "Retired"),
]
for c in codes:
    add("ref_codes", *c)

products = [
    (1, "Residential 2-year fixed", "MORTGAGE", "Northbridge"),
    (2, "Residential 5-year fixed", "MORTGAGE", "Northbridge"),
    (3, "Residential tracker", "MORTGAGE", "Northbridge"),
    (4, "Buy-to-let 2-year fixed", "MORTGAGE", "Northbridge Lets"),
    (5, "Interest-only buy-to-let 5-year fixed", "MORTGAGE", "Northbridge Lets"),   # trap for "interest only"
    (6, "Personal loan", "CONSUMER", "Northbridge"),
    (7, "Car loan", "CONSUMER", "Northbridge"),
    (8, "Home improvement loan", "CONSUMER", "Northbridge"),
]
for p in products:
    add("products", *p)

regions = ["London", "South East", "South West", "East of England", "West Midlands", "East Midlands",
           "North West", "North East", "Yorkshire and the Humber", "Wales", "Scotland", "Northern Ireland"]
for b in range(1, 16):
    add("brokers", b, f"Broker {b} Mortgage Advice", random.choice(regions))

# Borrowers, their extra details, income and bureau scores
for b in range(1, 301):
    add("borrowers", b, f"Borrower {b}", random.choices(["PRIMARY", "JOINT"], [80, 20])[0],
        random.choice(["18-29", "30-44", "45-59", "60+"]), random.choices(["Y", "N"], [97, 3])[0],
        random.choices(["EMPLOYED", "SELF_EMPLOYED", "RETIRED"], [70, 20, 10])[0],
        random.choice(["MARRIED", "SINGLE", "PARTNER"]))
    add("borrower_additional", b, random.choice([0, 0, 1, 2, 3]),
        random.choices(["Y", "N"], [25, 75])[0], random.choices(["Y", "N"], [30, 70])[0])

# Loans: mortgages are 1-200, consumer loans 1001-1250, so the IDs never clash
mortgage_ids = list(range(1, 201))
consumer_ids = list(range(1001, 1251))
loan_start = {}
loan_borrower = {}

for l in mortgage_ids:
    btl = random.random() < 0.6
    product_id = random.choice([4, 4, 5]) if btl else random.choice([1, 2, 3])
    start = date(random.randint(2006, 2025), random.randint(1, 12), 1)
    loan_start[l], loan_borrower[l] = start, random.randint(1, 300)
    pool = random.choice(["NB-MORT-POOL-1", "NB-MORT-POOL-2"])
    add("loans", l, "MORTGAGE", loan_borrower[l], product_id, pool, "Northbridge Bank plc",
        "Northbridge Servicing Ltd", "2026-10-31")

for l in consumer_ids:
    purpose = random.choice(["CAR", "HI", "DC", "OTH"])
    product_id = {"CAR": 7, "HI": 8}.get(purpose, 6)
    start = date(random.randint(2021, 2026), random.randint(1, 9), 1)
    loan_start[l], loan_borrower[l] = start, random.randint(1, 300)
    add("loans", l, "CONSUMER", loan_borrower[l], product_id, "NB-CONS-POOL-1", "Northbridge Bank plc",
        "Northbridge Servicing Ltd", "2026-10-31")
    loan_start[(l, "purpose")] = purpose

# Applications (one per loan); brokers only on mortgages
for n, l in enumerate(mortgage_ids + consumer_ids, start=1):
    app_date = loan_start[l] - timedelta(days=random.randint(20, 60))
    broker = random.choice([None, None] + list(range(1, 16))) if l < 1000 else None
    add("applications", n, l, d(app_date), "BROKER" if broker else "DIRECT", broker, "APPROVED",
        random.choices(["Y", "N"], [5, 95])[0])

# Income (one current record per borrower) and bureau scores (at first application and today)
first_app = {}
for l in mortgage_ids + consumer_ids:
    b = loan_borrower[l]
    first_app[b] = min(first_app.get(b, loan_start[l]), loan_start[l])
bureau_id = 1
for b in range(1, 301):
    started = first_app.get(b, date(2020, 1, 1))
    self_cert = started < date(2014, 4, 26) and random.random() < 0.5   # self-cert ended in 2014
    income = random.randint(18, 160) * 1000
    add("borrower_income", b, d(started), income, "SELF_CERT" if self_cert else "VERIFIED",
        round(random.uniform(5, 45), 1), random.choices(["Y", "N"], [92, 8])[0])
    score_then = random.randint(450, 950)
    add("credit_bureau", bureau_id, b, d(started - timedelta(days=30)), score_then,
        random.choices([0, 1, 2], [90, 8, 2])[0], "N", random.choices(["Y", "N"], [10, 90])[0])
    bureau_id += 1
    add("credit_bureau", bureau_id, b, "2026-10-01", max(300, min(999, score_then + random.randint(-150, 120))),
        random.choices([0, 1, 2], [88, 9, 3])[0], random.choices(["Y", "N"], [1, 99])[0],
        random.choices(["Y", "N"], [15, 85])[0])
    bureau_id += 1

# Mortgages, their properties, valuations and insurance
valuation_id, policy_id = 1, 1
final_dpd = {}
for l in mortgage_ids:
    start = loan_start[l]
    product_id = rows["loans"][l - 1][3]
    btl = product_id in (4, 5)
    original = random.randint(80, 600) * 1000
    ltv_orig = random.randint(50, 95) if not btl else random.randint(50, 75)
    seasoning = months_between(start, TODAY)
    balance = round(original * max(0.25, 1 - seasoning / 400), -2)
    ltv_curr = round(max(15, ltv_orig * balance / original * random.uniform(0.75, 1.0)), 1)
    if product_id == 5:
        repay = "IO"
    elif btl:
        repay = random.choices(["IO", "REP", "PP"], [60, 30, 10])[0]
    else:
        repay = random.choices(["REP", "IO", "PP"], [85, 8, 7])[0]
    rate_type = "TRK" if product_id == 3 else random.choices(["FIX", "SVR"], [80, 20])[0]
    fix_years = 5 if product_id in (2, 5) else 2
    fixed_end = None
    if rate_type == "FIX":
        fixed_end = add_months(TODAY, random.randint(1, fix_years * 12))
    margin = round(random.uniform(0.5, 2.5), 2)
    current_rate = round(BASE_RATE + margin, 2) if rate_type != "SVR" else 7.49
    if rate_type == "FIX":
        current_rate = round(random.uniform(3.8, 5.9), 2)
        margin = round(current_rate - BASE_RATE, 2)
    maturity = add_months(start, random.choice([20, 25, 30, 35]) * 12)
    add("mortgage_loans", l, "BTL" if btl else "RES", "N" if btl else "Y", original, balance,
        ltv_orig, ltv_curr, repay, rate_type, current_rate, margin, 7.49, d(fixed_end), d(start),
        d(maturity), seasoning, "Y" if rate_type == "FIX" else "N")
    add("interest_rate_history", l, d(start), round(current_rate - random.uniform(-1, 1), 2), rate_type)
    if start < date(2025, 11, 1):
        add("interest_rate_history", l, "2025-11-01", current_rate, rate_type)

    occupant, rel = ("OWNER", None) if not btl else ("TENANT", random.choices(["F1", "F2", "NR"], [15, 10, 75])[0])
    add("properties", l, l, f"NB{random.randint(1, 9)} {random.randint(1, 9)}XY", random.choice(regions),
        random.choice(["HOUSE", "FLAT", "BUNGALOW"]), random.choices(["FH", "LH"], [70, 30])[0],
        random.choices([1, 2], [94, 6])[0], random.choice("ABCDEFG"), occupant, rel)
    value_then = round(original / (ltv_orig / 100), -3)
    add("collateral_valuations", valuation_id, l, d(start - timedelta(days=30)), value_then,
        random.choice(["FULL", "DESKTOP"]), "Y")
    valuation_id += 1
    for when in sorted(random.sample(range(1, max(2, seasoning // 12) + 1), k=min(2, max(1, seasoning // 12)))):
        add("collateral_valuations", valuation_id, l, d(add_months(start, when * 12)),
            round(value_then * (1 + 0.03 * when), -3), random.choice(["INDEXED", "AVM"]), "N")
        valuation_id += 1
    add("collateral_valuations", valuation_id, l, "2026-09-30", round(balance / (ltv_curr / 100), -3),
        "INDEXED", "N")
    valuation_id += 1
    if random.random() < 0.8:
        add("insurance", policy_id, l, "LANDLORD" if btl else "BUILDINGS", d(start))
        policy_id += 1
    final_dpd[l] = random.choices([0, 30, 60, 90, 180], [85, 6, 4, 3, 2])[0]

# Consumer loans
for l in consumer_ids:
    start = loan_start[l]
    purpose = loan_start[(l, "purpose")]
    amount = random.randint(1, 25) * 1000
    term = random.choice([12, 24, 36, 48, 60])
    nominal = round(random.uniform(5, 18), 1)
    r = nominal / 1200
    instalment = round(amount * r / (1 - (1 + r) ** -term), 2)
    fee = random.choice([0, 0, 99, 199])
    total_payable = round(instalment * term + fee, 2)
    apr = round(nominal + random.uniform(0.3, 1.2) + (fee / amount) * 100 / (term / 12), 1)
    dpd = random.choices([0, 15, 45, 75, 120], [80, 7, 5, 4, 4])[0]
    final_dpd[l] = dpd
    status = "DEF" if dpd >= 90 else "ARR" if dpd > 0 else "CUR"
    add("consumer_loans", l, purpose, "Y", amount, term, nominal, apr, instalment, total_payable,
        round(total_payable - amount, 2), d(start), d(start + timedelta(days=14)),
        round(instalment * r * 28, 2), "N", d(add_months(start, term)), months_between(start, TODAY), status)
    add("interest_rate_history", l, d(start), nominal, "FIX")

# Monthly performance for the last 12 months, plus collections, forbearance and recoveries
month_ends = [add_months(date(2025, 12, 1), i) - timedelta(days=1) for i in range(12)]
action_id, case_id = 1, 1
for l in mortgage_ids + consumer_ids:
    dpd_end = final_dpd[l]
    months_late = dpd_end // 30 + (1 if dpd_end % 30 else 0)
    balance = rows["mortgage_loans"][l - 1][4] if l < 1000 else rows["consumer_loans"][l - 1001][3]
    instalment = balance / 200 if l < 1000 else rows["consumer_loans"][l - 1001][7]
    default_date = None
    for i, me in enumerate(month_ends):
        k = max(0, months_late - (11 - i))                 # arrears build up over the last months
        dpd = min(dpd_end, k * 30)
        if dpd >= 90 and default_date is None:
            default_date = me                              # UK default: 90 or more days past due
        add("loan_performance_monthly", l, d(me), round(balance, 2), round(k * instalment, 2), k, dpd,
            "Y" if default_date else "N", d(default_date))
    if dpd_end > 0:
        for _ in range(random.randint(1, 3)):
            when = TODAY - timedelta(days=random.randint(1, 120))
            add("collections", action_id, l, random.choice(["CALL", "LETTER", "VISIT", "DCA"]), d(when),
                (TODAY - when).days)
            action_id += 1
        if random.random() < 0.4:
            fstart = TODAY - timedelta(days=random.randint(30, 300))
            add("forbearance", case_id, l, random.choice(["PAYMENT_HOLIDAY", "REDUCED_PAYMENT", "TERM_EXTENSION"]),
                d(fstart), d(fstart + timedelta(days=random.choice([90, 180]))))
            case_id += 1
    if default_date:
        loss = round(balance * random.uniform(0.05, 0.6), 2)
        add("recoveries", l, d(default_date + timedelta(days=random.randint(30, 200))), loss,
            round(balance - loss, 2))

    # Treasury: is the loan pledged? "Eligible" is not the same as "pledged" (a planted trap)
    if l < 1000:
        pledged = random.choices(["UK_COVERED_BOND", "RMBS", "BOE_PREPOSITIONED", "NONE"], [30, 15, 20, 35])[0]
    else:
        pledged = random.choices(["BOE_PREPOSITIONED", "NONE"], [20, 80])[0]
    if default_date:
        pledged = "NONE"
    eligible = "N" if default_date else ("Y" if pledged != "NONE" or random.random() < 0.5 else "N")
    add("funding_encumbrance", l, pledged,
        d(TODAY - timedelta(days=random.randint(30, 900))) if pledged != "NONE" else None, eligible)

# Insert everything, parents before children so every link is valid
order = ["ref_codes", "products", "brokers", "borrowers", "borrower_additional", "borrower_income",
         "credit_bureau", "loans", "applications", "mortgage_loans", "consumer_loans",
         "interest_rate_history", "properties", "collateral_valuations", "insurance",
         "loan_performance_monthly", "collections", "forbearance", "recoveries", "funding_encumbrance"]
for t in order:
    marks = ",".join("?" * len(rows[t][0]))
    db.executemany(f"INSERT INTO {t} VALUES ({marks})", rows[t])
db.commit()


# ---------- 4. The data dictionary (about 10% of descriptions flawed on purpose) ----------
# Each entry: table, column ("" = the table itself), description, planted flaw ("" = none)
dictionary = [
    ("ref_codes", "", "Codebook: what every code used in other tables means.", ""),
    ("ref_codes", "code_set", "Which list the code belongs to, for example PURPOSE or OCC_REL.", ""),
    ("ref_codes", "code", "The code value as stored in other tables.", ""),
    ("ref_codes", "meaning", "Plain-English meaning of the code.", ""),
    ("products", "", "Catalogue of mortgage and consumer loan products.", ""),
    ("products", "product_id", "Unique product number.", ""),
    ("products", "product_name", "Marketing name of the product.", ""),
    ("products", "loan_type", "MORTGAGE or CONSUMER.", ""),
    ("products", "brand", "", "missing"),
    ("brokers", "", "Mortgage brokers (intermediaries) who introduce customers.", ""),
    ("brokers", "broker_id", "Unique broker number.", ""),
    ("brokers", "broker_name", "Name of the broker firm.", ""),
    ("brokers", "region", "UK region where the broker is based.", ""),
    ("borrowers", "", "Customers who hold a mortgage or consumer loan.", ""),
    ("borrowers", "borrower_id", "Unique customer number.", ""),
    ("borrowers", "full_name", "Customer name (synthetic).", ""),
    ("borrowers", "applicant_role", "Whether the customer is the primary or a joint applicant.", ""),
    ("borrowers", "age_band", "Customer age band.", ""),
    ("borrowers", "uk_resident_flag", "Y if the customer lives in the UK.", ""),
    ("borrowers", "employment", "Employment type; see ref_codes EMPLOYMENT.", ""),
    ("borrowers", "relationship_status", "Customer's marital or partner status.", ""),
    ("borrower_additional", "", "Extra customer details collected at application.", ""),
    ("borrower_additional", "borrower_id", "Customer number.", ""),
    ("borrower_additional", "dependants", "Number of financial dependants.", ""),
    ("borrower_additional", "first_time_buyer_flag", "Y if the customer had never owned a home.", ""),
    ("borrower_additional", "second_applicant_flag", "Y if there is a second applicant on the loan.", ""),
    ("borrower_income", "", "Customer income and affordability at application.", ""),
    ("borrower_income", "borrower_id", "Customer number.", ""),
    ("borrower_income", "income_date", "Date the income was recorded.", ""),
    ("borrower_income", "gross_income_gbp", "Gross annual income in pounds.", ""),
    ("borrower_income", "income_verification", "", "missing"),
    ("borrower_income", "debt_to_income_pct", "Total debt payments as a % of income.", ""),
    ("borrower_income", "affordability_pass_flag", "Y if the customer passed the affordability assessment.", ""),
    ("credit_bureau", "", "Credit reference agency results for each customer, over time.", ""),
    ("credit_bureau", "bureau_id", "Unique record number.", ""),
    ("credit_bureau", "borrower_id", "Customer number.", ""),
    ("credit_bureau", "score_date", "Date the score was obtained.", ""),
    ("credit_bureau", "bureau_score", "Credit score from the credit reference agency.", ""),
    ("credit_bureau", "ccj_count", "CCJ", "cryptic"),
    ("credit_bureau", "bankruptcy_flag", "Y if the customer has a bankruptcy on file.", ""),
    ("credit_bureau", "prior_arrears_flag", "Y if the customer had arrears with other lenders.", ""),
    ("loans", "", "Loan register: one row for every loan, mortgage or consumer.", ""),
    ("loans", "loan_id", "Unique loan number. Mortgages 1-200, consumer loans 1001-1250.", ""),
    ("loans", "loan_type", "MORTGAGE or CONSUMER.", ""),
    ("loans", "borrower_id", "Customer who holds the loan.", ""),
    ("loans", "product_id", "Product the loan was sold as.", ""),
    ("loans", "pool_id", "Loan pool the loan belongs to for reporting.", ""),
    ("loans", "originator", "Legal entity that made the loan.", ""),
    ("loans", "servicer", "", "missing"),
    ("loans", "pool_cutoff_date", "Cut-off", "vague"),
    ("applications", "", "Loan applications and decisions.", ""),
    ("applications", "application_id", "Unique application number.", ""),
    ("applications", "loan_id", "Loan created from this application.", ""),
    ("applications", "application_date", "Date the application was received.", ""),
    ("applications", "channel", "How the customer applied; see ref_codes CHANNEL.", ""),
    ("applications", "broker_id", "Broker who introduced the customer, if any.", ""),
    ("applications", "decision", "Application decision.", ""),
    ("applications", "policy_exception_flag", "Y if the loan was approved outside normal lending policy.", ""),
    ("mortgage_loans", "", "UK mortgage details: structure, terms and pricing.", ""),
    ("mortgage_loans", "loan_id", "Loan number.", ""),
    ("mortgage_loans", "product_code", "Mortgage type; see ref_codes PRODUCT.", ""),
    ("mortgage_loans", "fca_regulated_flag", "Y if the mortgage is regulated by the FCA.", ""),
    ("mortgage_loans", "original_amount_gbp", "Amount lent when the mortgage started.", ""),
    ("mortgage_loans", "balance_gbp", "Amount still owed today.", ""),
    ("mortgage_loans", "ltv_orig_pct", "Loan-to-value % when the mortgage started.", ""),
    ("mortgage_loans", "ltv_curr_pct", "LTV", "vague"),
    ("mortgage_loans", "repayment_type", "Repay type", "vague"),
    ("mortgage_loans", "rate_type", "Interest rate type; see ref_codes RATE_TYPE.", ""),
    ("mortgage_loans", "current_rate_pct", "Interest rate charged today.", ""),
    ("mortgage_loans", "margin_over_base_pct", "Margin of the interest rate above the central bank base rate.", ""),
    ("mortgage_loans", "reversion_rate_pct", "Rate the mortgage moves to when a deal ends.", ""),
    ("mortgage_loans", "fixed_rate_end_date", "Deal end", "vague"),
    ("mortgage_loans", "start_date", "Date the mortgage started.", ""),
    ("mortgage_loans", "maturity_date", "Date the mortgage must be fully repaid.", ""),
    ("mortgage_loans", "seasoning_months", "Months since the mortgage started.", ""),
    ("mortgage_loans", "erc_flag", "ERC", "cryptic"),
    ("consumer_loans", "", "UK consumer (personal) loan details: structure, terms and pricing.", ""),
    ("consumer_loans", "loan_id", "Loan number.", ""),
    ("consumer_loans", "purpose_cd", "Loan purpose; see ref_codes PURPOSE.", ""),
    ("consumer_loans", "cca_regulated_flag", "Y if the loan is regulated under the Consumer Credit Act.", ""),
    ("consumer_loans", "amount_gbp", "Amount borrowed.", ""),
    ("consumer_loans", "term_months", "Length of the loan in months.", ""),
    ("consumer_loans", "nominal_rate_pct", "Interest rate before fees.", ""),
    ("consumer_loans", "apr_pct", "Annual percentage rate: total yearly cost including fees.", ""),
    ("consumer_loans", "monthly_instalment_gbp", "Fixed monthly payment.", ""),
    ("consumer_loans", "total_amount_payable_gbp", "Everything the customer pays back over the loan.", ""),
    ("consumer_loans", "total_charge_for_credit_gbp", "TCC", "cryptic"),
    ("consumer_loans", "agreement_date", "Date the credit agreement was signed.", ""),
    ("consumer_loans", "cooling_off_end_date", "Last day the customer can withdraw from the agreement.", ""),
    ("consumer_loans", "early_settlement_charge_gbp", "Charge for paying the loan off early.", ""),
    ("consumer_loans", "secured_flag", "Y if the loan is secured on an asset.", ""),
    ("consumer_loans", "maturity_date", "Date of the last scheduled payment.", ""),
    ("consumer_loans", "seasoning_months", "Months since the loan started.", ""),
    ("consumer_loans", "status_cd", "Status code", "vague"),
    ("interest_rate_history", "", "Every change to a loan's interest rate.", ""),
    ("interest_rate_history", "loan_id", "Loan number.", ""),
    ("interest_rate_history", "effective_date", "Date the rate took effect.", ""),
    ("interest_rate_history", "rate_pct", "Interest rate from that date.", ""),
    ("interest_rate_history", "rate_type", "Rate type from that date.", ""),
    ("properties", "", "Properties securing the mortgages (collateral).", ""),
    ("properties", "property_id", "Unique property number.", ""),
    ("properties", "loan_id", "Mortgage secured on this property.", ""),
    ("properties", "postcode", "Property postcode (synthetic).", ""),
    ("properties", "region", "UK region of the property.", ""),
    ("properties", "property_type", "House, flat or bungalow.", ""),
    ("properties", "tenure", "Freehold or leasehold; see ref_codes TENURE.", ""),
    ("properties", "charge_rank", "Rank of the bank's legal charge: 1 = first charge, 2 = second charge.", ""),
    ("properties", "epc_rating", "Energy performance certificate rating, A to G.", ""),
    ("properties", "occupant_type", "Who lives in the property: owner or tenant.", ""),
    ("properties", "occ_rel_cd", "", "missing"),
    ("collateral_valuations", "", "Every valuation of each mortgaged property, including the one at origination.", ""),
    ("collateral_valuations", "valuation_id", "Unique valuation number.", ""),
    ("collateral_valuations", "property_id", "Property valued.", ""),
    ("collateral_valuations", "valuation_date", "Date of the valuation.", ""),
    ("collateral_valuations", "valuation_gbp", "Property value in pounds.", ""),
    ("collateral_valuations", "valuation_method", "How the property was valued; see ref_codes VAL_METHOD.", ""),
    ("collateral_valuations", "is_origination", "Y if this is the valuation used when the mortgage started.", ""),
    ("insurance", "", "Insurance cover on mortgaged properties.", ""),
    ("insurance", "policy_id", "Unique policy number.", ""),
    ("insurance", "property_id", "Property insured.", ""),
    ("insurance", "cover_type", "Type of cover: buildings or landlord.", ""),
    ("insurance", "start_date", "Date cover started.", ""),
    ("loan_performance_monthly", "", "Month-end performance of every loan: balance, arrears and default.", ""),
    ("loan_performance_monthly", "loan_id", "Loan number.", ""),
    ("loan_performance_monthly", "month_end", "Reporting month end.", ""),
    ("loan_performance_monthly", "balance_gbp", "Balance at month end.", ""),
    ("loan_performance_monthly", "arrears_balance_gbp", "Amount overdue at month end.", ""),
    ("loan_performance_monthly", "months_in_arrears", "Number of monthly payments missed at month end.", ""),
    ("loan_performance_monthly", "dpd", "", "missing"),
    ("loan_performance_monthly", "default_flag", "Y if the loan is in default.", ""),
    ("loan_performance_monthly", "default_date", "Date the loan first went into default.", ""),
    ("collections", "", "Collection actions taken on loans in arrears.", ""),
    ("collections", "action_id", "Unique action number.", ""),
    ("collections", "loan_id", "Loan number.", ""),
    ("collections", "action_type", "", "missing"),
    ("collections", "action_date", "Date of the action.", ""),
    ("collections", "days_since_contact", "Days since the bank last contacted the customer.", ""),
    ("forbearance", "", "Forbearance arrangements given to customers in difficulty.", ""),
    ("forbearance", "case_id", "Unique case number.", ""),
    ("forbearance", "loan_id", "Loan number.", ""),
    ("forbearance", "forbearance_type", "Type of arrangement; see ref_codes FORB.", ""),
    ("forbearance", "start_date", "Date the arrangement started.", ""),
    ("forbearance", "end_date", "Date the arrangement ends.", ""),
    ("recoveries", "", "Losses and recoveries on defaulted loans.", ""),
    ("recoveries", "loan_id", "Loan number.", ""),
    ("recoveries", "recovery_date", "Date the recovery was completed.", ""),
    ("recoveries", "loss_amount_gbp", "Amount written off.", ""),
    ("recoveries", "recovered_gbp", "Amount recovered.", ""),
    ("funding_encumbrance", "", "Treasury: whether each loan is used to raise funding.", ""),
    ("funding_encumbrance", "loan_id", "Loan number.", ""),
    ("funding_encumbrance", "pledged_to", "Pledge", "vague"),
    ("funding_encumbrance", "pledge_date", "Date the loan was pledged.", ""),
    ("funding_encumbrance", "boe_eligible_flag", "Y if the loan meets the central bank's collateral eligibility rules.", ""),
]
with open(DICT_PATH, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["table_name", "column_name", "description"])
    for t, c, desc, _ in dictionary:
        w.writerow([t, c, desc])
with open(EVAL_DIR / "planted_flaws.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["table_name", "column_name", "flaw"])
    for t, c, _, flaw in dictionary:
        if flaw:
            w.writerow([t, c, flaw])


# ---------- 5. The hidden answer key (never shown to the AI) ----------
answer_key = [
    ("Tenant is a family member of the borrower", "For buy-to-let mortgages, whether the tenant is a family member of the borrower.", "properties.occ_rel_cd", "occupant_type; relationship_status"),
    ("Loan-to-value at origination", "The mortgage amount as a % of the property value when the mortgage was taken out.", "mortgage_loans.ltv_orig_pct", "ltv_curr_pct"),
    ("Months in arrears", "How many monthly mortgage payments are missed at the reporting date.", "loan_performance_monthly.months_in_arrears", "forbearance; collections"),
    ("Current indexed property value", "The latest value of the mortgaged property.", "collateral_valuations.valuation_gbp", "origination valuation row"),
    ("First-charge mortgage", "The bank's charge on the property ranks first.", "properties.charge_rank", "products.product_name"),
    ("Repricing date", "The date the fixed rate ends and the rate can change.", "mortgage_loans.fixed_rate_end_date", "maturity_date"),
    ("Interest-only mortgage", "A mortgage where monthly payments cover interest only.", "mortgage_loans.repayment_type", "products.product_name"),
    ("Margin over base rate", "How far the mortgage rate is above the central bank base rate.", "mortgage_loans.margin_over_base_pct", "current_rate_pct"),
    ("Encumbered loan", "A loan already pledged to raise funding.", "funding_encumbrance.pledged_to", "boe_eligible_flag"),
    ("Debt consolidation loan", "A consumer loan taken out to pay off other debts.", "consumer_loans.purpose_cd", "meaning only in ref_codes"),
    ("Days past due", "How many days a payment is overdue at the reporting date.", "loan_performance_monthly.dpd", "collections.days_since_contact"),
    ("Annual Percentage Rate (APR)", "The total yearly cost of a consumer loan including fees.", "consumer_loans.apr_pct", "nominal_rate_pct"),
    ("Total charge for credit", "The total cost of borrowing: interest plus fees.", "consumer_loans.total_charge_for_credit_gbp", "rate columns"),
    ("Cooling-off period end", "The last day a consumer can withdraw from the credit agreement.", "consumer_loans.cooling_off_end_date", "agreement_date"),
    ("Bureau score at origination", "The customer's credit score when the loan was applied for.", "credit_bureau.bureau_score", "latest score row"),
    ("Self-certified income", "Income stated by the borrower and not checked by the bank.", "borrower_income.income_verification", "affordability_pass_flag"),
    ("Date of default", "The date the loan first went into default.", "loan_performance_monthly.default_date", "first month in arrears"),
]
with open(EVAL_DIR / "answer_key.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["term", "meaning", "correct_column", "trap"])
    w.writerows(answer_key)


# ---------- 6. Check everything and print a summary ----------
problems = []
db_tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

# a) every foreign key points to a real row
broken = db.execute("PRAGMA foreign_key_check").fetchall()
if broken:
    problems.append(f"{len(broken)} broken links")

# b) every code used exists in the codebook
code_columns = {("mortgage_loans", "product_code"): "PRODUCT", ("mortgage_loans", "rate_type"): "RATE_TYPE",
                ("mortgage_loans", "repayment_type"): "REPAY", ("consumer_loans", "purpose_cd"): "PURPOSE",
                ("consumer_loans", "status_cd"): "STATUS", ("properties", "occ_rel_cd"): "OCC_REL",
                ("properties", "tenure"): "TENURE", ("collateral_valuations", "valuation_method"): "VAL_METHOD",
                ("funding_encumbrance", "pledged_to"): "PLEDGE", ("borrower_income", "income_verification"): "INCOME_VER",
                ("forbearance", "forbearance_type"): "FORB", ("collections", "action_type"): "COLL_ACTION",
                ("applications", "channel"): "CHANNEL", ("borrowers", "employment"): "EMPLOYMENT"}
for (t, c), code_set in code_columns.items():
    unknown = db.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND {c} NOT IN "
                         f"(SELECT code FROM ref_codes WHERE code_set = ?)", (code_set,)).fetchone()[0]
    if unknown:
        problems.append(f"{t}.{c}: {unknown} unknown codes")

# c) every column has a dictionary entry, and every answer-key column exists
described = {(t, c) for t, c, _, _ in dictionary}
for t in db_tables:
    for col in [r[1] for r in db.execute(f"PRAGMA table_info({t})")]:
        if (t, col) not in described:
            problems.append(f"no dictionary entry for {t}.{col}")
for _, _, target, _ in answer_key:
    t, c = target.split(".")
    if c not in [r[1] for r in db.execute(f"PRAGMA table_info({t})")]:
        problems.append(f"answer key column missing: {target}")

print(f"Database:   {DB_PATH}")
print(f"Dictionary: {DICT_PATH}  ({len(dictionary)} entries, "
      f"{sum(1 for x in dictionary if x[3])} flawed on purpose)")
print(f"Hidden:     {EVAL_DIR}  (answer key: {len(answer_key)} terms)\n")
for t in order:
    print(f"  {t:<26} {db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>6} rows")
print()
print("✅ All links, codes and dictionary entries are valid." if not problems
      else "❌ Problems found:\n  " + "\n  ".join(problems))
db.close()
