-- Task 3 - Data Quality Investigation
-- Run each query separately in Snowsight and download the result as CSV.
-- Save each download under dq_exports/ with the filename given above the query.

use schema astrapay.raw;

-- =========================================================================
-- QUERY 1  ->  save as  dq_exports/scorecard.csv
-- One row per data quality check, across the six required dimensions.
-- =========================================================================
-- DQ scorecard: one row per check.
-- dimensions: completeness, validity, uniqueness, consistency, timeliness, reconciliation

with tx_total as (select count(*) n from transaction)

-- ---------------------------------------------------------- completeness --
select 'Completeness' as dimension,
       'transaction.merchant_id is null' as check_name,
       'transaction' as table_name,
       count_if(merchant_id is null) as failed_rows,
       count(*) as total_rows,
       round(100.0 * count_if(merchant_id is null) / count(*), 3) as failed_pct,
       'Warning' as severity,
       'Retain with flag; exclude only from merchant-level breakdowns' as remediation
from transaction

union all
select 'Completeness', 'transaction.customer_id is null', 'transaction',
       count_if(customer_id is null), count(*),
       round(100.0 * count_if(customer_id is null) / count(*), 3),
       'Informational', 'Retain'
from transaction

union all
select 'Completeness', 'transaction.amount is null', 'transaction',
       count_if(amount is null), count(*),
       round(100.0 * count_if(amount is null) / count(*), 3),
       'Blocking', 'Quarantine - cannot compute value'
from transaction

union all
select 'Completeness', 'chargeback.resolved_at is null (still open)', 'chargeback',
       count_if(resolved_at is null), count(*),
       round(100.0 * count_if(resolved_at is null) / count(*), 3),
       'Informational', 'Retain - open cases are a valid business state'
from chargeback

-- -------------------------------------------------------------- validity --
union all
select 'Validity', 'fraud_decision.risk_score outside 0 to 1', 'fraud_decision',
       count_if(risk_score < 0 or risk_score > 1), count(*),
       round(100.0 * count_if(risk_score < 0 or risk_score > 1) / count(*), 3),
       'Blocking', 'Repair - normalise by model_version before any threshold comparison'
from fraud_decision

union all
select 'Validity', 'transaction.amount < 0 with status REVERSED (legitimate)', 'transaction',
       count_if(amount < 0 and status = 'REVERSED'), count(*),
       round(100.0 * count_if(amount < 0 and status = 'REVERSED') / count(*), 3),
       'Informational', 'Retain - genuine reversals, net them rather than dropping'
from transaction

union all
select 'Validity', 'transaction.amount < 0 with status CAPTURED (impossible)', 'transaction',
       count_if(amount < 0 and status = 'CAPTURED'), count(*),
       round(100.0 * count_if(amount < 0 and status = 'CAPTURED') / count(*), 3),
       'Blocking', 'Quarantine - a captured payment cannot carry a negative amount'
from transaction

union all
select 'Validity', 'transaction.amount = 0', 'transaction',
       count_if(amount = 0), count(*),
       round(100.0 * count_if(amount = 0) / count(*), 3),
       'Warning', 'Quarantine - zero-value attempts carry no economics'
from transaction

union all
select 'Validity', 'transaction.status outside the known set', 'transaction',
       count_if(status not in ('CAPTURED','DECLINED','FAILED','REVERSED','PENDING')), count(*),
       round(100.0 * count_if(status not in ('CAPTURED','DECLINED','FAILED','REVERSED','PENDING')) / count(*), 3),
       'Blocking', 'Quarantine'
from transaction

union all
select 'Validity', 'fx_rate.rate_to_usd not positive', 'fx_rate',
       count_if(rate_to_usd <= 0), count(*),
       round(100.0 * count_if(rate_to_usd <= 0) / count(*), 3),
       'Blocking', 'Repair from source'
from fx_rate

union all
select 'Validity', 'route_cost.variable_fee_pct outside 0 to 0.10', 'route_cost',
       count_if(variable_fee_pct < 0 or variable_fee_pct > 0.10), count(*),
       round(100.0 * count_if(variable_fee_pct < 0 or variable_fee_pct > 0.10) / count(*), 3),
       'Blocking', 'Repair from source'
from route_cost

-- ------------------------------------------------------------ uniqueness --
union all
select 'Uniqueness', 'transaction_id is not unique', 'transaction',
       count(*) - count(distinct transaction_id), count(*),
       round(100.0 * (count(*) - count(distinct transaction_id)) / count(*), 3),
       'Blocking', 'Deduplicate - the declared primary key must hold'
from transaction

union all
select 'Uniqueness', 'more than one settlement row per transaction', 'settlement',
       (select count(*) from (select transaction_id from settlement
                              group by transaction_id having count(*) > 1) dup),
       count(*),
       round(100.0 * (select count(*) from (select transaction_id from settlement
                                            group by transaction_id having count(*) > 1) dup2)
             / count(*), 3),
       'Blocking', 'Sum fee_amount to transaction grain before joining'
from settlement

union all
select 'Uniqueness', 'merchant_risk_snapshot composite key is not unique', 'merchant_risk_snapshot',
       count(*) - count(distinct merchant_id || snapshot_month), count(*),
       round(100.0 * (count(*) - count(distinct merchant_id || snapshot_month)) / count(*), 3),
       'Blocking', 'Deduplicate'
from merchant_risk_snapshot

union all
select 'Uniqueness', 'fx_rate composite key is not unique', 'fx_rate',
       count(*) - count(distinct rate_date::varchar || currency || rate_type), count(*),
       round(100.0 * (count(*) - count(distinct rate_date::varchar || currency || rate_type)) / count(*), 3),
       'Blocking', 'Deduplicate'
from fx_rate

-- ----------------------------------------------------------- consistency --
union all
select 'Consistency', 'transaction.merchant_id not found in merchant', 'transaction',
       count_if(t.merchant_id is not null and m.merchant_id is null), count(*),
       round(100.0 * count_if(t.merchant_id is not null and m.merchant_id is null) / count(*), 3),
       'Blocking', 'Quarantine - orphaned merchant reference'
from transaction t left join merchant m on t.merchant_id = m.merchant_id

union all
select 'Consistency', 'settlement.transaction_id not found in transaction', 'settlement',
       count_if(t.transaction_id is null), count(*),
       round(100.0 * count_if(t.transaction_id is null) / count(*), 3),
       'Blocking', 'Exclude and report as a reconciliation break to Finance Operations'
from settlement s left join transaction t on s.transaction_id = t.transaction_id

union all
select 'Consistency', 'chargeback.transaction_id not found in transaction', 'chargeback',
       count_if(t.transaction_id is null), count(*),
       round(100.0 * count_if(t.transaction_id is null) / count(*), 3),
       'Blocking', 'Exclude'
from chargeback c left join transaction t on c.transaction_id = t.transaction_id

union all
select 'Consistency', 'chargeback raised against a non-captured transaction', 'chargeback',
       count_if(t.status is not null and t.status <> 'CAPTURED'), count(*),
       round(100.0 * count_if(t.status is not null and t.status <> 'CAPTURED') / count(*), 3),
       'Blocking', 'Quarantine - a payment that never captured cannot be charged back'
from chargeback c left join transaction t on c.transaction_id = t.transaction_id

union all
select 'Consistency', 'transaction has no CREATED lifecycle event', 'transaction',
       (select count(*) from transaction t
        where not exists (select 1 from payment_event e
                          where e.transaction_id = t.transaction_id
                            and e.event_type = 'CREATED')),
       (select n from tx_total),
       round(100.0 * (select count(*) from transaction t
                      where not exists (select 1 from payment_event e
                                        where e.transaction_id = t.transaction_id
                                          and e.event_type = 'CREATED'))
             / (select n from tx_total), 3),
       'Warning', 'Retain with flag - event pipeline gap'
from (select 1) d

-- ------------------------------------------------------------- timeliness --
union all
select 'Timeliness', 'event ingested more than 2 days after it occurred', 'payment_event',
       count_if(datediff('hour', event_time, ingestion_time) > 48), count(*),
       round(100.0 * count_if(datediff('hour', event_time, ingestion_time) > 48) / count(*), 3),
       'Warning', 'Retain - use event_time for KPI periods, ingestion_time for lag reporting'
from payment_event

union all
select 'Timeliness', 'event_time earlier than the parent transaction created_at', 'payment_event',
       count_if(e.event_time < t.created_at), count(*),
       round(100.0 * count_if(e.event_time < t.created_at) / count(*), 3),
       'Blocking', 'Quarantine - an event cannot precede its transaction'
from payment_event e join transaction t on e.transaction_id = t.transaction_id

union all
select 'Timeliness', 'chargeback opened before the transaction occurred', 'chargeback',
       count_if(c.opened_at < t.created_at), count(*),
       round(100.0 * count_if(c.opened_at < t.created_at) / count(*), 3),
       'Blocking', 'Quarantine'
from chargeback c join transaction t on c.transaction_id = t.transaction_id

union all
select 'Timeliness', 'settlement dated before the transaction occurred', 'settlement',
       count_if(s.settlement_date < t.created_at::date), count(*),
       round(100.0 * count_if(s.settlement_date < t.created_at::date) / count(*), 3),
       'Blocking', 'Quarantine'
from settlement s join transaction t on s.transaction_id = t.transaction_id

-- --------------------------------------------------------- reconciliation --
union all
select 'Reconciliation', 'captured transaction with no settlement row', 'transaction',
       (select count(*) from transaction t
        where t.status = 'CAPTURED'
          and not exists (select 1 from settlement s where s.transaction_id = t.transaction_id)),
       (select count(*) from transaction where status = 'CAPTURED'),
       round(100.0 * (select count(*) from transaction t
                      where t.status = 'CAPTURED'
                        and not exists (select 1 from settlement s
                                        where s.transaction_id = t.transaction_id))
             / (select count(*) from transaction where status = 'CAPTURED'), 3),
       'Blocking', 'Retain with flag and impute the fee from route_cost; excluding them biases recent months'
from (select 1) d

union all
select 'Reconciliation', 'settlement value does not match transaction value in USD', 'settlement',
       (select count(*)
        from settlement s
        join transaction t on s.transaction_id = t.transaction_id
        join fx_rate f on f.currency = t.currency
                      and f.rate_date = t.created_at::date
                      and f.rate_type = 'SETTLEMENT'
        where abs((s.settlement_amount + s.fee_amount) - (t.amount * f.rate_to_usd)) > 0.01),
       (select count(*) from settlement s join transaction t on s.transaction_id = t.transaction_id),
       round(100.0 * (select count(*)
                      from settlement s
                      join transaction t on s.transaction_id = t.transaction_id
                      join fx_rate f on f.currency = t.currency
                                    and f.rate_date = t.created_at::date
                                    and f.rate_type = 'SETTLEMENT'
                      where abs((s.settlement_amount + s.fee_amount) - (t.amount * f.rate_to_usd)) > 0.01)
             / (select count(*) from settlement s
                join transaction t on s.transaction_id = t.transaction_id), 3),
       'Blocking', 'Sum settlement rows to transaction grain before reconciling'
from (select 1) d

order by dimension, check_name;


-- =========================================================================
-- QUERY 2  ->  save as  dq_exports/missing_merchant_by_channel.csv
-- Missing merchant_id by channel
-- =========================================================================
-- Is the missing-merchant defect uniform, or concentrated?
select channel,
       count(*) as attempts,
       count_if(merchant_id is null) as missing_merchant,
       round(100.0 * count_if(merchant_id is null) / count(*), 3) as missing_pct
from transaction
group by channel
order by missing_pct desc;


-- =========================================================================
-- QUERY 3  ->  save as  dq_exports/risk_score_by_model.csv
-- Risk score range by model version
-- =========================================================================
-- Out-of-range risk scores: which model version emits them?
select model_version,
       count(*) as decisions,
       round(min(risk_score), 4) as min_score,
       round(max(risk_score), 4) as max_score,
       count_if(risk_score > 1) as above_one,
       round(100.0 * count_if(risk_score > 1) / count(*), 2) as above_one_pct
from fraud_decision
group by model_version
order by model_version;


-- =========================================================================
-- QUERY 4  ->  save as  dq_exports/event_lag_by_month.csv
-- Event arrival lag by month
-- =========================================================================
-- Timeliness: how late do events arrive, and is it getting worse?
select to_char(e.event_time, 'YYYY-MM') as event_month,
       count(*) as events,
       count_if(datediff('hour', e.event_time, e.ingestion_time) > 48) as late_over_2d,
       round(100.0 * count_if(datediff('hour', e.event_time, e.ingestion_time) > 48) / count(*), 2) as late_pct,
       round(max(datediff('hour', e.event_time, e.ingestion_time)) / 24.0, 1) as max_lag_days
from payment_event e
group by 1
order by 1;


-- =========================================================================
-- QUERY 5  ->  save as  dq_exports/settlement_coverage_by_month.csv
-- Settlement coverage by month
-- =========================================================================
-- Reconciliation: captured transactions missing a settlement row, by month
select to_char(t.created_at, 'YYYY-MM') as txn_month,
       count(*) as captured,
       count_if(s.transaction_id is null) as no_settlement,
       round(100.0 * count_if(s.transaction_id is null) / count(*), 2) as no_settlement_pct
from transaction t
left join (select distinct transaction_id from settlement) s
       on t.transaction_id = s.transaction_id
where t.status = 'CAPTURED'
group by 1
order by 1;


-- =========================================================================
-- QUERY 6  ->  save as  dq_exports/latency_by_provider_month.csv
-- Processing latency by provider and month
-- =========================================================================
-- Is latency deterioration uniform, or concentrated in one provider and period?
select r.provider,
       to_char(t.created_at, 'YYYY-MM') as txn_month,
       count(*) as attempts,
       round(median(e.processing_ms)) as p50_ms,
       round(percentile_cont(0.95) within group (order by e.processing_ms)) as p95_ms
from transaction t
join (select distinct route_id, provider from route_cost) r on t.route_id = r.route_id
join payment_event e on e.transaction_id = t.transaction_id
group by 1, 2
order by 1, 2;


-- =========================================================================
-- QUERY 7  ->  save as  dq_exports/fanout_proof.csv
-- Fan-out inflation proof
-- =========================================================================
-- Proves a one-to-many join inflates payment amount.
-- Required evidence for the data contract, and for Task 7.
with base as (
    select sum(amount) as gpv, count(*) as rows_in
    from transaction where status = 'CAPTURED'
),
naive_snapshot as (
    select sum(t.amount) as gpv, count(*) as rows_in
    from transaction t
    join merchant_risk_snapshot s on t.merchant_id = s.merchant_id
    where t.status = 'CAPTURED'
),
naive_fraud as (
    select sum(t.amount) as gpv, count(*) as rows_in
    from transaction t
    join fraud_decision f on t.transaction_id = f.transaction_id
    where t.status = 'CAPTURED'
),
correct_fraud as (
    select sum(t.amount) as gpv, count(*) as rows_in
    from transaction t
    join (select transaction_id, max(risk_score) as max_score
          from fraud_decision group by transaction_id) f
      on t.transaction_id = f.transaction_id
    where t.status = 'CAPTURED'
)
select 'correct: no join'                as method, rows_in, gpv, 1.0 as inflation from base
union all
select 'naive join to risk snapshot',    rows_in, gpv,
       round(gpv / (select gpv from base), 2) from naive_snapshot
union all
select 'naive join to fraud decision',   rows_in, gpv,
       round(gpv / (select gpv from base), 2) from naive_fraud
union all
select 'correct: fraud pre-aggregated',  rows_in, gpv,
       round(gpv / (select gpv from base), 2) from correct_fraud;
