-- A manual follow-up label; it does not participate in quantity or completion rules.
ALTER TABLE production_order_line
 ADD COLUMN production_status VARCHAR(64) NOT NULL DEFAULT '';
