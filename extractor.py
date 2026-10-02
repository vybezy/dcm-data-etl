import json
import ezc3d
import numpy as np
import psycopg2.extras
from config import config
from logger import logger
from utils import Profiler, handle_exception


# ------------------------- Metadata Extraction -------------------------


def make_json_safe(data):
    """
    Recursively cleans data so it is safe for PostgreSQL JSONB storage.
    """
    if isinstance(data, np.ndarray):
        data = data.tolist()
        
    if isinstance(data, (list, tuple)): # if its list/tuple
        return [make_json_safe(v) for v in data] # recursively checks all lists within lists if they exist 
        
    return data

def extract_and_insert_headers(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the basic header section of the C3D file.
    """
    headers_to_insert = []
    
    header_sections = { 
        'POINT': c3d_data['header'].get('points', {}),
        'ANALOG': c3d_data['header'].get('analogs', {})
    }

    for section_key, section_data in header_sections.items(): 
        for key, value in section_data.items():
            header_name = f"{section_key}_{key.upper()}"
            headers_to_insert.append((file_id, header_name, section_key, str(value)))

    if headers_to_insert:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_header (header_file_id, header_name, header_key, header_value)
                VALUES %s
                ON CONFLICT (header_file_id, header_name) DO NOTHING;
                """,
                headers_to_insert,
                template="(%s, %s, %s, %s)",
                page_size=1000
            )
            conn.commit()

@Profiler
def extract_and_insert_parameters(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the deep metadata parameters using strict anti-corruption checks.
    """
    params_to_insert = []
    parameters_section = c3d_data.get('parameters', {})
    
    for group_name, group_data in parameters_section.items():
        if not isinstance(group_data, dict):
            continue

        clean_group = group_name.replace("\x00", "").strip()

        for param_key, param_info in group_data.items():
            if not isinstance(param_info, dict) or "value" not in param_info:
                continue
            
            clean_key = param_key.replace("\x00", "").strip()
            if not clean_key:
                continue
                
            value = param_info["value"]
            description = param_info.get("description", "").replace("\x00", "").strip()
            
            dimensions = param_info.get("dimension", [])
            if not dimensions and isinstance(value, np.ndarray):
                dimensions = list(value.shape)
                
            if not isinstance(dimensions, (list, tuple)):
                dimensions = []

            if len(dimensions) > 5:
                logger.warning(f"Excessive dimensions in {clean_group}.{clean_key}. Skipping.")
                continue
            
            try:
                clean_value = make_json_safe(value)
                json_data = json.dumps(clean_value)
            except Exception as e:
                logger.warning(f"Cannot convert value to JSON in {clean_group}.{clean_key}: {e}")
                continue
            
            is_locked = bool(param_info.get('is_locked', False))

            params_to_insert.append((
                file_id, clean_group.upper(), clean_key.upper(),
                description, str(dimensions), is_locked, json_data
            ))

    if params_to_insert:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_parameters (
                    parameters_file_id,parameters_group, 
                    parameters_key, 
                    parameters_description, parameters_dimensions, parameters_lock, parameters_value_json
                )
                VALUES %s
                ON CONFLICT DO NOTHING;
                """,
                params_to_insert,
                template="(%s, %s, %s, %s, %s, %s, %s)",
                page_size=1000
            )
            conn.commit()

@Profiler
def extract_and_insert_analog(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the massive time-series arrays for Analog data (e.g., Force Plates, EMG).
    Uses execute_values for high-speed bulk inserts.
    """
    analog_to_insert = []
    
    # get the data and parameters
    analog_data = c3d_data.get('data', {}).get('analogs')
    analog_params = c3d_data.get('parameters', {}).get('ANALOG', {})
    
    # if there is no analog data (or empty), skip
    if analog_data is None or analog_data.size == 0 or len(analog_data.shape) != 3:
        return

    num_channels = analog_data.shape[1]
    
    # extract the metadata lists
    labels = analog_params.get('LABELS', {}).get('value', [])
    units = analog_params.get('UNITS', {}).get('value', [])
    gains = analog_params.get('GEN_SCALE', {}).get('value', [])
    offsets = analog_params.get('OFFSET', {}).get('value', [])
    descs = analog_params.get('DESCRIPTIONS', {}).get('value', [])

    for i in range(num_channels):
        # extract matching metadata by index, with fallbacks if C3D is poorly formatted
        label = labels[i] if i < len(labels) and labels[i] else f"Analog_{i}"
        unit = str(units[i]) if i < len(units) and units[i] else ""
        gain = str(gains[i]) if i < len(gains) and gains[i] else ""
        
        offset = None
        if i < len(offsets) and offsets[i] is not None:
            try:
                offset = int(float(offsets[i]))
            except ValueError:
                pass
                
        desc = str(descs[i]) if i < len(descs) and descs[i] else ""
        
        # extract the entire time-series array for this channel and convert to a list
        frames = analog_data[0, i, :].tolist()

        analog_to_insert.append((
            file_id, label, unit, gain, frames, offset, desc
        ))

    if analog_to_insert:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_analog (
                    analog_file_id, analog_label, analog_unit, 
                    analog_gain, analog_frames, analog_offset, analog_desc
                )
                VALUES %s
                ON CONFLICT DO NOTHING;
                """,
                analog_to_insert,
                template="(%s, %s, %s, %s, %s, %s, %s)",
                page_size=500
            )
            conn.commit()

@Profiler
def extract_and_insert_points(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the 3D trajectory tracking points.
    Uses execute_values for high-speed bulk inserts.
    """
    points_to_insert = []
    
    point_data = c3d_data.get('data', {}).get('points')
    point_params = c3d_data.get('parameters', {}).get('POINT', {})
    
    # if there is no point data, skip
    if point_data is None or point_data.size == 0 or len(point_data.shape) != 3:
        return

    num_points = point_data.shape[1]
    num_frames = point_data.shape[2]
    
    labels = point_params.get('LABELS', {}).get('value', [])

    for i in range(num_points):
        label = labels[i] if i < len(labels) and labels[i] else f"Point_{i}"
        
        # extract the X, Y, Z, and residual arrays 
        x_frames = point_data[0, i, :].tolist()
        y_frames = point_data[1, i, :].tolist()
        z_frames = point_data[2, i, :].tolist()
        r_frames = point_data[3, i, :].tolist()

        points_to_insert.append((
            file_id, num_frames, label, 
            x_frames, y_frames, z_frames, r_frames
        ))

    if points_to_insert:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_points (
                    points_file_id, points_frame_count, points_label, 
                    points_frames_x, points_frames_y, points_frames_z, points_frames_r
                )
                VALUES %s
                ON CONFLICT DO NOTHING;
                """,
                points_to_insert,
                template="(%s, %s, %s, %s, %s, %s, %s)",
                page_size=500
            )
            conn.commit()

def process_c3d_metadata(file_id: int, file_path: str):
    """
    Main entry point. Extracts only headers and parameters sequentially.
    """
    try:     
        c3d_data = ezc3d.c3d(file_path)
        params = config()
        
        with psycopg2.connect(**params) as conn:
            extract_and_insert_headers(conn, file_id, c3d_data)
            
            extract_and_insert_parameters(conn, file_id, c3d_data)

            extract_and_insert_analog(conn, file_id, c3d_data)

            extract_and_insert_points(conn, file_id, c3d_data)
            
        logger.info(f"Successfully processed headers and parameters for file_id: {file_id}")
        return True
        
    except Exception as e:
        handle_exception(e, options=None, file_path=file_path, level="ERROR")
        return False