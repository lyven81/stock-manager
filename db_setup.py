"""Database setup: create tables and load CSV data into AlloyDB."""

import os
import csv
from dotenv import load_dotenv
from google.cloud.alloydb.connector import Connector
import sqlalchemy
from sqlalchemy import text

load_dotenv()

ALLOYDB_INSTANCE_URI = os.environ["ALLOYDB_INSTANCE_URI"]
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_NAME = os.environ["DB_NAME"]


def get_engine():
    connector = Connector()

    def getconn():
        return connector.connect(
            ALLOYDB_INSTANCE_URI,
            "pg8000",
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
        )

    engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn)
    return engine


def create_tables(engine):
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()
    with engine.connect() as conn:
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
        conn.commit()
    print("Tables created.")


def load_csv(engine, table_name, csv_path, columns):
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"No data in {csv_path}")
        return

    placeholders = ", ".join([f":{col}" for col in columns])
    col_names = ", ".join(columns)
    insert_sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    with engine.connect() as conn:
        for row in rows:
            params = {col: row[col] for col in columns}
            conn.execute(text(insert_sql), params)
        conn.commit()
    print(f"Loaded {len(rows)} rows into {table_name}.")


def main():
    engine = get_engine()
    create_tables(engine)

    dataset_dir = os.path.join(os.path.dirname(__file__), "..", "dataset")

    load_csv(engine, "suppliers", os.path.join(dataset_dir, "suppliers.csv"),
             ["supplier_id", "supplier_name", "contact_phone", "email", "lead_time_days"])

    load_csv(engine, "products", os.path.join(dataset_dir, "products.csv"),
             ["product_id", "product_name", "category", "unit_price", "cost_price",
              "reorder_point", "reorder_quantity", "supplier_id"])

    load_csv(engine, "sales", os.path.join(dataset_dir, "sales.csv"),
             ["sale_id", "product_id", "quantity_sold", "sale_date", "sale_time"])

    load_csv(engine, "inventory", os.path.join(dataset_dir, "inventory.csv"),
             ["product_id", "current_stock", "last_updated"])

    print("Database setup complete.")


if __name__ == "__main__":
    main()
