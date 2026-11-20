-- =============================================================================
-- GL Transactions — PostgreSQL Analytical Views
-- =============================================================================
-- All views target the gl_transactions schema.
-- Set search path before running, or qualify each object with the schema name.
-- =============================================================================

SET search_path TO gl_transactions;


-- -----------------------------------------------------------------------------
-- View: monthly_spend_summary
-- Shows total spent per month, percentage change from the prior month,
-- and a running yearly total — using only credit-card and debit purchases.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW monthly_spend_summary AS
WITH cte AS (
    SELECT
        d.month_number,
        d.month_name    AS month,
        d.year,
        SUM(ABS(tf.transaction_amount)) AS month_amount_spent
    FROM transaction_facts AS tf
    JOIN transaction_type  AS t  USING (transaction_type_id)
    JOIN category          AS c  USING (category_id)
    JOIN date              AS d  USING (short_date)
    WHERE t.transaction_type_id IN (1, 2)   -- purchases only
      AND d.year != 2022
    GROUP BY d.month_name, d.month_number, d.year
)
SELECT
    *,
    ROUND(
        (month_amount_spent - LAG(month_amount_spent) OVER (ORDER BY year, month_number))
        / NULLIF(LAG(month_amount_spent) OVER (ORDER BY year, month_number), 0),
        4
    ) AS prior_month_change,
    SUM(month_amount_spent) OVER (
        PARTITION BY year
        ORDER BY year, month_number
    ) AS yearly_running_total
FROM cte
ORDER BY year, month_number;


-- -----------------------------------------------------------------------------
-- View: monthly_spend_category
-- Shows and ranks spending per category per month.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW monthly_spend_category AS
SELECT
    d.year,
    d.month_number,
    d.month_name,
    c.category_description,
    SUM(ABS(tf.transaction_amount)) AS monthly_spend,
    RANK() OVER (
        PARTITION BY d.month_number, d.month_name, d.year
        ORDER BY SUM(ABS(tf.transaction_amount)) DESC
    ) AS month_ranking
FROM transaction_facts AS tf
JOIN category          AS c  USING (category_id)
JOIN account           AS a  USING (account_id)
JOIN transaction_type  AS t  USING (transaction_type_id)
JOIN date              AS d  USING (short_date)
WHERE t.transaction_type_id IN (1, 2)
  AND d.year != 2022
GROUP BY d.month_number, d.month_name, d.year, c.category_description
ORDER BY d.year, d.month_number, month_ranking;


-- -----------------------------------------------------------------------------
-- View: daily_spend
-- All purchase transactions with a running yearly spend total.
-- Uses a LEFT JOIN from the date table so days with no purchases appear as 0.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW daily_spend AS
SELECT
    tf.transaction_id,
    d.short_date,
    t.transaction_type_description,
    c.category_description,
    tf.transaction_description,
    COALESCE(ABS(tf.transaction_amount), 0) AS transaction_total,
    d.year,
    SUM(ABS(tf.transaction_amount)) OVER (
        PARTITION BY d.year
        ORDER BY d.short_date, tf.transaction_id
    ) AS running_yearly_spend
FROM date AS d
LEFT JOIN transaction_facts AS tf
       ON d.short_date = tf.short_date
      AND tf.transaction_type_id IN (1, 2)
LEFT JOIN transaction_type  AS t  USING (transaction_type_id)
LEFT JOIN category          AS c  USING (category_id)
WHERE d.short_date <= CURRENT_DATE
  AND d.year != 2022
ORDER BY d.short_date;


-- -----------------------------------------------------------------------------
-- View: daily_category_balance
-- Running spend per category at daily granularity (used by Power BI visuals).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW daily_category_balance AS
WITH date_category AS (
    SELECT
        d.short_date,
        c.category_id
    FROM date AS d
    CROSS JOIN (SELECT category_id FROM category) AS c
    WHERE d.year != 2022
      AND d.short_date <= CURRENT_DATE
)
SELECT
    dc.short_date,
    dc.category_id,
    COALESCE(SUM(ABS(tf.transaction_amount)), 0) AS day_sum
FROM date_category AS dc
LEFT JOIN transaction_facts AS tf
       ON dc.short_date = tf.short_date
      AND dc.category_id = tf.category_id
LEFT JOIN transaction_type  AS t
       ON tf.transaction_type_id = t.transaction_type_id
      AND t.transaction_type_id IN (1, 2)
WHERE EXTRACT(YEAR FROM dc.short_date) != 2022
  AND dc.short_date <= CURRENT_DATE
GROUP BY dc.short_date, dc.category_id
ORDER BY dc.short_date, dc.category_id;


-- -----------------------------------------------------------------------------
-- View: monthly_account_balances
-- End-of-month running balance per account (useful for the account KPI cards).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW monthly_account_balances AS
SELECT
    TO_CHAR(DATE_TRUNC('month', d.short_date), 'YYYY-MM') AS end_date_period,
    tf.account_id,
    a.account_type,
    SUM(SUM(tf.transaction_amount)) OVER (
        PARTITION BY tf.account_id
        ORDER BY TO_CHAR(DATE_TRUNC('month', d.short_date), 'YYYY-MM')
    ) AS balance
FROM transaction_facts AS tf
JOIN account AS a USING (account_id)
JOIN date    AS d USING (short_date)
GROUP BY end_date_period, tf.account_id, a.account_type
ORDER BY end_date_period;
