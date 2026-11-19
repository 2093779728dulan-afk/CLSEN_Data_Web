-- Logistics evidence only. No stock, receipt or shipment quantities are changed.
CREATE TABLE shipment_transport (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 site_id BIGINT NOT NULL, shipment_id BIGINT NOT NULL, shipment_revision BIGINT NOT NULL,
 carrier VARCHAR(255) NOT NULL, tracking_number VARCHAR(255) NOT NULL,
 estimated_arrival TIMESTAMP(6) NULL, arrival_local VARCHAR(64) NOT NULL DEFAULT '',
 arrival_timezone VARCHAR(80) NOT NULL DEFAULT '', source_reference VARCHAR(2000) NOT NULL,
 source_snapshot JSON NOT NULL, revision BIGINT NOT NULL DEFAULT 1,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY transport_site(site_id,id), UNIQUE KEY transport_shipment(site_id,shipment_id),
 FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id)
) ENGINE=InnoDB;

CREATE TABLE shipment_transport_event (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 site_id BIGINT NOT NULL, transport_id BIGINT NOT NULL,
 event_kind VARCHAR(24) NOT NULL, occurred_at TIMESTAMP(6) NOT NULL,
 occurred_local VARCHAR(64) NOT NULL, timezone VARCHAR(80) NOT NULL,
 location VARCHAR(255) NOT NULL DEFAULT '', description VARCHAR(2000) NOT NULL DEFAULT '',
 source_reference VARCHAR(2000) NOT NULL, signed_units BIGINT NULL,
 revision BIGINT NOT NULL DEFAULT 1,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY transport_event_site(site_id,id),
 KEY transport_timeline(site_id,transport_id,occurred_at,id),
 FOREIGN KEY(site_id,transport_id) REFERENCES shipment_transport(site_id,id),
 CHECK(event_kind IN ('DISPATCHED','IN_TRANSIT','ARRIVED','SIGNED','EXCEPTION')),
 CHECK(signed_units IS NULL OR (event_kind='SIGNED' AND signed_units>=0))
) ENGINE=InnoDB;
