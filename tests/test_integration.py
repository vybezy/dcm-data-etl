import pytest
from unittest.mock import MagicMock, patch
from extractor import extract_and_insert_headers

# integration tests using mocking

def test_header_extraction_to_database_integration():

    # creates fake C3D dictionary mocking ezc3d output
    mock_c3d = {
        'header': {
            'points': {'rate': 100.0, 'count': 50},
            'analogs': {'rate': 1000.0}
        }
    }
    
    # creates mock database connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # runs extractor function with fake data and fake DB connection
    file_id = 99
    
    with patch('psycopg2.extras.execute_values') as mock_execute:
        extract_and_insert_headers(mock_conn, file_id, mock_c3d)

        assert mock_execute.call_count == 1
        
        # extracts arguments passed to execute_values function
        called_args = mock_execute.call_args[0]
        
        # second argument: query, third argument: data list
        query = called_args[1]
        data_payload = called_args[2]
        
        # verifies sql query targets right table
        assert "INSERT INTO c3d_header" in query
        
        # verifies it extracted points rate, points count, analogs rate
        assert len(data_payload) == 3
        
        # verifies payload structure matches postgres expectations: file_id, header_name, header_key, value
        assert (99, 'POINT_RATE', 'POINT', '100.0') in data_payload
        assert (99, 'ANALOG_RATE', 'ANALOG', '1000.0') in data_payload