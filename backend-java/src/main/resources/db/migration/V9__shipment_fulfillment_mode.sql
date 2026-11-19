-- A packing document may mix warehouse stock with goods shipped directly from production.
-- Existing rows keep the former warehouse-stock behavior.
ALTER TABLE production_shipment_source_line
 ADD fulfillment_mode VARCHAR(32) NOT NULL DEFAULT 'WAREHOUSE_STOCK',
 ADD CONSTRAINT shipment_fulfillment_mode_check
 CHECK(fulfillment_mode IN ('WAREHOUSE_STOCK','PRODUCTION_DIRECT'));
