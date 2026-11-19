-- Explicit evidence connecting a carton and its shipment source/allocation.
-- No historic shipment is assigned or received by this migration.
ALTER TABLE production_shipment_allocation ADD UNIQUE KEY shipment_allocation_site(site_id,id);

CREATE TABLE destination_shipment_binding (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 site_id BIGINT NOT NULL, shipment_id BIGINT NOT NULL,
 source_line_id BIGINT NOT NULL, allocation_id BIGINT NULL,
 carton_id CHAR(36) NOT NULL, sku_id BIGINT NOT NULL, units BIGINT NOT NULL,
 shipment_revision BIGINT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE, actor_id BIGINT NOT NULL,
 actor_name VARCHAR(255) NOT NULL, reason VARCHAR(2000) NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY binding_site(site_id,id),
 KEY binding_shipment(site_id,shipment_id),
 FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id),
 FOREIGN KEY(site_id,source_line_id) REFERENCES production_shipment_source_line(site_id,id),
 FOREIGN KEY(site_id,allocation_id) REFERENCES production_shipment_allocation(site_id,id),
 CHECK(units>0)
) ENGINE=InnoDB;

CREATE TABLE destination_receipt_upload (
 id CHAR(36) NOT NULL PRIMARY KEY, site_id BIGINT NOT NULL, shipment_id BIGINT NOT NULL,
 actor_id BIGINT NOT NULL, filename VARCHAR(255) NOT NULL, digest CHAR(64) NOT NULL,
 file_data MEDIUMBLOB NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY destination_upload_site(site_id,id),
 FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id)
) ENGINE=InnoDB;

CREATE TABLE destination_receipt (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 site_id BIGINT NOT NULL, shipment_id BIGINT NOT NULL,
 shipment_revision BIGINT NOT NULL, warehouse_id BIGINT NULL, owner_id BIGINT NULL,
 replaces_receipt_id BIGINT NULL, upload_id CHAR(36) NULL,
 business_date DATE NULL, reason VARCHAR(2000) NOT NULL DEFAULT '',
 status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', revision BIGINT NOT NULL DEFAULT 1,
 actor_id BIGINT NOT NULL, actor_name VARCHAR(255) NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY destination_receipt_site(site_id,id),
 KEY destination_receipt_shipment(site_id,shipment_id,status),
 FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id),
 FOREIGN KEY(site_id,replaces_receipt_id) REFERENCES destination_receipt(site_id,id),
 FOREIGN KEY(site_id,upload_id) REFERENCES destination_receipt_upload(site_id,id),
 FOREIGN KEY(site_id,warehouse_id,owner_id) REFERENCES inventory_scope(site_id,warehouse_id,owner_id),
 CHECK(status IN ('DRAFT','POSTED','REVERSED'))
) ENGINE=InnoDB;

CREATE TABLE destination_receipt_line (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 receipt_id BIGINT NOT NULL, binding_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 catalog_version VARCHAR(64) NOT NULL, qualified_units BIGINT NOT NULL DEFAULT 0,
 pending_units BIGINT NOT NULL DEFAULT 0, defective_units BIGINT NOT NULL DEFAULT 0,
 UNIQUE KEY receipt_line_site(site_id,id), UNIQUE KEY receipt_binding(site_id,receipt_id,binding_id),
 FOREIGN KEY(site_id,receipt_id) REFERENCES destination_receipt(site_id,id),
 FOREIGN KEY(site_id,binding_id) REFERENCES destination_shipment_binding(site_id,id),
 CHECK(qualified_units>=0 AND pending_units>=0 AND defective_units>=0)
) ENGINE=InnoDB;

CREATE TABLE destination_receipt_settlement (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 binding_id BIGINT NOT NULL, units BIGINT NOT NULL, reason VARCHAR(2000) NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', revision BIGINT NOT NULL DEFAULT 1,
 actor_id BIGINT NOT NULL, actor_name VARCHAR(255) NOT NULL, operation_token CHAR(36) NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY destination_settlement_site(site_id,id),
 FOREIGN KEY(site_id,binding_id) REFERENCES destination_shipment_binding(site_id,id),
 CHECK(status IN ('ACTIVE','REVERSED')), CHECK(units>0)
) ENGINE=InnoDB;
