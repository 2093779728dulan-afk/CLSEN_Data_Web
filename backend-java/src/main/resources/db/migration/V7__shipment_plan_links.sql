-- Explicit source-line to expected outbound plan relation. Existing shipments stay unlinked.
ALTER TABLE production_shipment_source_line
 ADD plan_id BIGINT NULL,
 ADD KEY shipment_source_plan(site_id,plan_id),
 ADD CONSTRAINT shipment_source_plan_fk FOREIGN KEY(site_id,plan_id) REFERENCES inventory_plan(site_id,id);
