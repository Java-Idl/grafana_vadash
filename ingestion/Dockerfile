FROM python:3.11-slim

# Prevent Python from writing .pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies directly using pip
# psycopg2-binary avoids needing gcc and libpq-dev build tools, keeping container slim
# numpy<2 prevents binary incompatibility with pandas 2.1.1
RUN pip install --no-cache-dir \
    "numpy<2" \
    pandas==2.1.1 \
    psycopg2-binary==2.9.9

# Copy ingestion engine script
COPY ingest.py /app/ingest.py

# Launch Python in unbuffered mode
CMD ["python", "-u", "ingest.py"]
