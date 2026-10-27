import logging

from database import db_connection


def auth_init(logger: logging.Logger = None) -> None:
    if logger is None:
        logger = logging.getLogger(__name__)

    with db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                user_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username VARCHAR(64) NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                rights SMALLINT NOT NULL CHECK (rights BETWEEN 1 AND 3),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            COMMENT ON TABLE app_users IS 'People who can log in to the web interface. Not dropped by a reset.';
            COMMENT ON COLUMN app_users.username IS 'Login name, unique.';
            COMMENT ON COLUMN app_users.password_hash IS 'pbkdf2_sha512$iterations$salt$hash. The password itself is never stored.';
            COMMENT ON COLUMN app_users.rights IS '1 = read only, 2 = read and write (settings, imports), 3 = admin (also reset and users).';
            COMMENT ON COLUMN app_users.created_at IS 'When the user was created.';
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_sessions (
                token_hash CHAR(64) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_app_sessions_user_id ON app_sessions(user_id);

            COMMENT ON TABLE app_sessions IS 'Logged-in browsers. Deleting a row logs that browser out.';
            COMMENT ON COLUMN app_sessions.token_hash IS 'SHA-256 of the session cookie, so a copy of this table cannot be used to log in.';
            COMMENT ON COLUMN app_sessions.user_id IS 'Foreign key to app_users; deleting the user deletes their sessions.';
            COMMENT ON COLUMN app_sessions.expires_at IS 'After this time the session is no longer accepted.';
            COMMENT ON COLUMN app_sessions.created_at IS 'When the user logged in.';
        """)

    logger.info("Auth tables initialized")
