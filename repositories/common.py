"""helpers shared by the repositories."""

from database import db_connection


def fetch_all(sql: str, params: tuple) -> list[dict]:
    # runs a select and turns each row into a dict keyed by column name
    with db_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]
