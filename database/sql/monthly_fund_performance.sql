-- Step 1: Aggregate symbol-level Market Value and Realized P/L by fund and month
WITH monthly_fund_totals AS (
    SELECT
        fund_name,
        report_date,
        SUM(market_value) AS fund_mv_end,
        SUM(realised_pl) AS fund_realized_pl
    FROM fund_positions
    GROUP BY fund_name, report_date
),

-- Step 2: Retrieve start-of-month market value using window LAG()
monthly_ror AS (
    SELECT
        fund_name,
        report_date,
        fund_mv_end,
        fund_realized_pl,
        LAG(fund_mv_end) OVER (
            PARTITION BY fund_name
            ORDER BY report_date
        ) AS fund_mv_start
    FROM monthly_fund_totals
),

-- Step 3: Compute monthly Rate of Return per fund
ror_calculated AS (
    SELECT
        fund_name,
        report_date,
        fund_mv_start,
        fund_mv_end,
        fund_realized_pl,
        (fund_mv_end - fund_mv_start + fund_realized_pl) / NULLIF(fund_mv_start, 0) AS rate_of_return
    FROM monthly_ror
    WHERE fund_mv_start IS NOT NULL  -- Excludes initial baseline month
),

-- Step 4: Rank funds by Rate of Return for each month
ranked_funds AS (
    SELECT
        report_date,
        fund_name AS best_performing_fund,
        ROUND(fund_mv_start, 2) AS fund_mv_start,
        ROUND(fund_mv_end, 2) AS fund_mv_end,
        ROUND(fund_realized_pl, 2) AS realized_pl,
        ROUND(rate_of_return * 100, 4) AS ror_pct,
        ROW_NUMBER() OVER (
            PARTITION BY report_date
            ORDER BY rate_of_return DESC
        ) AS rk
    FROM ror_calculated
)

-- Step 5: Select single top-performing fund per month
SELECT
    report_date,
    best_performing_fund,
    fund_mv_start,
    fund_mv_end,
    realized_pl,
    ror_pct
FROM ranked_funds
WHERE rk = 1
ORDER BY report_date;