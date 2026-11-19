-- Explicit new facts only: historic factories and production totals remain unknown.
CREATE TABLE production_factory (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 site_id BIGINT NOT NULL, name VARCHAR(120) COLLATE utf8mb4_0900_as_cs NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY factory_site(site_id,id), UNIQUE KEY factory_name(site_id,name)
) ENGINE=InnoDB;
ALTER TABLE production_order
 ADD COLUMN factory_id BIGINT NULL,
 ADD COLUMN receipt_warehouse_id BIGINT NULL,
 ADD COLUMN receipt_owner_id BIGINT NULL,
 ADD COLUMN destination VARCHAR(255) NOT NULL DEFAULT '',
 ADD KEY order_factory(site_id,factory_id,business_date,id),
 ADD FOREIGN KEY(site_id,factory_id) REFERENCES production_factory(site_id,id);
ALTER TABLE production_order_line
 ADD COLUMN produced_units BIGINT NULL,
 ADD CONSTRAINT production_nonnegative CHECK(produced_units IS NULL OR produced_units>=0);
ALTER TABLE production_shipment
 ADD COLUMN destination VARCHAR(255) NOT NULL DEFAULT '',
 ADD COLUMN cartons JSON NULL;
