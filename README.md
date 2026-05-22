# Nessus Ingest and Grafana Dashboard Pipeline

If you have ever done security audits, vulnerability scans, or coursework involving network security, you probably know how painful it is to work with raw scan reports. Nessus generates massive CSV files that are tough to read, columns often change names between versions, and tracking your network's overall security posture over time feels almost impossible without a dedicated tool. 

This project solves that by setting up a fully automated, multi-container pipeline that parses your Nessus CSV exports, structures them inside a database, and visualizes them on a live Grafana dashboard. It is designed to be lightweight, self-healing, and extremely simple to run.

---

## Quick Run: Zero-Download Setup (Docker Compose Only)

You do not need to download this repository or install any programming tools to run this application. If you just want to spin up the pipeline on your computer using Docker, follow these steps:

### 1. Create a Project Folder
Create a new directory on your machine where you want the project to live, for example, `nessus-pipeline`.

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

### 3. Spin Up the Containers
Open your terminal in your `nessus-pipeline` folder and start the services:

```bash
docker compose up -d
```

### 4. Drop in a Nessus CSV File
1. Once the containers start, Docker will automatically create a `./scan_files` folder in your project directory.
2. Drag and drop any Nessus CSV report directly into the `./scan_files` folder.
3. The ingestion daemon will:
   - Detect the file within 5 seconds.
   - Wait 3 seconds to ensure the file is completely written and stable.
   - Parse and clean the columns, write the data into the database, and write an audit record to `./scan_files/ingestion_audit.log`.
   - Safely move the file into `./scan_files/archive/` (adding a timestamp to prevent naming conflicts).

---

## Alternative Setup: Cloning the Repository

If you want to view the source code, play around with the scripts, or build the images yourself:

### Option A: Standard Repository Launch
Clone the repo and run compose directly:

```bash
# Clone the repository
git clone https://github.com/Java-Idl/grafana_vadash.git

# Navigate into the project folder
cd grafana_vadash

# Start the stack
docker compose up -d
```

### Option B: Local Development & Rebuilding
If you want to modify the parser script (`ingest.py`) or customize the Dockerfile, you can build your changes into a local image:

```bash
# Build the parser image locally
docker build -t galahanorg/nessus-ingester:latest ./ingestion

# Spin up the containers using your newly compiled image
docker compose up -d
```

---

## Under the Hood: How the Pipeline Works

The stack consists of three services running inside an isolated virtual network:

1. **PostgreSQL (vadash_postgres)**: The storage layer. It maintains the database state and holds all the parsed vulnerability entries.
2. **Python Ingest Daemon (vadash_ingestion)**: The brain of the operation. This container runs a persistent background script that watches the scan folder. It is designed to be fully self-healing: on startup, it automatically constructs the SQL table schema and indexing, and dynamic provisioning directories without requiring any manual SQL execution.
3. **Grafana (vadash_grafana)**: The visualization layer. It comes pre-provisioned via a shared Docker volume, meaning it establishes its connection to PostgreSQL automatically at boot using the credentials in your `.env` file. You do not have to configure anything inside the browser.

---

## Setting Up Your Grafana Dashboard

Grafana is already connected to your PostgreSQL database. Here is how to build a dynamic security dashboard:

1. Open your browser and go to `http://localhost:3000`.
2. Log in with **Username: admin / Password: admin** (you will be prompted to set a new password on your first login).
3. Create a new dashboard.

### Step 1: Add a Dynamic Scan File Variable
To avoid mixing up different scans, we will create a dropdown menu so you can look at specific files individually or all at once:
1. Click the Gear icon (Dashboard settings) in the top-right corner.
2. Go to **Variables** on the left menu and click **Add variable**.
3. Set these fields:
   - **Name**: source_file
   - **Type**: Query
   - **Label**: Scan File
   - **Data source**: PostgreSQL
   - **Query**:
     ```sql
     SELECT DISTINCT source_file FROM vulnerabilities ORDER BY source_file DESC;
     ```
   - **Selection Options**: Enable **Multi-value** and **Include All option**.
4. Click **Apply**. A dropdown menu will appear at the top of your dashboard.

---

### Step 2: Build the Panels with SQL Queries

Click **Add Panel** > **Add a new panel** and paste these queries to create your visualizations:

#### Panel A: Risk Distribution (Stat Panels)
Displays a quick count of Critical, High, Medium, and Low issues in the selected scans.
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
- *Configuration Tip*: Set the panel settings to show "Value + Name" and apply color overrides (Red for Critical, Orange for High, Yellow for Medium).

#### Panel B: Host Exposure Density (Bar Chart)
Lists the top 15 most vulnerable machines or IPs on your network.
- **Visualization**: Bar Chart
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

#### Panel C: Security Posture Trends (Time Series Graph)
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
A detailed, searchable data table showing specific plugins, descriptions, and solutions.
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

## Cool Engineering Details (Perfect for Class Projects!)

If you are using this code as part of a university project, lab, or report, here are the main engineering details you should highlight:

*   **Resilient Startup Waiting Loop**: Standard Docker Compose checks if containers are started, not if they are actually ready to accept connections. We engineered a socket-polling retry loop in `ingest.py` that waits until the PostgreSQL database is fully online before allowing the ingestion daemon to start monitoring. This avoids container crashes on boot.
*   **Dynamic Column Normalization**: Nessus report formats can vary, sometimes naming columns "Plugin ID", "Plugin_ID", or "pluginid". The Python parser uses regular expressions to strip spaces, force lowercase, and standardize headers dynamically, mapping them to the correct database schema out-of-the-box.
*   **Zero-Config Schema and Dashboard Provisioning**: To achieve the zero-download target, schema creation (`CREATE TABLE IF NOT EXISTS`) and Grafana connection setups are handled dynamically by the Python service on boot. This completely removes the need to maintain host SQL scripts or manual credential steps.
*   **Auditing and Integrity Log**: Every processed file writes a line to `./scan_files/ingestion_audit.log`, verifying the expected CSV row counts against the successful inserts in the database. This ensures complete data integrity.
