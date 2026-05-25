# Nessus Parser and Grafana Dashboard

This is a simple project to help you parse Nessus vulnerability scans (CSV format), store them in a database, and view them on a Grafana dashboard. If you have ever had to manually sort through Nessus scan exports, you know it can get tedious. This setup imports the data automatically and configures a basic Grafana connection so you can start analyzing your scans right away.

---

## Running with Docker Compose (No Repo Download Needed)

You do not need to download this repository to run this application. You can set up the entire stack on any machine running Docker by copying the following files into a folder:

### 1. Create a Project Folder
Create a folder on your computer, for example, `nessus-parser`.

### 2. Create the Configuration Files
Inside that folder, create the following two files:

#### Create `docker-compose.yml`
Copy and paste this content into a file named `docker-compose.yml`:

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

### 3. Start the Application
Open a terminal in your folder and run:

```bash
docker compose up -d
```

### 4. Import a Nessus CSV
1. Once the services start, you will see a new `./scan_files` folder in your project directory.
2. Drag and drop any Nessus CSV scan export into the `./scan_files` folder.
3. The parser script will automatically detect the file within a few seconds, wait briefly to ensure it is not still copying, clean the column headers, and import the records into the database.
4. The imported CSV will then be moved to `./scan_files/archive/` with a timestamp added to its filename so you do not accidentally overwrite old scans.

---

## Alternative Setup: Cloning the Repository

If you want to view the source code or build the images yourself, you can clone the repository:

### Option A: Clone and Run
```bash
# Clone the repository
git clone https://github.com/Java-Idl/grafana_vadash.git

# Go into the project directory
cd grafana_vadash

# Start the services
docker compose up -d
```

### Option B: Build Locally
If you want to modify the Python parser script (`ingest.py`) or the Dockerfile, you can build the image on your machine:

```bash
# Build the parser image locally
docker build -t galahanorg/nessus-ingester:latest ./ingestion

# Start the services with your local build
docker compose up -d
```

---

## How It Works

The application runs three separate containers:

1. **PostgreSQL**: Stores the vulnerability records in a table named `vulnerabilities`.
2. **Python Parser Script**: Monitors the folder, cleans the columns, inserts the CSV data into PostgreSQL, and moves the finished file to the archive. On startup, it automatically creates the database table, indexes, and the Grafana data source configuration.
3. **Grafana**: Pre-configured to connect to the database. It shares a volume with the Python parser to read the database connection settings on startup.

---

## Setting Up Your Grafana Dashboard

Grafana connects to your database automatically on startup. Here is how to configure a simple dashboard:

1. Open your browser and go to `http://localhost:3000`.
2. Log in using **Username: admin / Password: admin** (you will be asked to set a new password on your first login).
3. Create a new dashboard.

### Step 1: Create a Scan File Filter
Creating a dashboard variable allows you to filter your panels by specific scan files:
1. Click the Gear icon (Dashboard settings) in the top-right corner.
2. Select **Variables** on the left and click **Add variable**.
3. Fill out the following:
   - **Name**: source_file
   - **Type**: Query
   - **Label**: Scan File
   - **Data source**: PostgreSQL
   - **Query**:
     ```sql
     SELECT DISTINCT source_file FROM vulnerabilities ORDER BY source_file DESC;
     ```
   - **Selection Options**: Enable both **Multi-value** and **Include All option**.
4. Click **Apply**. You will now see a dropdown menu at the top of your dashboard.

---

### Step 2: Add Panels with SQL Queries

Click **Add Panel** > **Add a new panel** and use these SQL queries:

#### Panel A: Severity Levels (Stat Panel)
Shows a simple count of Critical, High, Medium, and Low vulnerabilities.
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
- *Tip*: Set the panel configuration to show "Value + Name" and assign color overrides (like red for Critical and orange for High).

#### Panel B: Most Vulnerable Hosts (Bar Chart)
Shows the top 15 hosts with the most Critical, High, or Medium severity issues.
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

#### Panel C: Vulnerability Trends (Time Series Graph)
Tracks the count of vulnerabilities over time based on when the scans were imported.
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

#### Panel D: Detailed Records List (Table)
A table showing specific vulnerability details, including the plugin ID, host, description, and solution.
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

## Practical Implementation Details

Here are some of the design decisions implemented in the code:

*   **Database Startup Wait**: Because containers can start at slightly different times, the Python script uses a connection loop. It will poll the database port and wait until PostgreSQL is ready before starting the monitoring loop. This prevents the script from crashing on startup.
*   **Column Name Standardization**: Nessus reports do not always use the exact same column names (for example, "Plugin ID" vs "plugin_id"). The script converts headers to lowercase, replaces spaces with underscores, and maps them to standard database fields dynamically.
*   **Automatic Setup**: The PostgreSQL table schema, indexes, and Grafana datasource file are created programmatically by the Python container. This makes it possible to run the entire setup using only a single Docker Compose file.
*   **Audit Logging**: The script writes a record to `./scan_files/ingestion_audit.log` showing the filename, the number of rows in the CSV, and the number of rows successfully saved to the database. This helps you verify that all data was imported correctly.
