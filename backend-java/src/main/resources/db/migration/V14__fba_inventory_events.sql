-- FBA is an explicitly enabled logical account/marketplace/owner scope.
-- Ordinary warehouse entry points remain forbidden for FBA.
CREATE TABLE fba_scope (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 warehouse_id BIGINT NOT NULL, owner_id BIGINT NOT NULL,
 seller_account VARCHAR(255) COLLATE utf8mb4_0900_as_cs NOT NULL,
 marketplace VARCHAR(32) COLLATE utf8mb4_0900_as_cs NOT NULL,
 report_source_scope_id BIGINT NOT NULL, store_evidence VARCHAR(255) NOT NULL,
 catalog_version VARCHAR(64) NOT NULL, cutoff_on DATE NOT NULL,
 opening_basis VARCHAR(2000) NOT NULL, simulated BOOLEAN NOT NULL,
 revision BIGINT NOT NULL DEFAULT 1,
 UNIQUE KEY fba_scope_site(site_id,id),
 UNIQUE KEY fba_warehouse_owner(site_id,warehouse_id,owner_id),
 UNIQUE KEY fba_account_scope(site_id,seller_account,marketplace,owner_id),
 FOREIGN KEY(site_id,warehouse_id,owner_id) REFERENCES inventory_scope(site_id,warehouse_id,owner_id)
) ENGINE=InnoDB;
CREATE TABLE fba_identity (
 site_id BIGINT NOT NULL, scope_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 seller_sku VARBINARY(1024) NOT NULL, seller_sku_raw VARCHAR(255) NOT NULL, fnsku VARBINARY(1024) NOT NULL, asin VARBINARY(1024) NOT NULL,
 style_id BIGINT NOT NULL, catalog_version VARCHAR(64) NOT NULL,
 evidence VARCHAR(2000) NOT NULL, tracked BOOLEAN NOT NULL DEFAULT FALSE,
 PRIMARY KEY(site_id,scope_id,sku_id), UNIQUE KEY fba_msku(site_id,scope_id,seller_sku),
 FOREIGN KEY(site_id,scope_id) REFERENCES fba_scope(site_id,id)
) ENGINE=InnoDB;
CREATE TABLE fba_reference (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL, scope_id BIGINT NOT NULL,
 reference_key VARBINARY(1024) NOT NULL, shipment_id BIGINT NOT NULL, shipment_revision BIGINT NOT NULL,
 evidence VARCHAR(2000) NOT NULL,
 UNIQUE KEY fba_reference_site(site_id,id), UNIQUE KEY fba_reference_key(site_id,scope_id,reference_key),
 FOREIGN KEY(site_id,scope_id) REFERENCES fba_scope(site_id,id),
 FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id)
) ENGINE=InnoDB;
CREATE TABLE fba_receipt_batch (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL, scope_id BIGINT NOT NULL,
 filename VARCHAR(255) NOT NULL, digest CHAR(64) NOT NULL, original_data MEDIUMBLOB NOT NULL,
 source_rows JSON NOT NULL, source_issues JSON NOT NULL, decisions JSON NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', revision BIGINT NOT NULL DEFAULT 1,
 actor_id BIGINT NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY fba_batch_site(site_id,id), UNIQUE KEY fba_exact_file(site_id,scope_id,digest),
 FOREIGN KEY(site_id,scope_id) REFERENCES fba_scope(site_id,id),
 CHECK(status IN ('DRAFT','PARTIAL','POSTED','ABANDONED'))
) ENGINE=InnoDB;
CREATE TABLE fba_receipt_event (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL, scope_id BIGINT NOT NULL,
 batch_id BIGINT NOT NULL, source_row INT NOT NULL, sku_id BIGINT NOT NULL,
 event_key VARBINARY(1024) NOT NULL, fingerprint CHAR(64) NOT NULL,
 reference_id BIGINT NOT NULL, units BIGINT NOT NULL, occurred_at TIMESTAMP(6) NOT NULL,
 occurred_local VARCHAR(64) NOT NULL, business_date DATE NOT NULL, fulfillment_center VARCHAR(255) NOT NULL,
 catalog_version VARCHAR(64) NOT NULL, correction_of BIGINT NULL, evidence VARCHAR(2000) NOT NULL,
 actor_id BIGINT NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY fba_event_site(site_id,id), UNIQUE KEY fba_occurrence_key(site_id,scope_id,event_key),
 UNIQUE KEY fba_source_once(site_id,batch_id,source_row),
 KEY fba_similarity(site_id,scope_id,fingerprint),
 FOREIGN KEY(site_id,scope_id) REFERENCES fba_scope(site_id,id),
 FOREIGN KEY(site_id,batch_id) REFERENCES fba_receipt_batch(site_id,id),
 FOREIGN KEY(site_id,reference_id) REFERENCES fba_reference(site_id,id),
 FOREIGN KEY(site_id,correction_of) REFERENCES fba_receipt_event(site_id,id),
 CHECK(units<>0)
) ENGINE=InnoDB;
CREATE TABLE fba_event_allocation (
 site_id BIGINT NOT NULL, event_id BIGINT NOT NULL, binding_id BIGINT NOT NULL, units BIGINT NOT NULL,
 PRIMARY KEY(site_id,event_id,binding_id),
 FOREIGN KEY(site_id,event_id) REFERENCES fba_receipt_event(site_id,id),
 FOREIGN KEY(site_id,binding_id) REFERENCES destination_shipment_binding(site_id,id),
 CHECK(units<>0)
) ENGINE=InnoDB;
-- Duplicate decisions retain exact source-row coverage without a second stock event.
CREATE TABLE fba_receipt_resolution (
 site_id BIGINT NOT NULL, batch_id BIGINT NOT NULL, source_row INT NOT NULL,
 event_id BIGINT NOT NULL, decision VARCHAR(16) NOT NULL, evidence VARCHAR(2000) NOT NULL,
 PRIMARY KEY(site_id,batch_id,source_row),
 FOREIGN KEY(site_id,batch_id) REFERENCES fba_receipt_batch(site_id,id),
 FOREIGN KEY(site_id,event_id) REFERENCES fba_receipt_event(site_id,id),
 CHECK(decision IN ('NEW','SAME'))
) ENGINE=InnoDB;
CREATE TABLE fba_action (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL, scope_id BIGINT NOT NULL,
 kind VARCHAR(16) NOT NULL, event_key VARBINARY(1024) NOT NULL, occurred_at TIMESTAMP(6) NOT NULL,
 business_date DATE NOT NULL, payload JSON NOT NULL, effects JSON NOT NULL,
 related_action_id BIGINT NULL, status VARCHAR(16) NOT NULL DEFAULT 'POSTED', revision BIGINT NOT NULL DEFAULT 1,
 actor_id BIGINT NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY fba_action_site(site_id,id), UNIQUE KEY fba_action_identity(site_id,scope_id,kind,event_key),
 FOREIGN KEY(site_id,scope_id) REFERENCES fba_scope(site_id,id),
 FOREIGN KEY(site_id,related_action_id) REFERENCES fba_action(site_id,id),
 CHECK(kind IN ('FULFILLMENT','RETURN','OBSERVATION')), CHECK(status IN ('POSTED','REVERSED'))
) ENGINE=InnoDB;
