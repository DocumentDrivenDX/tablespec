-- SPDX-License-Identifier: MIT OR Apache-2.0
-- DDL for all_types_table
-- Generated from UMF specification
-- Source file modified: 2025-01-01 00:00:00

CREATE TABLE all_types_table (
    id INTEGER NOT NULL,
    amount DECIMAL(10,2),
    rate FLOAT,
    created_date DATE,
    updated_at DATETIME NOT NULL,
    is_active BOOLEAN,
    notes TEXT,
    code STRING
)
COMMENT 'A table with all supported types'
;
