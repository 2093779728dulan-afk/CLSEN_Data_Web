-- Inventory is opt-in by a server-owned site/warehouse scope. No historic backfill.
CREATE TABLE inventory_site_lock(site_id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB;
CREATE TABLE inventory_scope (
 site_id BIGINT NOT NULL, warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL,
 warehouse_name VARCHAR(120) NOT NULL, owner_name VARCHAR(120) NOT NULL,
 cutoff_on DATE NOT NULL, source_reference VARCHAR(255) NOT NULL,
 opening_token CHAR(36) NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(site_id,warehouse_id,owner_id), UNIQUE KEY opening_source(site_id,source_reference)
) ENGINE=InnoDB;
CREATE TABLE inventory_balance (
 site_id BIGINT NOT NULL, warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 sku_label VARCHAR(255) NOT NULL, catalog_version VARCHAR(64) NOT NULL,
 qualified_units BIGINT NOT NULL DEFAULT 0, pending_units BIGINT NOT NULL DEFAULT 0,
 defective_units BIGINT NOT NULL DEFAULT 0, revision BIGINT NOT NULL DEFAULT 1,
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 PRIMARY KEY(site_id,warehouse_id,owner_id,sku_id),
 FOREIGN KEY(site_id,warehouse_id,owner_id) REFERENCES inventory_scope(site_id,warehouse_id,owner_id),
 CHECK(qualified_units>=0 AND pending_units>=0 AND defective_units>=0)
) ENGINE=InnoDB;
CREATE TABLE inventory_document (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, kind VARCHAR(8) NOT NULL,
 business_date DATE NOT NULL, reason VARCHAR(2000) NOT NULL, line_items JSON NOT NULL,
 effects JSON NULL, status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', revision BIGINT NOT NULL DEFAULT 1,
 source_key CHAR(64) NULL, source_fingerprint CHAR(64) NULL,
 actor_id BIGINT NOT NULL, actor_name VARCHAR(255) NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY document_site(site_id,id), UNIQUE KEY document_source(site_id,source_key),
 KEY document_list(site_id,status,id), CHECK(kind IN ('IN','OUT','MOVE','ADJUST')),
 CHECK(status IN ('DRAFT','POSTED','REVERSED'))
) ENGINE=InnoDB;
CREATE TABLE inventory_loan (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 document_id BIGINT NOT NULL, line_index INT NOT NULL, warehouse_id BIGINT NOT NULL,
 owner_id BIGINT NOT NULL, sku_id BIGINT NOT NULL, borrower VARCHAR(255) NOT NULL,
 purpose VARCHAR(255) NOT NULL, due_on DATE NULL, borrowed_units BIGINT NOT NULL,
 returned_units BIGINT NOT NULL DEFAULT 0, settled_units BIGINT NOT NULL DEFAULT 0,
 revision BIGINT NOT NULL DEFAULT 1, is_active BOOLEAN NOT NULL DEFAULT TRUE,
 UNIQUE KEY loan_site(site_id,id), UNIQUE KEY loan_line(site_id,document_id,line_index),
 FOREIGN KEY(site_id,document_id) REFERENCES inventory_document(site_id,id),
 CHECK(borrowed_units>0 AND returned_units>=0 AND settled_units>=0 AND returned_units+settled_units<=borrowed_units)
) ENGINE=InnoDB;
CREATE TABLE inventory_plan (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 direction VARCHAR(3) NOT NULL, planned_on DATE NULL, units BIGINT NOT NULL,
 completed_units BIGINT NOT NULL DEFAULT 0, cancelled_units BIGINT NOT NULL DEFAULT 0,
 source_reference VARCHAR(255) NOT NULL, loan_id BIGINT NULL, revision BIGINT NOT NULL DEFAULT 1,
 UNIQUE KEY plan_site(site_id,id), UNIQUE KEY plan_loan(site_id,loan_id),
 FOREIGN KEY(site_id,loan_id) REFERENCES inventory_loan(site_id,id),
 CHECK(direction IN ('IN','OUT')), CHECK(units>0 AND completed_units>=0 AND cancelled_units>=0 AND completed_units+cancelled_units<=units)
) ENGINE=InnoDB;
CREATE TABLE inventory_reservation (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 order_line_id BIGINT NOT NULL, units BIGINT NOT NULL, consumed_units BIGINT NOT NULL DEFAULT 0,
 released_units BIGINT NOT NULL DEFAULT 0, revision BIGINT NOT NULL DEFAULT 1,
 reason VARCHAR(2000) NOT NULL,
 UNIQUE KEY reservation_site(site_id,id),
 FOREIGN KEY(site_id,order_line_id) REFERENCES production_order_line(site_id,id),
 CHECK(units>0 AND consumed_units>=0 AND released_units>=0 AND consumed_units+released_units<=units)
) ENGINE=InnoDB;
CREATE TABLE inventory_hold (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 units BIGINT NOT NULL, released_units BIGINT NOT NULL DEFAULT 0,
 revision BIGINT NOT NULL DEFAULT 1, reason VARCHAR(2000) NOT NULL,
 UNIQUE KEY hold_site(site_id,id), CHECK(units>0 AND released_units>=0 AND released_units<=units)
) ENGINE=InnoDB;
CREATE TABLE inventory_event (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 quality VARCHAR(16) NOT NULL, delta_units BIGINT NOT NULL,
 document_kind VARCHAR(16) NOT NULL, document_id BIGINT NOT NULL, revision BIGINT NOT NULL,
 source_line_id BIGINT NULL, operation_token CHAR(36) NOT NULL, actor_id BIGINT NOT NULL,
 actor_name VARCHAR(255) NOT NULL, reason VARCHAR(2000) NOT NULL, business_date DATE NOT NULL,
 location_from VARCHAR(120) NOT NULL DEFAULT '', location_to VARCHAR(120) NOT NULL DEFAULT '',
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY event_balance(site_id,warehouse_id,owner_id,sku_id,id),
 KEY event_document(site_id,document_kind,document_id,revision),
 CHECK(quality IN ('QUALIFIED','PENDING','DEFECTIVE'))
) ENGINE=InnoDB;
CREATE TABLE inventory_shipment_position (
 site_id BIGINT NOT NULL, shipment_id BIGINT NOT NULL, source_line_id BIGINT NOT NULL,
 warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL, sku_id BIGINT NOT NULL, units BIGINT NOT NULL,
 PRIMARY KEY(site_id,shipment_id,source_line_id),
 FOREIGN KEY(site_id,source_line_id) REFERENCES production_shipment_source_line(site_id,id), CHECK(units>=0)
) ENGINE=InnoDB;
ALTER TABLE production_shipment ADD stock_tracked BOOLEAN NOT NULL DEFAULT FALSE,
 ADD warehouse_id BIGINT NULL, ADD owner_id BIGINT NULL;
ALTER TABLE production_revision ADD actor_name VARCHAR(255) NOT NULL DEFAULT '';
