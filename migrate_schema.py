"""Idempotent schema migration: add vector embeddings to products.

Runs on container startup. Safe to call repeatedly.

Adds:
  - vector extension (pgvector)
  - products.sales_pattern_embedding vector(6) column
  - Populates embeddings from sales data: 6-week normalized weekly velocity vector
"""

import os
import sys
from dotenv import load_dotenv
import sqlalchemy
from sqlalchemy import text

load_dotenv()

EMBEDDING_DIM = 6  # 6 weekly velocity values per product


def get_engine():
    db_host = os.environ["DB_HOST"]
    db_user = os.environ["DB_USER"]
    db_pass = os.environ["DB_PASS"]
    db_name = os.environ["DB_NAME"]
    return sqlalchemy.create_engine(
        f"postgresql+pg8000://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
    )


def ensure_extension(conn):
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    print("[migrate] vector extension ready")


def ensure_column(conn):
    result = conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'products' AND column_name = 'sales_pattern_embedding'
    """)).fetchone()
    if result:
        print("[migrate] sales_pattern_embedding column already exists")
        return
    conn.execute(text(f"""
        ALTER TABLE products
        ADD COLUMN sales_pattern_embedding vector({EMBEDDING_DIM})
    """))
    print(f"[migrate] added sales_pattern_embedding vector({EMBEDDING_DIM}) column")


def compute_embeddings(conn):
    """Compute a 6-week normalized velocity vector per product.

    Each dimension = total units sold in week N (counting backwards from latest sale date).
    Normalized per-product to unit length, so similarity captures SHAPE not VOLUME.
    """
    products = conn.execute(text("SELECT product_id FROM products")).fetchall()

    for (product_id,) in products:
        rows = conn.execute(text(f"""
            WITH latest AS (SELECT MAX(sale_date) AS d FROM sales),
            weeks AS (
                SELECT generate_series(0, {EMBEDDING_DIM - 1}) AS week_idx
            )
            SELECT
                w.week_idx,
                COALESCE(SUM(s.quantity_sold), 0) AS week_total
            FROM weeks w
            CROSS JOIN latest
            LEFT JOIN sales s
              ON s.product_id = :pid
              AND s.sale_date > latest.d - ((w.week_idx + 1) * INTERVAL '7 days')
              AND s.sale_date <= latest.d - (w.week_idx * INTERVAL '7 days')
            GROUP BY w.week_idx
            ORDER BY w.week_idx
        """), {"pid": product_id}).fetchall()

        # Most recent week first → reverse to chronological for readability
        weekly = [float(r[1]) for r in rows]
        weekly.reverse()  # oldest week first, newest last

        # Normalize to unit length for cosine similarity (shape-based)
        magnitude = sum(v * v for v in weekly) ** 0.5
        if magnitude == 0:
            normalized = [0.0] * EMBEDDING_DIM
        else:
            normalized = [v / magnitude for v in weekly]

        vector_literal = "[" + ",".join(f"{v:.6f}" for v in normalized) + "]"
        conn.execute(
            text("UPDATE products SET sales_pattern_embedding = :vec WHERE product_id = :pid"),
            {"vec": vector_literal, "pid": product_id},
        )

    print(f"[migrate] populated embeddings for {len(products)} products")


def run_migration():
    print("[migrate] starting schema migration...")
    engine = get_engine()
    with engine.connect() as conn:
        ensure_extension(conn)
        conn.commit()
        ensure_column(conn)
        conn.commit()
        compute_embeddings(conn)
        conn.commit()
    print("[migrate] migration complete")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"[migrate] FAILED: {e}", file=sys.stderr)
        sys.exit(1)
