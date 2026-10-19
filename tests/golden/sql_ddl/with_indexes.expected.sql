-- SPDX-License-Identifier: MIT OR Apache-2.0
-- DDL for customer_orders
-- Generated from UMF specification
-- Source file modified: 2025-01-01 00:00:00

CREATE TABLE orders (
    order_id INTEGER NOT NULL COMMENT 'Unique order identifier',
    customer_id INTEGER NOT NULL COMMENT 'FK to customers',
    total DECIMAL(12,2) NOT NULL
)
COMMENT 'Customer order records'
;

-- Suggested Indexes
CREATE INDEX idx_orders_customer ON orders (customer_id);
CREATE INDEX idx_orders_total ON orders (customer_id, total);
