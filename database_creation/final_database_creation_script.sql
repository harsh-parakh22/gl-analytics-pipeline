-- =============================================================================
-- GL Transactions — PostgreSQL Database Creation Script
-- =============================================================================
-- Creates the gl_transactions schema with dimension tables and a fact table
-- for financial transaction analytics.
--
-- Run order:
--   1. Execute this script to create all tables and constraints.
--   2. Load dimension seed data from database_creation/dimensions_data/
--      (use psql \copy or pgAdmin import).
--   3. Run the sequence reset block at the bottom of this file AFTER loading
--      seed data, to prevent auto-increment conflicts.
--   4. Run transactions_processing notebooks to populate transaction_facts.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Schema
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS gl_transactions;

SET search_path TO gl_transactions;


-- -----------------------------------------------------------------------------
-- Dimension: account
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account (
    account_id          INT             NOT NULL,
    account_type        VARCHAR(45)     NOT NULL,
    account_description VARCHAR(200)    NOT NULL,
    PRIMARY KEY (account_id)
);


-- -----------------------------------------------------------------------------
-- Dimension: transaction_type
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transaction_type (
    transaction_type_id          INT             NOT NULL,
    transaction_type_description VARCHAR(70)     NOT NULL,
    PRIMARY KEY (transaction_type_id),
    UNIQUE (transaction_type_description)
);


-- -----------------------------------------------------------------------------
-- Dimension: category
--
-- NOTE: category_id uses SERIAL (auto-increment) but seed data contains
-- explicit IDs with intentional gaps (5 and 13 are unused).
-- After loading seed data, run the sequence reset block below to prevent
-- future auto-incremented IDs from colliding with existing seed values.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS category (
    category_id          SERIAL          NOT NULL,
    category_description VARCHAR(100)    NOT NULL,
    category_essential   BOOLEAN         NOT NULL,
    PRIMARY KEY (category_id)
);


-- -----------------------------------------------------------------------------
-- Dimension: date
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS date (
    short_date      DATE        NOT NULL,
    weekday_name    VARCHAR(9)  NOT NULL,
    day_month       INT         NOT NULL,
    month_name      VARCHAR(9)  NOT NULL,
    quarter         INT         NOT NULL,
    year            INT         NOT NULL,
    weekday_number  INT         NOT NULL,
    month_number    INT         NOT NULL,
    PRIMARY KEY (short_date)
);


-- -----------------------------------------------------------------------------
-- Fact: transaction_facts
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transaction_facts (
    transaction_id          SERIAL          NOT NULL,
    account_id              INT             NOT NULL,
    transaction_type_id     INT             NOT NULL,
    category_id             INT             NULL,
    short_date              DATE            NOT NULL,
    transaction_description VARCHAR(100)    NULL,
    transaction_amount      DECIMAL(12, 2)  NOT NULL,
    PRIMARY KEY (transaction_id),
    CONSTRAINT fk_transactions_accounts
        FOREIGN KEY (account_id)
        REFERENCES account (account_id),
    CONSTRAINT fk_transactions_transaction_types
        FOREIGN KEY (transaction_type_id)
        REFERENCES transaction_type (transaction_type_id),
    CONSTRAINT fk_transactions_categories
        FOREIGN KEY (category_id)
        REFERENCES category (category_id),
    CONSTRAINT fk_transactions_date
        FOREIGN KEY (short_date)
        REFERENCES date (short_date)
);

-- Index on commonly filtered / joined columns
CREATE INDEX IF NOT EXISTS idx_tf_account_id          ON transaction_facts (account_id);
CREATE INDEX IF NOT EXISTS idx_tf_transaction_type_id ON transaction_facts (transaction_type_id);
CREATE INDEX IF NOT EXISTS idx_tf_category_id         ON transaction_facts (category_id);
CREATE INDEX IF NOT EXISTS idx_tf_short_date          ON transaction_facts (short_date);

-- Enforce that credit and debit purchases (type_id 1 or 2) must have a category
ALTER TABLE transaction_facts
    ADD CONSTRAINT check_transaction_category
    CHECK (
        (transaction_type_id IN (1, 2) AND category_id IS NOT NULL)
        OR
        (transaction_type_id NOT IN (1, 2))
    );


-- =============================================================================
-- STEP 3: Run this block AFTER loading seed data into the category table.
-- It resets the SERIAL sequence so new auto-generated IDs do not collide
-- with the explicit IDs already loaded from category.csv.
-- =============================================================================
-- SELECT setval(
--     pg_get_serial_sequence('gl_transactions.category', 'category_id'),
--     (SELECT MAX(category_id) FROM gl_transactions.category)
-- );
-- =============================================================================
