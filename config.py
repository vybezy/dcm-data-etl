import os
from dotenv import load_dotenv

def config():

    # Loads database configuration from .env file.

    # load .env file variables 
    load_dotenv()
    
    # saves environment variables to the dictionary keys
    db = {
        'host': os.getenv('DB_HOST'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    # missing .env file / misspelled variable safety check
    if not all(db.values()):
        raise Exception(
            "Missing database credentials. Ensure a .env file exists "
            "with DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD defined."
        )
        
    return db