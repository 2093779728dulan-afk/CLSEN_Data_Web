CREATE TABLE production_preview (
 id CHAR(36) NOT NULL PRIMARY KEY, site_id BIGINT NOT NULL, actor_id BIGINT NOT NULL,
 document_kind VARCHAR(16) NOT NULL, filename VARCHAR(255) NOT NULL, digest CHAR(64) NOT NULL,
 file_data MEDIUMBLOB NOT NULL, command_value JSON NOT NULL, issues JSON NOT NULL,
 target_id BIGINT NULL, target_revision BIGINT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY preview_scope(site_id,actor_id,id), CHECK(document_kind IN ('orders','shipments'))
) ENGINE=InnoDB;
CREATE TABLE production_source (
 site_id BIGINT NOT NULL, document_kind VARCHAR(16) NOT NULL, digest CHAR(64) NOT NULL,
 document_id BIGINT NULL, PRIMARY KEY(site_id,document_kind,digest),
 CHECK(document_kind IN ('orders','shipments'))
) ENGINE=InnoDB;
