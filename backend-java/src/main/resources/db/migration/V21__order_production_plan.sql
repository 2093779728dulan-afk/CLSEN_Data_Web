-- NULL follows the order quantity; historical orders retain their original target.
ALTER TABLE production_order_line
 ADD COLUMN planned_production_units BIGINT UNSIGNED NULL,
 ADD COLUMN production_plan_reason VARCHAR(2000) NOT NULL DEFAULT '';
