-- Manual facts and report evidence share the existing receipt event ledger.
ALTER TABLE fba_receipt_batch
 ADD COLUMN source_kind VARCHAR(16) NOT NULL DEFAULT 'REPORT',
 ADD COLUMN shipment_id BIGINT NULL,
 ADD COLUMN draft_payload JSON NULL,
 ADD FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id);
ALTER TABLE fba_receipt_event
 MODIFY reference_id BIGINT NULL,
 MODIFY occurred_at TIMESTAMP(6) NULL,
 ADD COLUMN source_kind VARCHAR(16) NOT NULL DEFAULT 'REPORT',
 ADD COLUMN shipment_id BIGINT NULL,
 ADD COLUMN time_precision VARCHAR(16) NOT NULL DEFAULT 'TIMESTAMP',
 ADD COLUMN source_fingerprint CHAR(64) NULL,
 ADD FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id);
UPDATE fba_receipt_event e JOIN fba_reference r ON r.site_id=e.site_id AND r.id=e.reference_id
 SET e.shipment_id=r.shipment_id,e.source_fingerprint=e.fingerprint;
ALTER TABLE fba_receipt_resolution
 ADD COLUMN source_fingerprint CHAR(64) NULL,
 ADD COLUMN confirmed_units BIGINT NULL,
 ADD COLUMN linked_units BIGINT NOT NULL DEFAULT 0;
CREATE TABLE fba_report_coverage (
 site_id BIGINT NOT NULL, batch_id BIGINT NOT NULL, source_row INT NOT NULL,
 event_id BIGINT NOT NULL, units BIGINT NOT NULL,
 evidence VARCHAR(2000) NOT NULL, actor_id BIGINT NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(site_id,batch_id,source_row,event_id),
 FOREIGN KEY(site_id,batch_id) REFERENCES fba_receipt_batch(site_id,id),
 FOREIGN KEY(site_id,event_id) REFERENCES fba_receipt_event(site_id,id),
 CHECK(units>0)
) ENGINE=InnoDB;
