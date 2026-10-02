import numpy as np
from extractor import make_json_safe

def test_make_json_safe_numpy_arrays():
    # creates 2D numpy array 
    np_array = np.array([[1.5, 2.5], [3.5, 4.5]])
    
    # passes it through cleaner
    result = make_json_safe(np_array)
    
    # asserts it was converted to a standard nested list
    assert isinstance(result, list)
    assert result == [[1.5, 2.5], [3.5, 4.5]]

def test_make_json_safe_nested_structures():
    # tests a mix of tuples, lists, and numpy arrays
    complex_data = (
        "POINT",
        np.array([1, 2, 3]),
        [np.array([4, 5])]
    )
    
    result = make_json_safe(complex_data)
    
    # asserts tuples are converted to lists and arrays inside lists are converted
    assert result == ["POINT", [1, 2, 3], [[4, 5]]]