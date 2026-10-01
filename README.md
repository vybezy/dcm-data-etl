## Python ETL Pipeline & PostgreSQL Backend
    This is a backend data engineering project I built to process, clean, and load large datasets into a PostgreSQL database quickly and safely.

# What it does
    ETL Pipeline: Handles extracting messy files, cleaning the data, and inserting it into the database.

    Database Design: Uses PostgreSQL schemas, including JSONB fields and GIN / B-Tree indexes so queries run efficiently.

    Multiprocessing: Uses ProcessPoolExecutor to parse large files in parallel instead of processing them one by one.

    Safety & Logging: Includes SHA-256 file hashing to make sure data isn't corrupted, along with custom error handling.

# Tech Stack
    Python (Multiprocessing, file handling, custom data structures)

    PostgreSQL (Relational schema design, JSONB, indexing)