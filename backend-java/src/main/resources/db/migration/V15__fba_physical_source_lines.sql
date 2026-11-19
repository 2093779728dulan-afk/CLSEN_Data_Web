-- Immutable physical-event provenance. The existing site transaction lock
-- serializes active-source checks; reversed facts retain these original rows.
CREATE TABLE fba_action_line (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, site_id BIGINT NOT NULL,
 scope_id BIGINT NOT NULL, action_id BIGINT NOT NULL, sku_id BIGINT NOT NULL,
 kind VARCHAR(16) NOT NULL, source_event_key VARBINARY(1024) NOT NULL,
 customer_order_ref VARCHAR(255) COLLATE utf8mb4_0900_as_cs NOT NULL,
 units BIGINT NOT NULL, quality VARCHAR(16) NOT NULL,
 KEY fba_physical_source(site_id,scope_id,kind,source_event_key,sku_id),
 FOREIGN KEY(site_id,scope_id) REFERENCES fba_scope(site_id,id),
 FOREIGN KEY(site_id,action_id) REFERENCES fba_action(site_id,id),
 CHECK(kind IN ('FULFILLMENT','RETURN')), CHECK(units>0)
) ENGINE=InnoDB;
