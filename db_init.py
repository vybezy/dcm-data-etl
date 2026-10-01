import logging
from THKE_config import config
import psycopg2

def db_init(reset_tables: bool = False, logger: logging.Logger = None):

    params = config()
    conn = psycopg2.connect(**params)
    
    if logger is None:
        logger = logging.getLogger(__name__)

    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS c3d_files_MM CASCADE;")
    
    if reset_tables:
        logger.info("Resetting database tables...")
        cur.execute("DROP TABLE IF EXISTS c3d_logger_MM CASCADE;")
        cur.execute("DROP TABLE IF EXISTS c3d_logger_session_MM CASCADE;")
        cur.execute("DROP TABLE IF EXISTS c3d_settings_MM CASCADE;")
        cur.execute("DROP TABLE IF EXISTS c3d_header_MM CASCADE;")
        cur.execute("DROP TABLE IF EXISTS c3d_parameters_MM CASCADE;")
        cur.execute("DROP TABLE IF EXISTS c3d_analog_MM CASCADE;")
        cur.execute("DROP TABLE IF EXISTS c3d_points_MM CASCADE;")
        cur.execute("DROP TABLE IF EXISTS c3d_files_MM CASCADE;")

    
    # Logger Session
   
    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_logger_session_MM (
            logses_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            logses_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            logses_userid TEXT DEFAULT current_user,
            logses_machineid TEXT
        );
        
        COMMENT ON COLUMN c3d_logger_session_MM.logses_id IS 'Primary key for the logging session batch.';
        COMMENT ON COLUMN c3d_logger_session_MM.logses_timestamp IS 'Exact UTC timestamp when the batch import initiated.';
        COMMENT ON COLUMN c3d_logger_session_MM.logses_userid IS 'Database user who initiated the import session.';
        COMMENT ON COLUMN c3d_logger_session_MM.logses_machineid IS 'Network identity/hostname of the machine running the import script.';
    """)

    
    # Logger
  
    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_logger_MM (
            log_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            log_logses_id INTEGER NOT NULL REFERENCES c3d_logger_session_MM(logses_id) ON DELETE CASCADE,
            log_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            log_level VARCHAR(10) NOT NULL,
            log_c3dfile VARCHAR(100) NOT NULL, 
            log_message TEXT NOT NULL,
            log_module VARCHAR(100) NOT NULL,
            log_function VARCHAR(100) NOT NULL,
            log_line_number INTEGER NOT NULL,
            log_process_name VARCHAR(100) NOT NULL,
            log_thread_name VARCHAR(100) NOT NULL,
            log_exception_type VARCHAR(200),
            log_stack_trace TEXT
        );
        
        COMMENT ON COLUMN c3d_logger_MM.log_id IS 'Primary key for the individual log event.';
        COMMENT ON COLUMN c3d_logger_MM.log_logses_id IS 'Foreign key tying this log to a specific import batch session.';
        COMMENT ON COLUMN c3d_logger_MM.log_timestamp IS 'Exact timestamp of the logged event.';
        COMMENT ON COLUMN c3d_logger_MM.log_level IS 'Severity level (e.g., INFO, ERROR, CRITICAL).';
        COMMENT ON COLUMN c3d_logger_MM.log_c3dfile IS 'The specific C3D file being processed during the event.';
        COMMENT ON COLUMN c3d_logger_MM.log_message IS 'Descriptive logging message or error summary.';
        COMMENT ON COLUMN c3d_logger_MM.log_module IS 'Python module where the event was triggered.';
        COMMENT ON COLUMN c3d_logger_MM.log_function IS 'Python function where the event was triggered.';
        COMMENT ON COLUMN c3d_logger_MM.log_line_number IS 'Code line number for debugging.';
        COMMENT ON COLUMN c3d_logger_MM.log_process_name IS 'Multiprocessing worker name.';
        COMMENT ON COLUMN c3d_logger_MM.log_thread_name IS 'Thread name executing the process.';
        COMMENT ON COLUMN c3d_logger_MM.log_exception_type IS 'Type of Python exception caught, if any.';
        COMMENT ON COLUMN c3d_logger_MM.log_stack_trace IS 'Full traceback for post-mortem debugging.';
    """)

    
    # Settings

    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_settings_MM (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        
        COMMENT ON COLUMN c3d_settings_MM.key IS 'Configuration parameter name (e.g., max_file_size).';
        COMMENT ON COLUMN c3d_settings_MM.value IS 'Configuration parameter value stored as text for flexible casting.';
    """)


    # Files

    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_files_MM ( 
            file_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            file_name VARCHAR(255) NOT NULL,
            file_path TEXT NOT NULL,
            file_date TIMESTAMP WITH TIME ZONE NOT NULL,
            file_size BIGINT NOT NULL,
            file_sha256_hash VARCHAR(64) UNIQUE NOT NULL,
            file_subject_name VARCHAR(255) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        
        COMMENT ON COLUMN c3d_files_MM.file_id IS 'Master Primary Key for the imported C3D file. All metadata tables link back to this ID.';
        COMMENT ON COLUMN c3d_files_MM.file_name IS 'Original file name of the C3D file.';
        COMMENT ON COLUMN c3d_files_MM.file_path IS 'Absolute filesystem path of the source file.';
        COMMENT ON COLUMN c3d_files_MM.file_date IS 'Last modified timestamp of the source file.';
        COMMENT ON COLUMN c3d_files_MM.file_size IS 'File size in bytes.';
        COMMENT ON COLUMN c3d_files_MM.file_sha256_hash IS 'Cryptographic hash to guarantee uniqueness and prevent duplicate file ingestion.';
        COMMENT ON COLUMN c3d_files_MM.file_subject_name IS 'Extracted test subject identifier for downstream grouping.';
        COMMENT ON COLUMN c3d_files_MM.created_at IS 'Timestamp of when the file was ingested into the database.';
    """)

    
    # Header
   
    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_header_MM (
            header_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            header_file_id INTEGER NOT NULL,
            header_name TEXT NOT NULL,
            header_key TEXT NOT NULL,
            header_value TEXT NOT NULL,
            
            UNIQUE(header_file_id, header_name),
            
            CONSTRAINT fk_c3d_headers_file_id FOREIGN KEY(header_file_id)
                REFERENCES c3d_files_MM(file_id) ON DELETE CASCADE
        );
                
        CREATE INDEX IF NOT EXISTS idx_headers_file ON c3d_header_MM(header_file_id);
                
        COMMENT ON COLUMN c3d_header_MM.header_id IS 'Surrogate primary key for the header record.';
        COMMENT ON COLUMN c3d_header_MM.header_file_id IS 'Foreign key linking to the master C3D file.';
        COMMENT ON COLUMN c3d_header_MM.header_name IS 'Composite identifier combining section and key to prevent namespace collisions (e.g., POINT_RATE).';
        COMMENT ON COLUMN c3d_header_MM.header_key IS 'The parent section of the header telemetry (e.g., POINT or ANALOG).';
        COMMENT ON COLUMN c3d_header_MM.header_value IS 'The stringified value of the header telemetry.';
    """)    


    # Analog
   
    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_analog_MM (
            analog_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            analog_file_id INTEGER NOT NULL,
            analog_label TEXT,      
            analog_unit TEXT,       
            analog_gain TEXT,       
            analog_frames FLOAT8[] NOT NULL,
            analog_offset INT,
            analog_desc TEXT,       
            
            CONSTRAINT uniq_c3d_analog_MM_file_label 
                UNIQUE (analog_file_id, analog_label),
            CONSTRAINT fk_c3d_analog_MM_file 
                FOREIGN KEY (analog_file_id) 
                REFERENCES c3d_files_MM(file_id)
                ON DELETE CASCADE
        );
        
        COMMENT ON COLUMN c3d_analog_MM.analog_id IS 'Surrogate primary key for the specific analog channel record.';
        COMMENT ON COLUMN c3d_analog_MM.analog_file_id IS 'Foreign key linking this analog hardware data back to the master C3D file record.';
        COMMENT ON COLUMN c3d_analog_MM.analog_label IS 'The hardware identifier of the analog channel (e.g., Force_Z, EMG_Biceps). Forms a unique composite key with file_id to prevent duplicate channel ingestion.';
        COMMENT ON COLUMN c3d_analog_MM.analog_unit IS 'The engineering unit of measurement (e.g., V, N, mV). Critical for downstream physical calculations and ensuring force/voltage conversions are accurate.';
        COMMENT ON COLUMN c3d_analog_MM.analog_gain IS 'The hardware amplifier gain setting applied during data collection. Used to reverse-calculate raw voltages if the data was pre-scaled by the capture system.';
        COMMENT ON COLUMN c3d_analog_MM.analog_frames IS 'Sequential time-series array of the actual high-frequency analog measurements across all frames. Stored as a FLOAT8 array for maximum scientific precision.';
        COMMENT ON COLUMN c3d_analog_MM.analog_offset IS 'Baseline zero-offset (tare) value for the analog channel. Essential for calibrating the raw signal (e.g., removing the weight of an empty force plate) before analysis.';
        COMMENT ON COLUMN c3d_analog_MM.analog_desc IS 'Human-readable description of the analog channel configuration natively extracted from the C3D parameters.';

        ALTER TABLE c3d_analog_MM ALTER COLUMN analog_frames SET STORAGE EXTERNAL;
        
        CREATE INDEX IF NOT EXISTS idx_c3d_analog_MM_file_id 
            ON c3d_analog_MM (analog_file_id);
            
        CREATE INDEX IF NOT EXISTS idx_c3d_analog_MM_frames_gin 
            ON c3d_analog_MM USING GIN (analog_frames);

        COMMENT ON INDEX idx_c3d_analog_MM_file_id IS 'B-Tree Index: Optimizes foreign key cascading deletes and allows ultra-fast extraction of all analog hardware channels belonging to a single C3D file.';
        COMMENT ON INDEX idx_c3d_analog_MM_frames_gin IS 'GIN (Generalized Inverted Index): Enables fast membership queries without unpacking the entire array. Extremely useful for identifying signal clipping/peaking (e.g., rapidly finding files where an EMG sensor hit its maximum voltage).';
    """)

    
    # Parameters
   
    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_parameters_MM (
            parameters_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            parameters_file_id INTEGER NOT NULL,
            parameters_group TEXT,
            parameters_key TEXT,           
            parameters_description TEXT,  
            parameters_dimensions TEXT,
            parameters_lock BOOL,
            parameters_value_json JSONB,
            
            CONSTRAINT uniq_c3d_params_file_group_key 
                UNIQUE (parameters_file_id, parameters_group, parameters_key),
            CONSTRAINT fk_c3d_parameters_MM_file 
                FOREIGN KEY (parameters_file_id) 
                REFERENCES c3d_files_MM(file_id) 
                ON DELETE CASCADE
        );

        COMMENT ON COLUMN c3d_parameters_MM.parameters_id IS 'Surrogate primary key for the specific parameter record.';
        COMMENT ON COLUMN c3d_parameters_MM.parameters_file_id IS 'Foreign key linking this parameter back to the master C3D file record.';
        COMMENT ON COLUMN c3d_parameters_MM.parameters_group IS 'The high-level C3D parameter group folder (e.g., POINT, ANALOG, SUBJECTS). Acts as the primary namespace.';
        COMMENT ON COLUMN c3d_parameters_MM.parameters_key IS 'The specific parameter setting name (e.g., RATE, USED, LABELS). Forms a unique identifier alongside the file_id and group.';
        COMMENT ON COLUMN c3d_parameters_MM.parameters_description IS 'The embedded text description natively extracted from the C3D file, providing human-readable context for obscure parameter keys.';
        COMMENT ON COLUMN c3d_parameters_MM.parameters_dimensions IS 'The stringified matrix shape of the original data. Used programmatically to identify multi-dimensional array structures before unpacking the JSON payload.';
        COMMENT ON COLUMN c3d_parameters_MM.parameters_lock IS 'Stores the lock status (is_locked).';
        COMMENT ON COLUMN c3d_parameters_MM.parameters_value_json IS 'The core payload stored as binary JSON (JSONB). Crucial for handling polymorphic C3D data types (integers, floats, deep matrices, strings) within a single database column without breaking relational schema rules.';
                  
        CREATE INDEX IF NOT EXISTS idx_c3d_parameters_MM_file_id 
            ON c3d_parameters_MM (parameters_file_id);
        CREATE INDEX IF NOT EXISTS idx_c3d_parameters_MM_group_key 
            ON c3d_parameters_MM (parameters_file_id, parameters_group, parameters_key);
            
        CREATE INDEX IF NOT EXISTS idx_c3d_parameters_MM_value_json 
            ON c3d_parameters_MM USING GIN (parameters_value_json);

        COMMENT ON INDEX idx_c3d_parameters_MM_file_id IS 'B-Tree Index: Optimizes cascading deletes and master-detail joins when extracting all parameters for a specific file.';
        COMMENT ON INDEX idx_c3d_parameters_MM_group_key IS 'Composite B-Tree Index: Highly optimized for point-queries. Allows instant data retrieval when the application asks for a specific setting.';
        COMMENT ON INDEX idx_c3d_parameters_MM_value_json IS 'GIN (Generalized Inverted Index): The search engine for the JSONB payload. Allows ultra-fast, document-style queries to look inside nested parameter arrays.';
    """)

    
    # Points
  
    cur.execute("""
        CREATE TABLE IF NOT EXISTS c3d_points_MM (
            points_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            points_file_id INTEGER NOT NULL,
            points_frame_count INTEGER NOT NULL, 
            points_label TEXT NOT NULL, 
            points_frames_x FLOAT8[] NOT NULL,
            points_frames_y FLOAT8[] NOT NULL,
            points_frames_z FLOAT8[] NOT NULL,
            points_frames_r FLOAT8[] NOT NULL,   
            
            CONSTRAINT uniq_points_file_label 
                UNIQUE (points_file_id, points_label),
            CONSTRAINT fk_points_file
                FOREIGN KEY (points_file_id)
                REFERENCES c3d_files_MM(file_id) 
                ON DELETE CASCADE,
            CONSTRAINT chk_c3d_points_valid_lengths CHECK (
                array_length(points_frames_x, 1) = points_frame_count AND
                array_length(points_frames_y, 1) = points_frame_count AND
                array_length(points_frames_z, 1) = points_frame_count AND
                array_length(points_frames_r, 1) = points_frame_count 
            )
        );
                
        COMMENT ON COLUMN c3d_points_MM.points_id IS 'Surrogate primary key for the specific point trajectory record.';
        COMMENT ON COLUMN c3d_points_MM.points_file_id IS 'Foreign key linking this trajectory data back to the master C3D file record.';
        COMMENT ON COLUMN c3d_points_MM.points_frame_count IS 'Total number of recorded frames for this specific marker. Used programmatically to validate data completeness via the array length CHECK constraint.';
        COMMENT ON COLUMN c3d_points_MM.points_label IS 'The physical name/identifier of the tracking marker (e.g., L_KNEE, R_HEEL). Forms a unique composite key with the file_id to prevent duplicate markers per file.';
        COMMENT ON COLUMN c3d_points_MM.points_frames_x IS 'Sequential time-series array of X-axis spatial coordinates across all frames. Stored as FLOAT8 array for precision 3D reconstruction.';
        COMMENT ON COLUMN c3d_points_MM.points_frames_y IS 'Sequential time-series array of Y-axis spatial coordinates across all frames.';
        COMMENT ON COLUMN c3d_points_MM.points_frames_z IS 'Sequential time-series array of Z-axis spatial coordinates across all frames.';
        COMMENT ON COLUMN c3d_points_MM.points_frames_r IS 'Sequential array of Residual (error) values or camera contribution flags per frame. Crucial for evaluating the reliability and physical validity of the 3D coordinate at any given frame.';

        ALTER TABLE c3d_points_MM ALTER COLUMN points_frames_x SET STORAGE EXTERNAL;
        ALTER TABLE c3d_points_MM ALTER COLUMN points_frames_y SET STORAGE EXTERNAL;
        ALTER TABLE c3d_points_MM ALTER COLUMN points_frames_z SET STORAGE EXTERNAL;
        ALTER TABLE c3d_points_MM ALTER COLUMN points_frames_r SET STORAGE EXTERNAL;

        CREATE INDEX IF NOT EXISTS idx_c3d_points_MM_file_id 
            ON c3d_points_MM(points_file_id);
            
        CREATE INDEX IF NOT EXISTS idx_c3d_points_MM_x_gin 
            ON c3d_points_MM USING GIN (points_frames_x);
        CREATE INDEX IF NOT EXISTS idx_c3d_points_MM_y_gin 
            ON c3d_points_MM USING GIN (points_frames_y);
        CREATE INDEX IF NOT EXISTS idx_c3d_points_MM_z_gin 
            ON c3d_points_MM USING GIN (points_frames_z);
        CREATE INDEX IF NOT EXISTS idx_c3d_points_MM_r_gin 
            ON c3d_points_MM USING GIN (points_frames_r);

        COMMENT ON INDEX idx_c3d_points_MM_file_id IS 'B-Tree Index: Optimizes foreign key joins and allows ultra-fast extraction of all point trajectories belonging to a single C3D file for 3D plotting.';
        COMMENT ON INDEX idx_c3d_points_MM_x_gin IS 'GIN (Generalized Inverted Index): Enables rapid array-intersection queries (e.g., finding if a specific coordinate anomaly exists) without unpacking the entire FLOAT8 array into memory.';
        COMMENT ON INDEX idx_c3d_points_MM_y_gin IS 'GIN (Generalized Inverted Index): Accelerates deep array element lookups for Y-axis anomalies.';
        COMMENT ON INDEX idx_c3d_points_MM_z_gin IS 'GIN (Generalized Inverted Index): Accelerates deep array element lookups for Z-axis anomalies.';
        COMMENT ON INDEX idx_c3d_points_MM_r_gin IS 'GIN (Generalized Inverted Index): Highly analytical index. Allows fast querying to find exactly which trajectories contain unacceptably high residual/error values.';
    """)

    # Default settings (only if resetting)
    if reset_tables:
        cur.execute("""
            INSERT INTO c3d_settings_MM (key, value) VALUES 
            ('min_file_size', '307200'),
            ('max_file_size', '103809024'),
            ('subject_min_length', '3'),
            ('max_file_age_months', '24'),
            ('workers', '4'),
            ('safe_c3d_folder', '')
            ON CONFLICT (key) DO NOTHING;
        """)
    
    conn.commit()
    cur.close()
    conn.close()
    logger.info("Database tables initialized (reset: %s)", reset_tables)