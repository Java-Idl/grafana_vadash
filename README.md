# Nessus Ingest and Grafana Dashboard Pipeline

This project is a clean, multi-container pipeline built to automate the parsing, storage, and visualization of Nessus vulnerability reports (CSV exports). 

If you have ever tried manually formatting and copying vulnerability scan data, you know it can be tedious. Column names can change slightly between exports, files can overwrite each other, and tracking security trends over time is difficult. This project solves those problems by automating the entire ingestion flow using Docker Compose, Python, PostgreSQL, and Grafana.

---

## Quick Start: Zero-Download Deploy (No Repository Download Needed)

You do not need to clone this repository or download any files to run this application. You can deploy the complete pipeline on any machine using only Docker Compose by following these steps:

### 1. Create a Project Folder
Create a folder on your system where you want the pipeline to run, for example, `nessus-pipeline`.

### 2. Create the Configuration Files
Inside that folder, create the following two files:

#### Create `docker-compose.yml`
Copy and paste this exact content into a file named `docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:15-alpine
    container_name: vadash_postgres
    restart: always
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - ./postgres_data:/var/lib/postgresql/data
    networks:
      - vulnerability_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 5s

  ingestion:
    image: galahanorg/nessus-ingester:latest
    container_name: vadash_ingestion
    restart: always
    environment:
      - DB_HOST=db
      - DB_PORT=5432
      - DB_USER=${POSTGRES_USER}
      - DB_PASSWORD=${POSTGRES_PASSWORD}
      - DB_NAME=${POSTGRES_DB}
      - SCAN_FILES_PATH=/app/scan_files
    volumes:
      - ${SCAN_FILES_PATH}:/app/scan_files
      - grafana_provisioning:/app/grafana_provisioning
    networks:
      - vulnerability_net
    depends_on:
      db:
        condition: service_healthy

  grafana:
    image: grafana/grafana:latest
    container_name: vadash_grafana
    restart: always
    ports:
      - "${GRAFANA_PORT}:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
      - DB_USER=${POSTGRES_USER}
      - DB_PASSWORD=${POSTGRES_PASSWORD}
      - DB_NAME=${POSTGRES_DB}
    volumes:
      - grafana_provisioning:/etc/grafana/provisioning
      - grafana_storage:/var/lib/grafana
    networks:
      - vulnerability_net
    depends_on:
      db:
        condition: service_healthy

networks:
  vulnerability_net:
    driver: bridge

volumes:
  grafana_storage:
    driver: local
  grafana_provisioning:
    driver: local
```

#### Create `.env`
Copy and paste this content into a file named `.env` in the same directory:

```ini
# Database Credentials and Configuration
POSTGRES_USER=nessus_user
POSTGRES_PASSWORD=nessus_secure_password_123
POSTGRES_DB=nessus_vulnerabilities
DB_PORT=5432

# Grafana Dashboard Configuration
GRAFANA_PORT=3000

# File Monitor and Archiving Paths
SCAN_FILES_PATH=./scan_files
```

### 3. Start the Pipeline
Open your terminal inside your `nessus-pipeline` folder and run the following command:

```bash
docker compose up -d
```

### 4. Feed a Nessus CSV Scan
1. Docker will automatically create a `./scan_files` folder in your directory.
2. Drag and drop any Nessus CSV report into the `./scan_files` folder.
3. The Python daemon will:
   - Detect the file within 5 seconds.
   - Wait 3 seconds to ensure the file is fully written and its size is stable.
   - Normalize column names dynamically, insert the data, and append a status to `./scan_files/ingestion_audit.log`.
   - Rename and move the file into `./scan_files/archive/` (adding a unique timestamp to prevent collisions).

---

## Alternative Setup: Cloning the Repository

If you prefer to clone the repository and run the setup locally, use these options:

### Option A: Standard Run
Clone this repository and run docker compose from the project root:

```bash
# Clone the repository
git clone https://github.com/Java-Idl/grafana_vadash.git

# Navigate into the project folder
cd grafana_vadash

# Start the stack
docker compose up -d
```

### Option B: Developer Setup (Custom Building)
If you want to modify the Python parser script (`ingest.py`) or customize the Dockerfile, you can build your changes into a local image first:

```bash
# Build the image locally
docker build -t galahanorg/nessus-ingester:latest ./ingestion

# Start the stack using your local image
docker compose up -d
```

---

## How the Architecture Works

Here is a quick overview of how the three containers work together:

1. **PostgreSQL Database (vadash_postgres)**: The storage layer. It maintains the database state and persists the parsed vulnerability records.
2. **Python Ingest Daemon (vadash_ingestion)**: The parsing layer. This container actively watches the scan files directory. When a Nessus CSV is placed there, it performs write-contention checks, cleans up headers, parses the records, commits them to the database, audits the row count, and archives the processed file.
3. **Grafana Visualization (vadash_grafana)**: The presentation layer. It comes pre-provisioned, meaning it connects to the database automatically on startup so you do not have to manually configure hostnames, database names, or credentials in the browser interface.

---

## Setting Up Your Grafana Dashboard

Grafana is automatically connected to your PostgreSQL database out of the box.

1. Go to `http://localhost:3000` in your web browser.
2. Log in with **Username: admin / Password: admin** (you will be asked to change this on your first login).
3. Create a new dashboard.

### Step 1: Set up a Dynamic File Filter (Variable)
Before making panels, create a dropdown filter to let you isolate specific scan files:
1. In your dashboard, click the Gear icon (Dashboard settings) in the top-right corner.
2. Go to **Variables** and click **Add variable**.
3. Configure the following settings:
   - **Name**: source_file
   - **Type**: Query
   - **Label**: Scan File
   - **Data source**: PostgreSQL
   - **Query**:
     ```sql
     SELECT DISTINCT source_file FROM vulnerabilities ORDER BY source_file DESC;
     ```
   - **Selection Options**: Turn on **Multi-value** and **Include All option**.
4. Click **Apply**. You will now see a dropdown menu at the top of your dashboard.

---

### Step 2: Create Dashboard Panels with SQL Queries

Click **Add Panel** > **Add a new panel** and use these SQL queries to build your dashboard widgets:

#### Panel A: Risk Distribution (Stat Panel)
Shows a quick count of Critical, High, Medium, and Low issues across selected scans.
- **Visualization**: Stat
- **SQL Query**:
  ```sql
  SELECT 
    risk, 
    count(*) as count
  FROM vulnerabilities
  WHERE source_file IN (${source_file:sqlstring})
  GROUP BY risk
  ORDER BY CASE risk
    WHEN 'Critical' THEN 1
    WHEN 'High' THEN 2
    WHEN 'Medium' THEN 3
    WHEN 'Low' THEN 4
    ELSE 5
  END;
  ```
- *Tip*: Set the panel settings to show "Value + Name" and apply color overrides (Red for Critical, Orange for High, Yellow for Medium).

#### Panel B: Host Exposure Density (Bar Chart)
Identifies the top 15 most vulnerable host IPs or computer names on the network.
- **Visualization**: Bar Chart or Pie Chart
- **SQL Query**:
  ```sql
  SELECT 
    host as "Host IP/Address", 
    count(*) as "Vulnerabilities Count"
  FROM vulnerabilities
  WHERE risk IN ('Critical', 'High', 'Medium')
    AND source_file IN (${source_file:sqlstring})
  GROUP BY host
  ORDER BY count(*) DESC
  LIMIT 15;
  ```

#### Panel C: Security Posture Trends (Time Series Line Graph)
Tracks historical trend lines of vulnerability counts over scanning days.
- **Visualization**: Time Series
- **SQL Query**:
  ```sql
  SELECT 
    date_trunc('day', ingested_at) as time,
    risk,
    count(*) as count
  FROM vulnerabilities
  WHERE source_file IN (${source_file:sqlstring})
  GROUP BY time, risk
  ORDER BY time;
  ```

#### Panel D: Granular Data Inspector (Table)
A searchable table showing specific plugin IDs, descriptions, and solutions.
- **Visualization**: Table
- **SQL Query**:
  ```sql
  SELECT 
    host as "Host",
    plugin_id as "Plugin ID",
    cve as "CVE",
    risk as "Severity",
    cvss_base_score as "CVSS Base Score",
    name as "Vulnerability Name",
    synopsis as "Synopsis",
    description as "Description",
    solution as "Solution",
    plugin_output as "Plugin Output"
  FROM vulnerabilities
  WHERE source_file IN (${source_file:sqlstring})
  ORDER BY cvss_base_score DESC NULLS LAST;
  ```

---

## Technical Design Features

If you are looking at the code for study or curious how the system is engineered:
- **Resilient Startup Loop**: Standard Docker depends_on only checks if a container is started, not if the database is actually ready to accept connections. We wrote a custom socket connection loop in `ingest.py` that polls the connection state and prevents the ingestion script from crashing on startup.
- **Auto-Initialization**: Schema creation and Grafana provisioning are handled entirely within the Python ingestion daemon container. On startup, the table and necessary indices are automatically created, and the Grafana datasource configuration is written to the shared volume dynamically. This is what enables the zero-download run route.
- **Dynamic Name Cleaning Engine**: Nessus exports sometimes name columns "Plugin ID", "Plugin_ID", or "pluginid". The parser uses regex to clean column names, forcing everything to lowercase, stripping special characters, and converting spaces to underscores. It then maps them dynamically to standard database headers.
- **Integrity Auditing**: Every file ingestion writes to `ingestion_audit.log`, verifying if the parsed CSV rows match the database written count. This provides an audit trail to guarantee that no data was dropped.
