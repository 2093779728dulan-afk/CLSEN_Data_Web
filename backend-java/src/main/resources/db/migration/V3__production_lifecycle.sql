ALTER TABLE production_order_line
 ADD COLUMN tracking_state VARCHAR(6) NOT NULL DEFAULT 'OPEN',
 ADD COLUMN closed_units BIGINT NOT NULL DEFAULT 0,
 ADD COLUMN closed_at TIMESTAMP(6) NULL,
 ADD CHECK(tracking_state IN ('OPEN','CLOSED')),
 ADD CHECK(closed_units>=0);
ALTER TABLE production_shipment_allocation ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE production_shipment_source_line
 ADD COLUMN replaces_source_id BIGINT NULL,
 ADD FOREIGN KEY(site_id,replaces_source_id) REFERENCES production_shipment_source_line(site_id,id);
ALTER TABLE production_revision
 ADD COLUMN operation_kind VARCHAR(40) NOT NULL DEFAULT 'LEGACY',
 ADD COLUMN effective_date DATE NULL;
