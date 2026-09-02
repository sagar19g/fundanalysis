-- Step 1: Clean raw positions (excluding cash holdings)
WITH raw_positions AS (
    SELECT DISTINCT
        fund_name,
        report_date,
        financial_type,
        symbol,
        security_name,
        sedol,
        price AS fund_price,
        CASE
            WHEN LOWER(financial_type) LIKE '%equit%' THEN 'EQUITY'
            WHEN LOWER(financial_type) LIKE '%bond%' OR LOWER(financial_type) LIKE '%debt%' THEN 'BOND'
            ELSE 'OTHER'
        END AS asset_class
    FROM fund_positions
    WHERE LOWER(financial_type) NOT LIKE '%cash%'
),

-- Step 2: Map Bond identifiers to ISIN with explicit NULL safeguards
bond_isin_mappings AS (
    SELECT DISTINCT
        p.sedol,
        p.security_name,
        br.ISIN
    FROM raw_positions p
    LEFT JOIN bond_reference br
           ON (br.SEDOL = p.sedol AND p.sedol IS NOT NULL AND p.sedol <> '')
           OR (br."SECURITY NAME" = p.security_name AND p.security_name IS NOT NULL)
    WHERE p.asset_class = 'BOND'
),

-- Step 3: Match Equity prices using pre-indexed temp table
equity_prices_asof AS (
    SELECT
        p.fund_name,
        p.report_date,
        p.symbol,
        ep.PRICE AS ref_price,
        ep.iso_ref_date AS ref_price_date
    FROM raw_positions p
    LEFT JOIN norm_eq_prices ep
           ON ep.SYMBOL = p.symbol
          AND ep.iso_ref_date = (
              SELECT MAX(ep_sub.iso_ref_date)
              FROM norm_eq_prices ep_sub
              WHERE ep_sub.SYMBOL = p.symbol
                AND ep_sub.iso_ref_date <= p.report_date
          )
    WHERE p.asset_class = 'EQUITY'
),

-- Step 4: Match Bond prices using pre-indexed temp table
bond_prices_asof AS (
    SELECT
        p.fund_name,
        p.report_date,
        p.security_name,
        p.sedol,
        bp.PRICE AS ref_price,
        bp.iso_ref_date AS ref_price_date
    FROM raw_positions p
    LEFT JOIN bond_isin_mappings bm
           ON (bm.sedol = p.sedol AND p.sedol IS NOT NULL AND p.sedol <> '')
           OR (bm.security_name = p.security_name AND p.security_name IS NOT NULL)
    LEFT JOIN norm_bd_prices bp
           ON bp.ISIN = bm.ISIN
          AND bp.iso_ref_date = (
              SELECT MAX(bp_sub.iso_ref_date)
              FROM norm_bd_prices bp_sub
              WHERE bp_sub.ISIN = bm.ISIN
                AND bp_sub.iso_ref_date <= p.report_date
          )
    WHERE p.asset_class = 'BOND'
),

-- Step 5: Combine position data with single fallback reference price
reconciled_positions AS (
    SELECT
        rp.fund_name,
        rp.report_date,
        rp.financial_type,
        rp.symbol,
        rp.security_name,
        rp.sedol,
        rp.fund_price,
        COALESCE(eq.ref_price, bd.ref_price) AS ref_price,
        COALESCE(eq.ref_price_date, bd.ref_price_date) AS ref_price_date
    FROM raw_positions rp
    LEFT JOIN equity_prices_asof eq
           ON rp.asset_class = 'EQUITY'
          AND rp.fund_name = eq.fund_name
          AND rp.report_date = eq.report_date
          AND rp.symbol = eq.symbol
    LEFT JOIN bond_prices_asof bd
           ON rp.asset_class = 'BOND'
          AND rp.fund_name = bd.fund_name
          AND rp.report_date = bd.report_date
          AND ((rp.sedol = bd.sedol AND rp.sedol IS NOT NULL) OR (rp.security_name = bd.security_name AND rp.security_name IS NOT NULL))
)

-- Step 6: Output calculations with division-by-zero guard
SELECT DISTINCT
    fund_name,
    report_date,
    financial_type,
    symbol,
    security_name,
    sedol,
    fund_price,
    ref_price,
    ref_price_date,
    ROUND(fund_price - ref_price, 4) AS price_break,
    ROUND(ABS(fund_price - ref_price) / NULLIF(ref_price, 0) * 100, 2) AS price_break_pct,
    CASE
        WHEN ref_price IS NULL THEN 'MISSING_REF_PRICE'
        WHEN ABS(fund_price - ref_price) > 0.01 THEN 'PRICE_BREAK'
        ELSE 'MATCH'
    END AS status
FROM reconciled_positions;