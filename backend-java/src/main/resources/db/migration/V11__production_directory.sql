ALTER TABLE production_factory
 ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
 ADD COLUMN revision BIGINT NOT NULL DEFAULT 1,
 ADD COLUMN profile JSON NULL;

CREATE TABLE production_warehouse (
 site_id BIGINT NOT NULL,
 id BIGINT NOT NULL AUTO_INCREMENT,
 name VARCHAR(120) COLLATE utf8mb4_0900_as_cs NOT NULL,
 type VARCHAR(24) NOT NULL,
 country VARCHAR(80) NOT NULL DEFAULT '',
 status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
 revision BIGINT NOT NULL DEFAULT 1,
 profile JSON NULL,
 PRIMARY KEY(site_id,id), KEY warehouse_sequence(id),
 KEY warehouse_name(site_id,name),
 CHECK(type IN ('FACTORY','OWN','THIRD_PARTY','FBA','LOCATION','UNCLASSIFIED')),
 CHECK(status IN ('ACTIVE','INACTIVE'))
) ENGINE=InnoDB;

-- Preserve existing scoped IDs and balances. No names are guessed across scopes.
INSERT INTO production_warehouse(site_id,id,name,type)
 SELECT site_id,warehouse_id,
 CASE WHEN COUNT(DISTINCT warehouse_name)=1 THEN MAX(warehouse_name)
 ELSE CONCAT('历史仓库 ',warehouse_id,'（名称待核）') END,'UNCLASSIFIED'
 FROM inventory_scope GROUP BY site_id,warehouse_id;

CREATE TABLE production_factory_warehouse (
 site_id BIGINT NOT NULL, factory_id BIGINT NOT NULL, warehouse_id BIGINT NOT NULL,
 PRIMARY KEY(site_id,factory_id,warehouse_id),
 FOREIGN KEY(site_id,factory_id) REFERENCES production_factory(site_id,id),
 FOREIGN KEY(site_id,warehouse_id) REFERENCES production_warehouse(site_id,id)
) ENGINE=InnoDB;

CREATE TABLE production_directory_revision (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 site_id BIGINT NOT NULL, entity_kind VARCHAR(16) NOT NULL, entity_id BIGINT NOT NULL,
 revision BIGINT NOT NULL, actor_id BIGINT NOT NULL, actor_name VARCHAR(255) NOT NULL,
 reason VARCHAR(2000) NOT NULL, before_value JSON NULL, after_value JSON NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY directory_version(site_id,entity_kind,entity_id,revision)
) ENGINE=InnoDB;

ALTER TABLE production_order
 ADD COLUMN destination_type VARCHAR(16) NULL,
 ADD COLUMN destination_id BIGINT NULL;
ALTER TABLE production_shipment
 ADD COLUMN destination_type VARCHAR(16) NULL,
 ADD COLUMN destination_id BIGINT NULL;
