import os
import sys
import time
import re
import shutil
import logging
from datetime import datetime
import pandas as pd
import psycopg2

# Set up logging to stdout for Docker Compose compatibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Load configuration from environment variables
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_NAME = os.getenv("DB_NAME", "postgres")
SCAN_FILES_PATH = os.getenv("SCAN_FILES_PATH", "/app/scan_files")
AUDIT_LOG_FILE = os.path.join(SCAN_FILES_PATH, "ingestion_audit.log")

# Setup folder paths
ARCHIVE_PATH = os.path.join(SCAN_FILES_PATH, "archive")

# Mapping dictionary for cleaning and matching various Nessus CSV column spellings
HEADER_MAPPING = {
    'plugin_id': 'plugin_id',
    'pluginid': 'plugin_id',
    'plugin_ids': 'plugin_id',
    'cve': 'cve',
    'cves': 'cve',
    'cvss_v20_base_score': 'cvss_base_score',
    'cvss_v30_base_score': 'cvss_base_score',
    'cvss_base_score': 'cvss_base_score',
    'cvss_v2_base_score': 'cvss_base_score',
    'cvss_v3_base_score': 'cvss_base_score',
    'cvss_score': 'cvss_base_score',
    'cvss': 'cvss_base_score',
    'risk': 'risk',
    'severity': 'risk',
    'host': 'host',
    'ip': 'host',
    'ip_address': 'host',
    'address': 'host',
    'protocol': 'protocol',
    'port': 'port',
    'name': 'name',
    'title': 'name',
    'synopsis': 'synopsis',
    'description': 'description',
    'solution': 'solution',
    'see_also': 'see_also',
    'seealso': 'see_also',
    'plugin_output': 'plugin_output',
    'pluginoutput': 'plugin_output'
}

def clean_column_name(col):
    """
    Cleans column headers: lowercases, removes non-alphanumeric chars,
    and replaces spaces with underscores.
    """
    col_clean = re.sub(r'[^a-z0-9\s]', '', col.lower())
    col_clean = col_clean.replace(' ', '_').strip('_')
    return col_clean

def initialize_database_schema(conn):
    """
    Auto-initializes the PostgreSQL table schema and indexes if they do not exist.
    This makes the application self-contained without needing db_init.sql on the host.
    """
    schema_sql = """
    CREATE TABLE IF NOT EXISTS vulnerabilities (
        id SERIAL PRIMARY KEY,
        plugin_id INTEGER,
        cve VARCHAR(100),
        cvss_base_score NUMERIC(3,1),
        risk VARCHAR(20),
        host VARCHAR(255),
        protocol VARCHAR(20),
        port VARCHAR(20),
        name TEXT,
        synopsis TEXT,
        description TEXT,
        solution TEXT,
        see_also TEXT,
        plugin_output TEXT,
        source_file VARCHAR(255) NOT NULL,
        ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_vulnerabilities_risk ON vulnerabilities(risk);
    CREATE INDEX IF NOT EXISTS idx_vulnerabilities_host ON vulnerabilities(host);
    CREATE INDEX IF NOT EXISTS idx_vulnerabilities_source_file ON vulnerabilities(source_file);
    CREATE INDEX IF NOT EXISTS idx_vulnerabilities_ingested_at ON vulnerabilities(ingested_at);
    """
    try:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
        logging.info("Database schema and indexes checked/initialized successfully.")
    except Exception as e:
        conn.rollback()
        logging.error(f"Failed to auto-initialize database schema: {e}")

def initialize_grafana_provisioning():
    """
    Auto-provisions the Grafana data source dynamically if the shared volume is mapped.
    """
    prov_path = "/app/grafana_provisioning"
    if not os.path.exists(prov_path):
        logging.info("Grafana provisioning path not mapped. Skipping auto-provisioning.")
        return
    
    ds_dir = os.path.join(prov_path, "datasources")
    os.makedirs(ds_dir, exist_ok=True)
    
    ds_file = os.path.join(ds_dir, "datasource.yml")
    
    yaml_content = f"""apiVersion: 1
datasources:
  - name: PostgreSQL
    type: postgres
    access: proxy
    url: db:5432
    user: {DB_USER}
    secureJsonData:
      password: {DB_PASSWORD}
    jsonData:
      database: {DB_NAME}
      sslmode: disable
      postgresVersion: 1500
    isDefault: true
    editable: true
"""
    try:
        with open(ds_file, "w") as f:
            f.write(yaml_content)
        logging.info(f"Grafana data source provisioned dynamically at {ds_file}")
    except Exception as e:
        logging.error(f"Failed to write Grafana datasource provisioning file: {e}")

def wait_for_database():
    """
    Blocks startup by polling the PostgreSQL port until a successful
    database connection is established.
    """
    logging.info("Starting connection loops. Waiting for database to become online...")
    retry_count = 0
    while True:
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                dbname=DB_NAME,
                connect_timeout=3
            )
            # Run self-contained database schema initialization
            initialize_database_schema(conn)
            conn.close()
            
            # Run dynamic Grafana data source auto-provisioning
            initialize_grafana_provisioning()
            
            logging.info("Successfully connected to the database. Ingestion monitoring is ready!")
            break
        except psycopg2.OperationalError as e:
            retry_count += 1
            logging.warning(f"Database not ready yet (attempt #{retry_count}). Retrying in 2 seconds...")
            time.sleep(2)

def audit_record(filename, total_rows, ingested_rows, status="SUCCESS"):
    """
    Writes a persistent data-alignment auditing entry to the host system directory.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] FILE: {filename} | STATUS: {status} | EXPECTED ROWS: {total_rows} | INGESTED ROWS: {ingested_rows}\n"
    
    try:
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(log_entry)
        logging.info(f"Auditing complete: {filename} - Expected: {total_rows}, Ingested: {ingested_rows}")
    except Exception as e:
        logging.error(f"Failed to write to audit log file: {e}")

def process_nessus_file(filepath):
    """
    Parses, cleans, and injects a single Nessus CSV file into PostgreSQL.
    """
    filename = os.path.basename(filepath)
    logging.info(f"Preparing to ingest file: {filename}")
    
    try:
        # Load CSV using pandas
        df = pd.read_csv(filepath)
        total_rows = len(df)
        
        if total_rows == 0:
            logging.warning(f"File {filename} is empty. Archiving immediately.")
            shutil.move(filepath, os.path.join(ARCHIVE_PATH, filename))
            audit_record(filename, 0, 0, status="EMPTY_FILE")
            return

        logging.info(f"Parsed CSV file successfully. Found {total_rows} records.")
        
        # Clean column headers
        original_cols = df.columns.tolist()
        cleaned_cols = [clean_column_name(col) for col in original_cols]
        
        # Map columns to target schema database fields
        mapped_cols = [HEADER_MAPPING.get(c, None) for c in cleaned_cols]
        
        # Establish PostgreSQL connection
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME
        )
        cur = conn.cursor()
        
        ingested_rows = 0
        
        for idx, row in df.iterrows():
            # Build database parameters for the insert query
            # We explicitly define the columns and extract standard values
            row_dict = {}
            for orig, mapped in zip(original_cols, mapped_cols):
                if mapped:
                    row_dict[mapped] = row[orig]
            
            # Clean and sanitize specific data fields before db ingestion
            # 1. plugin_id
            plugin_id_raw = row_dict.get('plugin_id', None)
            try:
                plugin_id = int(float(plugin_id_raw)) if pd.notna(plugin_id_raw) else None
            except (ValueError, TypeError):
                plugin_id = None
                
            # 2. cvss_base_score
            cvss_raw = row_dict.get('cvss_base_score', None)
            try:
                cvss_base_score = float(cvss_raw) if pd.notna(cvss_raw) else None
            except (ValueError, TypeError):
                cvss_base_score = None
            
            # 3. risk
            risk_raw = str(row_dict.get('risk', 'None')).strip().lower().capitalize()
            if risk_raw not in ['Critical', 'High', 'Medium', 'Low', 'None']:
                risk = 'None'
            else:
                risk = risk_raw
                
            # Extract other textual values safely
            cve = str(row_dict.get('cve', ''))[:100] if pd.notna(row_dict.get('cve', None)) else None
            host = str(row_dict.get('host', ''))[:255] if pd.notna(row_dict.get('host', None)) else None
            protocol = str(row_dict.get('protocol', ''))[:20] if pd.notna(row_dict.get('protocol', None)) else None
            port = str(row_dict.get('port', ''))[:20] if pd.notna(row_dict.get('port', None)) else None
            
            name = str(row_dict.get('name', '')) if pd.notna(row_dict.get('name', None)) else None
            synopsis = str(row_dict.get('synopsis', '')) if pd.notna(row_dict.get('synopsis', None)) else None
            description = str(row_dict.get('description', '')) if pd.notna(row_dict.get('description', None)) else None
            solution = str(row_dict.get('solution', '')) if pd.notna(row_dict.get('solution', None)) else None
            see_also = str(row_dict.get('see_also', '')) if pd.notna(row_dict.get('see_also', None)) else None
            plugin_output = str(row_dict.get('plugin_output', '')) if pd.notna(row_dict.get('plugin_output', None)) else None
            
            # Insert record using psycopg2 parameterized querying to protect from SQL injection
            insert_query = """
                INSERT INTO vulnerabilities (
                    plugin_id, cve, cvss_base_score, risk, host, protocol, port,
                    name, synopsis, description, solution, see_also, plugin_output, source_file
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            try:
                cur.execute(insert_query, (
                    plugin_id, cve, cvss_base_score, risk, host, protocol, port,
                    name, synopsis, description, solution, see_also, plugin_output, filename
                ))
                ingested_rows += 1
            except Exception as e_row:
                logging.error(f"Error ingesting row #{idx} in {filename}: {e_row}")
                conn.rollback()
                continue
        
        # Commit transaction once all rows in file have been inserted
        conn.commit()
        cur.close()
        conn.close()
        
        # Archive file after successful DB confirmation
        os.makedirs(ARCHIVE_PATH, exist_ok=True)
        
        # Append unique timestamp to the archived file name to avoid overwrite collisions
        timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_parts = os.path.splitext(filename)
        archived_filename = f"{name_parts[0]}_{timestamp_suffix}{name_parts[1]}"
        shutil.move(filepath, os.path.join(ARCHIVE_PATH, archived_filename))
        
        logging.info(f"File {filename} successfully imported. Moved to archive as: {archived_filename}")
        
        # Record data auditing statistics
        audit_record(filename, total_rows, ingested_rows, status="SUCCESS")
        
    except Exception as e:
        logging.error(f"Fatal error processing file {filename}: {e}")
        audit_record(filename, 0, 0, status=f"FAILED: {str(e)[:100]}")
        # Move failed file out to prevent endless processing loop
        try:
            os.makedirs(ARCHIVE_PATH, exist_ok=True)
            failed_filename = f"FAILED_{filename}"
            shutil.move(filepath, os.path.join(ARCHIVE_PATH, failed_filename))
            logging.info(f"Moved failed file to: {failed_filename}")
        except Exception as move_err:
            logging.error(f"Failed to move broken file {filename}: {move_err}")

def start_file_watcher():
    """
    Main watcher loop. Scans active directory, performs write contention delay,
    and dispatches parsing routines.
    """
    # Auto-create intake folder directories
    os.makedirs(SCAN_FILES_PATH, exist_ok=True)
    os.makedirs(ARCHIVE_PATH, exist_ok=True)
    
    logging.info(f"Watching directory: '{SCAN_FILES_PATH}' for incoming Nessus CSV files...")
    
    while True:
        # Scan folder for CSV files
        try:
            files = [
                os.path.join(SCAN_FILES_PATH, f)
                for f in os.listdir(SCAN_FILES_PATH)
                if f.lower().endswith('.csv') and os.path.isfile(os.path.join(SCAN_FILES_PATH, f))
            ]
        except Exception as e:
            logging.error(f"Error scanning directory '{SCAN_FILES_PATH}': {e}")
            time.sleep(5)
            continue
            
        for filepath in files:
            # File Contention Mitigation:
            # Wait 3 seconds and verify file size is stable (ensuring host complete file export)
            try:
                size_t0 = os.path.getsize(filepath)
                time.sleep(3)
                size_t1 = os.path.getsize(filepath)
                
                if size_t0 != size_t1:
                    logging.info(f"File {os.path.basename(filepath)} is currently being written (sizes: {size_t0} vs {size_t1}). Skipping for now.")
                    continue
                
                # Sizes are stable, initiate ingestion!
                process_nessus_file(filepath)
                
            except FileNotFoundError:
                # File was removed or processed in the meantime
                continue
            except Exception as contention_err:
                logging.error(f"Error handling contention verification for {os.path.basename(filepath)}: {contention_err}")
                
        # Polling sleep interval
        time.sleep(5)

if __name__ == "__main__":
    logging.info("Vulnerability Ingestion Engine Container Initializing...")
    wait_for_database()
    start_file_watcher()
