import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from datetime import date


def savings_file_cleanup(csv_file):
    # Load raw CSV into DataFrame
    savings_df = pd.read_csv(csv_file, encoding='unicode_escape', index_col=False)

    # Remove unnecessary columns
    savings_df = savings_df.drop(['Details', 'Type', 'Balance', 'Check or Slip #'], axis=1)

    # Standardize all text to lowercase
    savings_df = savings_df.map(lambda x: x.lower() if isinstance(x, str) else x)
    savings_df.columns = [col.lower() for col in savings_df.columns]

    # Add required columns for database schema
    savings_df.insert(0, 'account_id', 3)
    savings_df.insert(1, 'transaction_type_id', 0)
    savings_df.insert(2, 'category_id', 0)

    # Rename columns to match database schema
    savings_df = savings_df.rename(columns={
        'posting date': 'short_date',
        'description': 'transaction_description',
        'amount': 'transaction_amount'
    })

    # Convert date column to datetime format
    savings_df['short_date'] = pd.to_datetime(savings_df['short_date'])

    # Classify transactions by type based on description and amount
    savings_df.loc[savings_df['transaction_description'].str.contains('interest'),
                   ['transaction_type_id', 'category_id']] = [9, np.nan]

    savings_df.loc[(savings_df['transaction_description'].str.contains('transfer')) & (savings_df['transaction_amount'] < 0),
                   ['transaction_type_id', 'category_id']] = [5, np.nan]

    savings_df.loc[(savings_df['transaction_description'].str.contains('transfer')) & (savings_df['transaction_amount'] > 0),
                   ['transaction_type_id', 'category_id']] = [6, np.nan]

    savings_df.loc[(savings_df['transaction_description'].str.contains('deposit')) & (savings_df['transaction_amount'] > 0),
                   ['transaction_type_id', 'category_id']] = [3, np.nan]

    savings_df.loc[(savings_df['transaction_description'].str.contains('withdraw')) & (savings_df['transaction_amount'] < 0),
                   ['transaction_type_id', 'category_id']] = [4, np.nan]

    # Default unclassified positives as deposit, negatives as withdraw
    savings_df.loc[(savings_df['transaction_type_id'] == 0) & (savings_df['transaction_amount'] > 0),
                   ['transaction_type_id', 'category_id']] = [3, np.nan]

    savings_df.loc[(savings_df['transaction_type_id'] == 0) & (savings_df['transaction_amount'] < 0),
                   ['transaction_type_id', 'category_id']] = [4, np.nan]

    # Truncate description to 100 characters and tag region
    savings_df['transaction_description'] = savings_df['transaction_description'].str.slice(0, 100)
    savings_df['region'] = 'North America'

    # Separate transactions needing manual review
    mask = (savings_df['transaction_type_id'] == 0) & (savings_df['category_id'] == 0)
    review_df = savings_df[mask].reset_index(drop=True)
    savings_df = savings_df[~mask].reset_index(drop=True)

    print("Transformation complete. Transactions needing review:")
    print(review_df)

    return savings_df, review_df


def checking_file_cleanup(csv_file):
    # Load raw CSV into DataFrame
    checking_df = pd.read_csv(csv_file, encoding='unicode_escape', index_col=False)

    # Standardize text to lowercase and remove unnecessary columns
    checking_df = checking_df.map(lambda x: x.lower() if isinstance(x, str) else x)
    checking_df.columns = [col.lower() for col in checking_df.columns]
    checking_df = checking_df.drop(['details', 'type', 'balance', 'check or slip #'], axis=1)

    # Rename columns to match database schema
    checking_df = checking_df.rename(columns={
        'posting date': 'short_date',
        'description': 'transaction_description',
        'amount': 'transaction_amount'
    })

    # Convert date column to datetime format
    checking_df['short_date'] = pd.to_datetime(checking_df['short_date'])

    # Add required columns for database schema
    checking_df.insert(1, 'account_id', 2)
    checking_df.insert(2, 'transaction_type_id', 0)
    checking_df.insert(3, 'category_id', 0)
    checking_df['category_id'] = checking_df['category_id'].fillna(0).astype('Int64')

    # Classify transactions by type based on description and amount
    checking_df.loc[(checking_df['transaction_description'].str.contains('transfer')) & (checking_df['transaction_amount'] > 0),
                    ['transaction_type_id', 'category_id']] = [6, np.nan]

    checking_df.loc[(checking_df['transaction_description'].str.contains('deposit')) & (checking_df['transaction_amount'] > 0),
                    ['transaction_type_id', 'category_id']] = [3, np.nan]

    checking_df.loc[checking_df['transaction_description'].str.contains('interest'),
                    ['transaction_type_id', 'category_id']] = [9, np.nan]

    checking_df.loc[(checking_df['transaction_description'].str.contains('transfer')) & (checking_df['transaction_amount'] < 0),
                    ['transaction_type_id', 'category_id']] = [5, np.nan]

    checking_df.loc[(checking_df['transaction_description'].str.contains('transfer')) & (checking_df['transaction_amount'] > 0),
                    ['transaction_type_id', 'category_id']] = [6, np.nan]

    # Flag Venmo payments for manual review
    mask = (checking_df['transaction_description'].str.contains('venmo')) & (checking_df['transaction_amount'] < 0)
    venmo_review_df = checking_df[mask].reset_index(drop=True)
    checking_df = checking_df[~mask].reset_index(drop=True)

    # Separate remaining unclassified transactions for manual review
    mask = (checking_df['transaction_type_id'] == 0) & (checking_df['category_id'] == 0)
    review_df = checking_df[mask].reset_index(drop=True)
    checking_df = checking_df[~mask].reset_index(drop=True)

    review_df = pd.concat([review_df, venmo_review_df]).reset_index(drop=True)

    # Truncate description to 100 characters and tag region
    checking_df['transaction_description'] = checking_df['transaction_description'].str.slice(0, 100)
    checking_df['region'] = 'North America'
    review_df['transaction_description'] = review_df['transaction_description'].str.slice(0, 100)

    print("Transformation complete. Transactions needing review:")
    print(review_df)

    return checking_df, review_df


def to_gl_transactions(df, data_source, password):
    # Connect to PostgreSQL database
    engine = create_engine('postgresql+psycopg2://postgres:' + password + '@localhost/gl_transactions')
    conn = engine.connect()

    # Load DataFrame into transaction_facts table
    df.to_sql('transaction_facts', con=conn, if_exists='append', index=False)
    conn.commit()
    conn.close()

    # Save backup CSV with today's date
    current_date = date.today()
    file_name = f"{data_source}_{current_date}.csv"
    df.to_csv(file_name, index=False)

    print(f"{data_source} data successfully loaded into gl_transactions PostgreSQL database")
    print(f"Backup CSV saved as {file_name}")