-- Exact scoped provenance. Existing facts remain unclassified; no historical backfill.
ALTER TABLE production_order
 ADD source_system VARCHAR(120) NOT NULL DEFAULT '',
 ADD source_event_kind VARCHAR(64) NOT NULL DEFAULT '',
 ADD external_event_id VARCHAR(120) NOT NULL DEFAULT '',
 ADD source_batch VARCHAR(120) NOT NULL DEFAULT '',
 ADD manual_source_note VARCHAR(2000) NOT NULL DEFAULT '',
 ADD source_signature CHAR(64) NULL,
 ADD KEY order_source_candidates(site_id,business_date,source_signature);
ALTER TABLE production_shipment
 ADD source_system VARCHAR(120) NOT NULL DEFAULT '',
 ADD source_event_kind VARCHAR(64) NOT NULL DEFAULT '',
 ADD external_event_id VARCHAR(120) NOT NULL DEFAULT '',
 ADD source_batch VARCHAR(120) NOT NULL DEFAULT '',
 ADD manual_source_note VARCHAR(2000) NOT NULL DEFAULT '',
 ADD source_signature CHAR(64) NULL,
 ADD dispatch_purpose VARCHAR(32) NOT NULL DEFAULT 'LEGACY_UNCLASSIFIED',
 ADD KEY shipment_source_candidates(site_id,business_date,source_signature);
CREATE TABLE production_business_source (
 site_id BIGINT NOT NULL, document_kind VARCHAR(16) NOT NULL,
 source_key CHAR(64) NOT NULL, content_hash CHAR(64) NOT NULL,
 source_system VARCHAR(120) NOT NULL, source_event_kind VARCHAR(64) NOT NULL,
 external_event_id VARCHAR(120) NOT NULL, source_batch VARCHAR(120) NOT NULL,
 document_id BIGINT NULL,
 PRIMARY KEY(site_id,document_kind,source_key),
 CHECK(document_kind IN ('orders','shipments'))
) ENGINE=InnoDB;
