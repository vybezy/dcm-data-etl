import logging
from config import DEFAULT_SETTINGS
from database import db_connection


# Indexes that older versions created on top of UNIQUE constraints; see _create_schema().
REDUNDANT_INDEXES = (
    "idx_patients_mrn",
    "idx_studies_uid",
    "idx_series_uid",
    "idx_instances_sha256",
    "idx_dicom_headers_file",
)


def db_init(reset_tables: bool = False, logger: logging.Logger = None):
    """
    Creates all pipeline tables (and drops them first if reset_tables=True).
    Runs in one transaction: if any statement fails, nothing is half-created,
    and the connection is always closed.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    with db_connection() as conn, conn.cursor() as cur:
        _create_schema(cur, reset_tables, logger)

    logger.info("Database tables initialized (reset: %s)", reset_tables)


def _create_schema(cur, reset_tables: bool, logger: logging.Logger):

    if reset_tables:
        logger.info("Resetting database tables...")
        cur.execute("DROP TABLE IF EXISTS dicom_logger CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dicom_logger_session CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dicom_settings CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dicom_header CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dicom_instances CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dicom_series CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dicom_studies CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dicom_patients CASCADE;")

    
    # Logger Session
   
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_logger_session (
            logses_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            logses_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            logses_userid TEXT DEFAULT current_user,
            logses_machineid TEXT
        );
        
        COMMENT ON COLUMN dicom_logger_session.logses_id IS 'Primary key for the logging session batch.';
        COMMENT ON COLUMN dicom_logger_session.logses_timestamp IS 'Exact UTC timestamp when the batch import initiated.';
        COMMENT ON COLUMN dicom_logger_session.logses_userid IS 'Database user who initiated the import session.';
        COMMENT ON COLUMN dicom_logger_session.logses_machineid IS 'Network identity/hostname of the machine running the import script.';
    """)

    
    # Logger
  
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_logger (
            log_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            log_logses_id INTEGER NOT NULL REFERENCES dicom_logger_session(logses_id) ON DELETE CASCADE,
            log_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            log_level VARCHAR(10) NOT NULL,
            log_dicomfile VARCHAR(100) NOT NULL, 
            log_message TEXT NOT NULL,
            log_module VARCHAR(100) NOT NULL,
            log_function VARCHAR(100) NOT NULL,
            log_line_number INTEGER NOT NULL,
            log_process_name VARCHAR(100) NOT NULL,
            log_thread_name VARCHAR(100) NOT NULL,
            log_exception_type VARCHAR(200),
            log_stack_trace TEXT
        );
        
        COMMENT ON COLUMN dicom_logger.log_id IS 'Primary key for the individual log event.';
        COMMENT ON COLUMN dicom_logger.log_logses_id IS 'Foreign key tying this log to a specific import batch session.';
        COMMENT ON COLUMN dicom_logger.log_timestamp IS 'Exact timestamp of the logged event.';
        COMMENT ON COLUMN dicom_logger.log_level IS 'Severity level (e.g., INFO, ERROR, CRITICAL).';
        COMMENT ON COLUMN dicom_logger.log_dicomfile IS 'The specific DICOM file being processed during the event.';
        COMMENT ON COLUMN dicom_logger.log_message IS 'Descriptive logging message or error summary.';
        COMMENT ON COLUMN dicom_logger.log_module IS 'Python module where the event was triggered.';
        COMMENT ON COLUMN dicom_logger.log_function IS 'Python function where the event was triggered.';
        COMMENT ON COLUMN dicom_logger.log_line_number IS 'Code line number for debugging.';
        COMMENT ON COLUMN dicom_logger.log_process_name IS 'Multiprocessing worker name.';
        COMMENT ON COLUMN dicom_logger.log_thread_name IS 'Thread name executing the process.';
        COMMENT ON COLUMN dicom_logger.log_exception_type IS 'Type of Python exception caught, if any.';
        COMMENT ON COLUMN dicom_logger.log_stack_trace IS 'Full traceback for post-mortem debugging.';
    """)

    
    # Settings

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        
        COMMENT ON COLUMN dicom_settings.key IS 'Configuration parameter name (e.g., max_file_size).';
        COMMENT ON COLUMN dicom_settings.value IS 'Configuration parameter value stored as text for flexible casting.';
    """)

    # Patients

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_patients (
            patient_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            medical_record_number VARCHAR(64) UNIQUE NOT NULL,
            patient_name VARCHAR(255) NOT NULL DEFAULT 'ANONYMOUS',
            birth_date DATE,
            sex VARCHAR(16),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );

        COMMENT ON TABLE dicom_patients IS 'Root entity of the DICOM hierarchy representing unique individuals.';
        COMMENT ON COLUMN dicom_patients.patient_id IS 'Surrogate primary key for internal foreign key referencing.';
        COMMENT ON COLUMN dicom_patients.medical_record_number IS 'Clinical patient identifier extracted from DICOM Tag (0010,0020). UNIQUE constraint; its index serves upsert lookups.';
        COMMENT ON COLUMN dicom_patients.patient_name IS 'Extracted from DICOM Tag (0010,0010). Typically masked or anonymized in public research cohorts.';
        COMMENT ON COLUMN dicom_patients.birth_date IS 'Extracted from DICOM Tag (0010,0030). Used for cohort age segmentation.';
        COMMENT ON COLUMN dicom_patients.sex IS 'Extracted from DICOM Tag (0010,0040) (e.g., M, F, O).';
        COMMENT ON COLUMN dicom_patients.created_at IS 'UTC timestamp recording when this patient profile was first ingested.';
    """)


    # Studies (Clinical Examination / Hospital Appointment)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_studies (
            study_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            study_instance_uid VARCHAR(128) UNIQUE NOT NULL,
            study_date DATE,
            study_time TIME,
            accession_number VARCHAR(64),
            study_description TEXT,
            referring_physician VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

            CONSTRAINT fk_dicom_studies_patient FOREIGN KEY(patient_id)
                REFERENCES dicom_patients(patient_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_studies_patient_id 
            ON dicom_studies(patient_id);
            

        COMMENT ON TABLE dicom_studies IS 'Clinical study or exam visit containing one or more imaging series.';
        COMMENT ON COLUMN dicom_studies.study_id IS 'Surrogate primary key for internal referencing.';
        COMMENT ON COLUMN dicom_studies.patient_id IS 'Foreign key linking this exam back to the master patient profile.';
        COMMENT ON COLUMN dicom_studies.study_instance_uid IS 'Globally unique identifier extracted from DICOM Tag (0020,000D). UNIQUE constraint; its index serves upsert lookups.';
        COMMENT ON COLUMN dicom_studies.study_date IS 'Date the examination occurred, extracted from DICOM Tag (0080,0020).';
        COMMENT ON COLUMN dicom_studies.study_time IS 'Time of acquisition, extracted from DICOM Tag (0080,0030).';
        COMMENT ON COLUMN dicom_studies.accession_number IS 'Hospital billing/order identifier extracted from DICOM Tag (0008,0050).';
        COMMENT ON COLUMN dicom_studies.study_description IS 'Clinical exam summary (e.g., CT CHEST WITHOUT CONTRAST) from Tag (0008,1030).';
        COMMENT ON COLUMN dicom_studies.referring_physician IS 'Physician ordering the study from DICOM Tag (0008,0090).';
        COMMENT ON COLUMN dicom_studies.created_at IS 'UTC timestamp recording when this study was ingested.';
        COMMENT ON INDEX idx_studies_patient_id IS 'B-Tree Index: Optimizes joins to fetch all medical exams belonging to a single patient.';
    """)


    # Series (Scanner Protocol / Acquisition Run)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_series (
            series_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            study_id INTEGER NOT NULL,
            series_instance_uid VARCHAR(128) UNIQUE NOT NULL,
            series_number INTEGER,
            modality VARCHAR(16) NOT NULL,
            body_part_examined VARCHAR(64),
            series_description TEXT,
            slice_thickness_mm FLOAT8,
            pixel_spacing FLOAT8[],
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

            CONSTRAINT fk_dicom_series_study FOREIGN KEY(study_id)
                REFERENCES dicom_studies(study_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_series_study_id 
            ON dicom_series(study_id);
            
        CREATE INDEX IF NOT EXISTS idx_series_modality 
            ON dicom_series(modality);

        COMMENT ON TABLE dicom_series IS 'Specific imaging run or protocol within a clinical study.';
        COMMENT ON COLUMN dicom_series.series_id IS 'Surrogate primary key for internal referencing.';
        COMMENT ON COLUMN dicom_series.study_id IS 'Foreign key linking this series back to its parent clinical study.';
        COMMENT ON COLUMN dicom_series.series_instance_uid IS 'Globally unique identifier for the series extracted from DICOM Tag (0020,000E). UNIQUE constraint; its index serves upsert lookups.';
        COMMENT ON COLUMN dicom_series.series_number IS 'Sequential number of this run within the study, from Tag (0020,0011).';
        COMMENT ON COLUMN dicom_series.modality IS 'Imaging technology used (e.g., CT, MR, PT) extracted from Tag (0008,0060).';
        COMMENT ON COLUMN dicom_series.body_part_examined IS 'Target anatomy (e.g., CHEST, ABDOMEN) extracted from Tag (0018,0015).';
        COMMENT ON COLUMN dicom_series.series_description IS 'Technical run description extracted from Tag (0008,103E).';
        COMMENT ON COLUMN dicom_series.slice_thickness_mm IS 'Physical depth of the slices in millimeters, extracted from Tag (0018,0050).';
        COMMENT ON COLUMN dicom_series.pixel_spacing IS 'Physical distance between pixel centers [row, col] in mm, extracted from Tag (0028,0030).';
        COMMENT ON COLUMN dicom_series.created_at IS 'UTC timestamp recording when this series was ingested.';
        COMMENT ON INDEX idx_series_study_id IS 'B-Tree Index: Optimizes joins to fetch all scan series belonging to a specific hospital visit.';
        COMMENT ON INDEX idx_series_modality IS 'B-Tree Index: Enables rapid filtering of the database by imaging technology.';
    """)


    # Instances

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_instances ( 
            file_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            series_id INTEGER NOT NULL,
            sop_instance_uid VARCHAR(128) UNIQUE NOT NULL,
            instance_number INTEGER,
            file_name VARCHAR(255) NOT NULL,
            file_path TEXT NOT NULL,
            file_size_bytes BIGINT NOT NULL,
            file_sha256_hash VARCHAR(64) UNIQUE NOT NULL,
            image_position_patient FLOAT8[],
            rows INTEGER,
            columns INTEGER,
            metadata_json JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

            CONSTRAINT fk_dicom_instances_series FOREIGN KEY(series_id)
                REFERENCES dicom_series(series_id) ON DELETE CASCADE
        );
        
        CREATE INDEX IF NOT EXISTS idx_instances_series_id ON dicom_instances(series_id);
        CREATE INDEX IF NOT EXISTS idx_instances_metadata_gin ON dicom_instances USING GIN (metadata_json);

        COMMENT ON TABLE dicom_instances IS 'Master record for the physical DICOM files (.dcm) on disk.';
        COMMENT ON COLUMN dicom_instances.file_id IS 'Master Primary Key for the imported DICOM file. All metadata tables link back to this ID.';
        COMMENT ON COLUMN dicom_instances.series_id IS 'Foreign key linking this file to its parent acquisition series.';
        COMMENT ON COLUMN dicom_instances.sop_instance_uid IS 'Globally unique identifier for this specific image slice, extracted from Tag (0008,0018).';
        COMMENT ON COLUMN dicom_instances.instance_number IS 'Slice number within the series, extracted from Tag (0020,0013).';
        COMMENT ON COLUMN dicom_instances.file_name IS 'Original file name of the DICOM file.';
        COMMENT ON COLUMN dicom_instances.file_path IS 'Absolute filesystem path to the source file.';
        COMMENT ON COLUMN dicom_instances.file_size_bytes IS 'File size in bytes.';
        COMMENT ON COLUMN dicom_instances.file_sha256_hash IS 'SHA-256 of the file contents. UNIQUE constraint; its index powers duplicate detection.';
        COMMENT ON COLUMN dicom_instances.image_position_patient IS '3D physical coordinates [x, y, z] of the slice relative to the patient coordinate system.';
        COMMENT ON COLUMN dicom_instances.rows IS 'Matrix row count (e.g., 512) from Tag (0028,0010).';
        COMMENT ON COLUMN dicom_instances.columns IS 'Matrix column count (e.g., 512) from Tag (0028,0011).';
        COMMENT ON COLUMN dicom_instances.metadata_json IS 'Complete extracted DICOM header dictionary stored as a queryable JSONB document.';
        COMMENT ON COLUMN dicom_instances.created_at IS 'Timestamp of when the file was ingested into the database.';
        
        COMMENT ON INDEX idx_instances_series_id IS 'B-Tree Index: Optimizes foreign key joins to group all slices for a specific scan.';
        COMMENT ON INDEX idx_instances_metadata_gin IS 'GIN Index: Enables lightning-fast searches deep inside the unstructured DICOM metadata payload.';
    """)

    
    # Header (Tag Dictionary)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dicom_header (
            header_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            header_file_id INTEGER NOT NULL,
            header_tag VARCHAR(16) NOT NULL,
            header_name TEXT NOT NULL,
            header_vr VARCHAR(4),
            header_value TEXT NOT NULL,
            
            UNIQUE(header_file_id, header_tag),
            
            CONSTRAINT fk_dicom_headers_file_id FOREIGN KEY(header_file_id)
                REFERENCES dicom_instances(file_id) ON DELETE CASCADE
        );
                
        CREATE INDEX IF NOT EXISTS idx_dicom_headers_tag 
            ON dicom_header(header_tag);

        COMMENT ON TABLE dicom_header IS 'Normalized key-value store for individual DICOM header tags per image instance.';
        COMMENT ON COLUMN dicom_header.header_id IS 'Surrogate primary key for the individual header tag record.';
        COMMENT ON COLUMN dicom_header.header_file_id IS 'Foreign key linking to the master DICOM file.';
        COMMENT ON COLUMN dicom_header.header_tag IS 'Hexadecimal DICOM tag identifier in (GGGG,EEEE) format (e.g., (0008,0060) or (0020,0032)).';
        COMMENT ON COLUMN dicom_header.header_name IS 'Standardized DICOM keyword/element name (e.g., Modality, PatientName, SliceThickness).';
        COMMENT ON COLUMN dicom_header.header_vr IS 'DICOM Value Representation code defining data type (e.g., CS=Code String, DS=Decimal String, UI=UID).';
        COMMENT ON COLUMN dicom_header.header_value IS 'The stringified value extracted from the DICOM element.';
        
        COMMENT ON INDEX idx_dicom_headers_tag IS 'B-Tree Index: Enables rapid filtering across all files by specific tag (e.g., finding all slices with a specific Modality or PhotometricInterpretation).';
    """)
    

    # Remove indexes created by earlier versions of this schema. Each one
    # duplicated an index PostgreSQL already builds for a UNIQUE constraint
    # (the composite UNIQUE(header_file_id, header_tag) also covers lookups on
    # header_file_id alone). Harmless no-op on a fresh database.
    for redundant_index in REDUNDANT_INDEXES:
        cur.execute(f"DROP INDEX IF EXISTS {redundant_index};")

    # Default settings: inserted on every run, but ON CONFLICT keeps any value
    # an operator has already changed, so tuned settings survive restarts.
    cur.executemany(
        "INSERT INTO dicom_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;",
        list(DEFAULT_SETTINGS.items()),
    )
