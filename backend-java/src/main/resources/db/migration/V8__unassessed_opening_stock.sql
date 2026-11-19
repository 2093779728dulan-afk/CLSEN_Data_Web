-- Record confirmed physical quantity without inventing ownership or quality facts.
ALTER TABLE inventory_scope ADD opening_metadata JSON NULL;
ALTER TABLE inventory_balance ADD unassessed_units BIGINT NOT NULL DEFAULT 0,
 ADD CONSTRAINT inventory_unassessed_nonnegative CHECK(unassessed_units>=0);
ALTER TABLE inventory_event DROP CHECK inventory_event_chk_1,
 ADD CONSTRAINT inventory_event_quality CHECK(quality IN ('QUALIFIED','PENDING','DEFECTIVE','UNASSESSED'));
