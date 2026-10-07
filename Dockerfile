FROM python:3.11-slim

# set working directory in container
WORKDIR /app

# install system dependencies required for psycopg2 and numpy
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# copy requirements file into the container and install libraries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy in container
COPY . .

# Run the manager script when the container launches
CMD ["python", "main.py"]