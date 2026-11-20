import os
import numpy as np
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import create_engine, text
from datetime import date


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Year to exclude from analytical views (data quality / incomplete year)
# Update this if you want to include earlier data.
_EXCLUDE_YEAR: int = 2022

# Required CSV columns per account type
_SAVINGS_REQUIRED_COLS  = {"Details", "Posting Date", "Description", "Amount",
                            "Type", "Balance", "Check or Slip #"}
_CHECKING_REQUIRED_COLS = {"Details", "Posting Date", "Description", "Amount",
                            "Type", "Balance", "Check or Slip #"}
_CC_REQUIRED_COLS       = {"Transaction Date", "Description", "Category",
                            "Type", "Amount"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_engine(password: str = None):
    """
    Build a SQLAlchemy engine for the gl_transactions PostgreSQL database.

    Reads connection details from environment variables when available:
        DB_HOST     (default: localhost)
        DB_PORT     (default: 5432)
        DB_USER     (default: postgres)
        DB_NAME     (default: gl_transactions)
        DB_PASSWORD (overridden by the password argument when supplied)

    Args:
        password (str, optional): Database password. Falls back to the
                                   DB_PASSWORD environment variable.

    Returns:
        sqlalchemy.Engine
    """
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "postgres")
    db   = os.getenv("DB_NAME", "gl_transactions")
    pw   = password or os.getenv("DB_PASSWORD", "")
    url  = f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}"
    return create_engine(url)


def _fetch_category_map(engine) -> dict:
    """
    Retrieve the category description → category_id mapping from the database.

    Returns:
        dict[str, int]: e.g. {'food & drink': 6, 'groceries': 9, ...}
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT category_id, category_description FROM category")
        ).fetchall()
    return {row[1].lower(): row[0] for row in rows}


def _validate_columns(df: pd.DataFrame, required: set, source_label: str):
    """
    Raise a clear ValueError when required columns are missing from a DataFrame.

    Args:
        df (pd.DataFrame): The DataFrame to check.
        required (set): Set of required column names (case-sensitive).
        source_label (str): Human-readable label for error messages.

    Raises:
        ValueError: Lists every missing column so the user knows exactly what
                    to fix in their CSV export.
    """
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"[{source_label}] The following required columns are missing from "
            f"the input CSV: {sorted(missing)}.\n"
            f"Columns found: {sorted(df.columns.tolist())}\n"
            f"Check that you exported the correct file format from your bank."
        )


def _safe_decimal_amount(series: pd.Series) -> pd.Series:
    """
    Round a float series to 2 decimal places using ROUND_HALF_UP to avoid
    floating-point representation errors in monetary amounts.

    Args:
        series (pd.Series): Numeric series of transaction amounts.

    Returns:
        pd.Series: Rounded to 2 d.p., dtype float64.
    """
    return series.apply(
        lambda x: float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        if pd.notna(x) else x
    )


# ---------------------------------------------------------------------------
# Credit-card processing
# ---------------------------------------------------------------------------

def cc_file_cleanup(gl_transactions_password: str, csv_file: str,
                    category_map: dict = None):
    """
    Clean and transform a credit-card transactions CSV into a format ready for
    loading into the gl_transactions PostgreSQL database.

    The function uses the bank-assigned category column to look up the matching
    category_id. Transactions whose bank category cannot be mapped automatically
    are separated into a review DataFrame.

    Args:
        gl_transactions_password (str): Password for the gl_transactions
            PostgreSQL server. Used only when category_map is not provided.
            Pass "" to use the DB_PASSWORD environment variable.
        csv_file (str): Path to the input CSV file of credit-card transactions
            exported from the bank (Chase-format columns expected).
        category_map (dict, optional): Pre-built {description: category_id}
            mapping. When provided, skips the database lookup entirely —
            useful for testing without a live database connection.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]:
            - cc_df: Cleaned and transformed transactions ready for loading.
            - cc_review_df: Transactions that could not be automatically
              categorised and require manual review before loading.

    Raises:
        FileNotFoundError: If csv_file does not exist.
        ValueError: If required columns are missing from the CSV.
    """
    if not os.path.isfile(csv_file):
        raise FileNotFoundError(
            f"[cc_file_cleanup] CSV file not found: {csv_file}"
        )

    if category_map is None:
        engine       = _get_engine(gl_transactions_password)
        category_map = _fetch_category_map(engine)

    # --- Load raw CSV ---
    cc_df = pd.read_csv(csv_file, encoding="unicode_escape", index_col=False)

    _validate_columns(cc_df, _CC_REQUIRED_COLS, "cc_file_cleanup")

    # --- Standardise column names and text ---
    cc_df.columns = [col.lower() for col in cc_df.columns]
    cc_df = cc_df.map(lambda x: x.lower() if isinstance(x, str) else x)

    # --- Drop unused columns ---
    for col in ["post date", "type", "memo"]:
        if col in cc_df.columns:
            cc_df = cc_df.drop(columns=[col])

    # --- Rename to schema columns ---
    cc_df = cc_df.rename(columns={
        "transaction date": "short_date",
        "description":      "transaction_description",
        "amount":           "transaction_amount",
        "category":         "_bank_category",
    })

    # --- Date and amount conversion ---
    cc_df["short_date"]          = pd.to_datetime(cc_df["short_date"])
    cc_df["transaction_amount"]  = _safe_decimal_amount(cc_df["transaction_amount"])

    # --- Add required schema columns ---
    cc_df.insert(0, "account_id",          1)   # credit card account
    cc_df.insert(1, "transaction_type_id", 0)   # placeholder; assigned below
    cc_df.insert(2, "category_id",         pd.NA)
    cc_df["category_id"] = cc_df["category_id"].astype("Int64")

    # --- Classify payments (positive amount → CC payment received) ---
    payment_mask = cc_df["transaction_amount"] > 0
    cc_df.loc[payment_mask, "transaction_type_id"] = 7   # credit card payment
    cc_df.loc[payment_mask, "category_id"]         = pd.NA

    # --- Classify purchases (negative amount) using bank category ---
    purchase_mask = cc_df["transaction_amount"] < 0
    cc_df.loc[purchase_mask, "transaction_type_id"] = 1  # credit card purchase

    def map_category(bank_cat):
        if pd.isna(bank_cat):
            return pd.NA
        return category_map.get(str(bank_cat).lower(), pd.NA)

    cc_df.loc[purchase_mask, "category_id"] = (
        cc_df.loc[purchase_mask, "_bank_category"].apply(map_category)
    )

    # --- Truncate description to 100 characters ---
    cc_df["transaction_description"] = (
        cc_df["transaction_description"].str.slice(0, 100)
    )

    # --- Drop helper column ---
    cc_df = cc_df.drop(columns=["_bank_category"])

    # --- Separate unclassified transactions ---
    review_mask  = (cc_df["transaction_type_id"] == 0)
    cc_review_df = cc_df[review_mask].reset_index(drop=True)
    cc_df        = cc_df[~review_mask].reset_index(drop=True)

    print(
        "Transactions successfully transformed. "
        "The following transactions need to be reviewed. "
        "Once values have been assigned to transaction_type_id and "
        "category_id, use to_gl_transactions() to load into the database."
    )
    print(cc_review_df)

    return cc_df, cc_review_df


# ---------------------------------------------------------------------------
# Savings processing
# ---------------------------------------------------------------------------

def savings_file_cleanup(csv_file: str):
    """
    Clean and transform a savings-account transactions CSV into a format ready
    for loading into the gl_transactions PostgreSQL database.

    Args:
        csv_file (str): Path to the input CSV file exported from the bank
            (Chase savings format expected).

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]:
            - savings_df: Cleaned transactions ready for loading.
            - review_df:  Transactions that could not be automatically
              classified and require manual review.

    Raises:
        FileNotFoundError: If csv_file does not exist.
        ValueError: If required columns are missing from the CSV.
    """
    if not os.path.isfile(csv_file):
        raise FileNotFoundError(
            f"[savings_file_cleanup] CSV file not found: {csv_file}"
        )

    # Load raw CSV
    savings_df = pd.read_csv(csv_file, encoding="unicode_escape", index_col=False)

    _validate_columns(savings_df, _SAVINGS_REQUIRED_COLS, "savings_file_cleanup")

    # Remove unnecessary columns
    savings_df = savings_df.drop(
        ["Details", "Type", "Balance", "Check or Slip #"], axis=1
    )

    # Standardize all text to lowercase
    savings_df = savings_df.map(lambda x: x.lower() if isinstance(x, str) else x)
    savings_df.columns = [col.lower() for col in savings_df.columns]

    # Add required columns for database schema
    savings_df.insert(0, "account_id",          3)
    savings_df.insert(1, "transaction_type_id", 0)
    savings_df.insert(2, "category_id",         0)

    # Rename columns to match database schema
    savings_df = savings_df.rename(columns={
        "posting date": "short_date",
        "description":  "transaction_description",
        "amount":       "transaction_amount",
    })

    # Convert date and amount columns
    savings_df["short_date"]         = pd.to_datetime(savings_df["short_date"])
    savings_df["transaction_amount"] = _safe_decimal_amount(savings_df["transaction_amount"])

    # Classify transactions by type — na=False prevents crash on null descriptions
    savings_df.loc[
        savings_df["transaction_description"].str.contains("interest", na=False),
        ["transaction_type_id", "category_id"]
    ] = [9, np.nan]

    savings_df.loc[
        savings_df["transaction_description"].str.contains("transfer", na=False)
        & (savings_df["transaction_amount"] < 0),
        ["transaction_type_id", "category_id"]
    ] = [5, np.nan]

    savings_df.loc[
        savings_df["transaction_description"].str.contains("transfer", na=False)
        & (savings_df["transaction_amount"] > 0),
        ["transaction_type_id", "category_id"]
    ] = [6, np.nan]

    savings_df.loc[
        savings_df["transaction_description"].str.contains("deposit", na=False)
        & (savings_df["transaction_amount"] > 0),
        ["transaction_type_id", "category_id"]
    ] = [3, np.nan]

    savings_df.loc[
        savings_df["transaction_description"].str.contains("withdraw", na=False)
        & (savings_df["transaction_amount"] < 0),
        ["transaction_type_id", "category_id"]
    ] = [4, np.nan]

    # Default: unclassified positives → deposit, negatives → withdraw
    savings_df.loc[
        (savings_df["transaction_type_id"] == 0) & (savings_df["transaction_amount"] > 0),
        ["transaction_type_id", "category_id"]
    ] = [3, np.nan]

    savings_df.loc[
        (savings_df["transaction_type_id"] == 0) & (savings_df["transaction_amount"] < 0),
        ["transaction_type_id", "category_id"]
    ] = [4, np.nan]

    # Truncate description to 100 characters
    savings_df["transaction_description"] = (
        savings_df["transaction_description"].str.slice(0, 100)
    )

    # Separate transactions needing manual review
    mask       = (savings_df["transaction_type_id"] == 0) & (savings_df["category_id"] == 0)
    review_df  = savings_df[mask].reset_index(drop=True)
    savings_df = savings_df[~mask].reset_index(drop=True)

    print("Transformation complete. Transactions needing review:")
    print(review_df)

    return savings_df, review_df


# ---------------------------------------------------------------------------
# Checking processing
# ---------------------------------------------------------------------------

def checking_file_cleanup(csv_file: str):
    """
    Clean and transform a checking-account transactions CSV into a format
    ready for loading into the gl_transactions PostgreSQL database.

    Args:
        csv_file (str): Path to the input CSV file exported from the bank
            (Chase checking format expected).

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]:
            - checking_df: Cleaned transactions ready for loading.
            - review_df:   Transactions that could not be automatically
              classified and require manual review.

    Raises:
        FileNotFoundError: If csv_file does not exist.
        ValueError: If required columns are missing from the CSV.
    """
    if not os.path.isfile(csv_file):
        raise FileNotFoundError(
            f"[checking_file_cleanup] CSV file not found: {csv_file}"
        )

    # Load raw CSV
    checking_df = pd.read_csv(csv_file, encoding="unicode_escape", index_col=False)

    _validate_columns(checking_df, _CHECKING_REQUIRED_COLS, "checking_file_cleanup")

    # Standardize text to lowercase and remove unnecessary columns
    checking_df = checking_df.map(lambda x: x.lower() if isinstance(x, str) else x)
    checking_df.columns = [col.lower() for col in checking_df.columns]
    checking_df = checking_df.drop(
        ["details", "type", "balance", "check or slip #"], axis=1
    )

    # Rename columns to match database schema
    checking_df = checking_df.rename(columns={
        "posting date": "short_date",
        "description":  "transaction_description",
        "amount":       "transaction_amount",
    })

    # Convert date and amount columns
    checking_df["short_date"]         = pd.to_datetime(checking_df["short_date"])
    checking_df["transaction_amount"] = _safe_decimal_amount(checking_df["transaction_amount"])

    # Add required columns for database schema
    checking_df.insert(1, "account_id",          2)
    checking_df.insert(2, "transaction_type_id", 0)
    checking_df.insert(3, "category_id",         0)
    checking_df["category_id"] = checking_df["category_id"].fillna(0).astype("Int64")

    # Classify transactions — na=False prevents crash on null descriptions
    checking_df.loc[
        checking_df["transaction_description"].str.contains("transfer", na=False)
        & (checking_df["transaction_amount"] > 0),
        ["transaction_type_id", "category_id"]
    ] = [6, np.nan]

    checking_df.loc[
        checking_df["transaction_description"].str.contains("deposit", na=False)
        & (checking_df["transaction_amount"] > 0),
        ["transaction_type_id", "category_id"]
    ] = [3, np.nan]

    checking_df.loc[
        checking_df["transaction_description"].str.contains("interest", na=False),
        ["transaction_type_id", "category_id"]
    ] = [9, np.nan]

    checking_df.loc[
        checking_df["transaction_description"].str.contains("transfer", na=False)
        & (checking_df["transaction_amount"] < 0),
        ["transaction_type_id", "category_id"]
    ] = [5, np.nan]

    # Flag Venmo payments for manual review (require category assignment)
    venmo_mask      = (
        checking_df["transaction_description"].str.contains("venmo", na=False)
        & (checking_df["transaction_amount"] < 0)
    )
    venmo_review_df = checking_df[venmo_mask].reset_index(drop=True)
    checking_df     = checking_df[~venmo_mask].reset_index(drop=True)

    # Separate remaining unclassified transactions for manual review
    mask        = (checking_df["transaction_type_id"] == 0) & (checking_df["category_id"] == 0)
    review_df   = checking_df[mask].reset_index(drop=True)
    checking_df = checking_df[~mask].reset_index(drop=True)

    review_df = pd.concat([review_df, venmo_review_df]).reset_index(drop=True)

    # Truncate description to 100 characters
    checking_df["transaction_description"] = (
        checking_df["transaction_description"].str.slice(0, 100)
    )
    review_df["transaction_description"] = (
        review_df["transaction_description"].str.slice(0, 100)
    )

    print("Transformation complete. Transactions needing review:")
    print(review_df)

    return checking_df, review_df


# ---------------------------------------------------------------------------
# Database loader
# ---------------------------------------------------------------------------

def to_gl_transactions(df: pd.DataFrame, data_source: str,
                       password: str = None, backup_dir: str = None):
    """
    Load a cleaned transactions DataFrame into the transaction_facts table of
    the gl_transactions PostgreSQL database, and save a dated backup CSV.

    Args:
        df (pd.DataFrame): Cleaned DataFrame with columns matching the
            transaction_facts schema.
        data_source (str): Label used for the backup CSV filename
            (e.g. "savings", "checking", "cc").
        password (str, optional): Database password. Falls back to the
            DB_PASSWORD environment variable when omitted.
        backup_dir (str, optional): Directory for the backup CSV. Defaults to
            the current working directory when not specified. Pass an absolute
            path (e.g. "../data/backups") for reproducible output locations.

    Returns:
        None
    """
    engine = _get_engine(password)

    with engine.connect() as conn:
        df.to_sql("transaction_facts", con=conn, if_exists="append", index=False)
        conn.commit()

    # Save backup CSV with today's date in the specified (or current) directory
    current_date = date.today()
    file_name    = f"{data_source}_{current_date}.csv"
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        file_name = os.path.join(backup_dir, file_name)

    df.to_csv(file_name, index=False)

    print(f"{data_source} data successfully loaded into gl_transactions PostgreSQL database")
    print(f"Backup CSV saved as {file_name}")
