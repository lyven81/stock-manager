CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id VARCHAR(10) PRIMARY KEY,
    supplier_name VARCHAR(100) NOT NULL,
    contact_phone VARCHAR(20),
    email VARCHAR(100),
    lead_time_days INTEGER
);

CREATE TABLE IF NOT EXISTS products (
    product_id VARCHAR(10) PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    unit_price DECIMAL(10,2),
    cost_price DECIMAL(10,2),
    reorder_point INTEGER,
    reorder_quantity INTEGER,
    supplier_id VARCHAR(10) REFERENCES suppliers(supplier_id)
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id VARCHAR(20) PRIMARY KEY,
    product_id VARCHAR(10) REFERENCES products(product_id),
    quantity_sold INTEGER,
    sale_date DATE,
    sale_time TIME
);

CREATE TABLE IF NOT EXISTS inventory (
    product_id VARCHAR(10) PRIMARY KEY REFERENCES products(product_id),
    current_stock INTEGER,
    last_updated DATE
);
