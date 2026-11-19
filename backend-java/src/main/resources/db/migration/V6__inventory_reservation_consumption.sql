-- Preserve which reservation was consumed by each shipment, for quantity correction.
CREATE TABLE inventory_shipment_reservation (
 site_id BIGINT NOT NULL, shipment_id BIGINT NOT NULL, reservation_id BIGINT NOT NULL,
 consumed_units BIGINT NOT NULL,
 PRIMARY KEY(site_id,shipment_id,reservation_id),
 FOREIGN KEY(site_id,shipment_id) REFERENCES production_shipment(site_id,id),
 FOREIGN KEY(site_id,reservation_id) REFERENCES inventory_reservation(site_id,id),
 CHECK(consumed_units>=0)
) ENGINE=InnoDB;
