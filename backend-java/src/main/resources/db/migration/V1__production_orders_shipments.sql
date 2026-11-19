CREATE TABLE production_order (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 system_number VARCHAR(64) NOT NULL, business_number VARCHAR(120) NOT NULL DEFAULT '',
 business_date DATE NULL, notes VARCHAR(2000) NOT NULL DEFAULT '',
 status VARCHAR(16) NOT NULL, revision BIGINT NOT NULL DEFAULT 1,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY order_scope_id(site_id,id), UNIQUE KEY order_number(site_id,system_number),
 KEY order_listing(site_id,status,business_date,id), CHECK(status IN ('DRAFT','CONFIRMED','VOID'))
) ENGINE=InnoDB;
CREATE TABLE production_order_line (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL, order_id BIGINT NOT NULL,
 sku_id BIGINT NOT NULL, sku_label VARCHAR(255) NOT NULL, catalog_version VARCHAR(64) NOT NULL,
 expected_units BIGINT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE,
 UNIQUE KEY order_sku(site_id,order_id,sku_id), UNIQUE KEY order_line_scope(site_id,id),
 FOREIGN KEY(site_id,order_id) REFERENCES production_order(site_id,id), CHECK(expected_units>0)
) ENGINE=InnoDB;
CREATE TABLE production_shipment (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 system_number VARCHAR(64) NOT NULL, business_number VARCHAR(120) NOT NULL DEFAULT '',
 business_date DATE NULL, notes VARCHAR(2000) NOT NULL DEFAULT '',
 status VARCHAR(16) NOT NULL, revision BIGINT NOT NULL DEFAULT 1,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY shipment_scope_id(site_id,id), UNIQUE KEY shipment_number(site_id,system_number),
 KEY shipment_listing(site_id,status,business_date,id), CHECK(status IN ('DRAFT','CONFIRMED','VOID'))
) ENGINE=InnoDB;
CREATE TABLE production_shipment_source_line (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL, shipment_id BIGINT NOT NULL,
 sku_id BIGINT NOT NULL, sku_label VARCHAR(255) NOT NULL, catalog_version VARCHAR(64) NOT NULL,
 actual_units BIGINT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE,
 UNIQUE KEY source_scope(site_id,id), KEY shipment_sources(site_id,shipment_id,is_active),
 FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id), CHECK(actual_units>0)
) ENGINE=InnoDB;
CREATE TABLE production_shipment_allocation (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 source_line_id BIGINT NOT NULL, order_line_id BIGINT NOT NULL, units BIGINT NOT NULL,
 UNIQUE KEY source_order_line(site_id,source_line_id,order_line_id),
 KEY allocation_order(site_id,order_line_id),
 FOREIGN KEY(site_id,source_line_id) REFERENCES production_shipment_source_line(site_id,id),
 FOREIGN KEY(site_id,order_line_id) REFERENCES production_order_line(site_id,id), CHECK(units>0)
) ENGINE=InnoDB;
CREATE TABLE production_revision (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL, document_kind VARCHAR(16) NOT NULL,
 document_id BIGINT NOT NULL, revision BIGINT NOT NULL, actor_id BIGINT NOT NULL,
 operation_token CHAR(36) NOT NULL, reason VARCHAR(2000) NOT NULL,
 before_value JSON NULL, after_value JSON NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY document_revision(site_id,document_kind,document_id,revision)
) ENGINE=InnoDB;
CREATE TABLE production_command (
 site_id BIGINT NOT NULL, actor_id BIGINT NOT NULL, operation_token CHAR(36) NOT NULL,
 fingerprint CHAR(64) NOT NULL, result JSON NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(site_id,actor_id,operation_token)
) ENGINE=InnoDB;
