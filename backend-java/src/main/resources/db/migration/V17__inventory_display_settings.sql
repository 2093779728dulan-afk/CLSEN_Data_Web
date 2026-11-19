CREATE TABLE inventory_display_settings (
    site_id BIGINT NOT NULL PRIMARY KEY,
    style_ids JSON NOT NULL,
    revision BIGINT NOT NULL,
    actor_id BIGINT NOT NULL,
    actor_name VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
);
