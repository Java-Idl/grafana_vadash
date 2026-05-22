# Nessus Vulnerability Ingest Engine & Grafana Dashboard

This project is a containerized infrastructure that watches a host directory for Nessus security scanning reports (in CSV format), parses and cleans the data dynamically, persists it into a secured PostgreSQL database, and exposes it through Grafana.

---

## Service Architecture

- **PostgreSQL Database (`vadash_postgres`)**: An isolated, persistent PostgreSQL service initialized with standard security metrics schemas, customized configurations, and indexes.
- **Python Ingest Engine (`vadash_ingestion`)**: A lightweight container that watches the local `./scan_files` folder, detects new files, verifies that write locks are released, cleans headers, audits rows, and moves files to the archive.
- **Grafana Dashboard (`vadash_grafana`)**: Auto-provisioned to connect directly to the database over the secure container network on port `3000`.

---

## Quick Start Instructions

### Prerequisites
- Install **Docker** and **Docker Compose** on your host machine.

### Step 1: Initialize the Containers
From the root of this project workspace directory, run:
```bash
docker compose up -d --build
```
This command builds the custom ingestion image, initializes the PostgreSQL schema via `db_init.sql`, configures the network layer, and spawns the containers in detached mode.

### Step 2: Feed Vulnerability CSV Scans
1. Place your Nessus `.csv` scan files into the newly created `./scan_files` directory inside your workspace root.
2. The custom watcher will:
   - Recognize the new file within 5 seconds.
   - Wait 3 seconds to confirm file stability (to avoid parsing partial exports).
   - Dynamically clean headers, parse the rows, and insert them into the database.
   - Append data alignment audit stats directly to `./scan_files/ingestion_audit.log`.
   - Move the processed file to `./scan_files/archive/` (renamed with a timestamp to avoid naming conflicts).

### Step 3: View Ingestion Logs and Auditing
- To watch the ingestion service process files in real-time, run:
  ```bash
  docker compose logs -f ingestion
  ```
- Inspect `./scan_files/ingestion_audit.log` to confirm data alignment audits:
  ```text
  [2026-05-22 14:15:30] FILE: external_scan_results.csv | STATUS: SUCCESS | EXPECTED ROWS: 154 | INGESTED ROWS: 154
  ```

---

## Grafana Manual Dashboard Setup Guide

Grafana is automatically configured with a pre-connected PostgreSQL datasource. 

### Accessing Grafana
1. Open your browser and navigate to `http://localhost:3000`.
2. Log in with the default administrator credentials:
   - **Username**: `admin`
   - **Password**: `admin` (you will be prompted to change this upon first login).

---

### Step 1: Create a Dashboard Level Variable
To filter dashboard panels dynamically by the security scan filename:
1. In your dashboard, click **Dashboard Settings** (the gear icon in the top right).
2. Go to **Variables** > **Add variable**.
3. Set the following parameters:
   - **Name**: `source_file`
   - **Type**: `Query`
   - **Label**: `Scan File`
   - **Data source**: `PostgreSQL`
   - **Query**:
     ```sql
     SELECT DISTINCT source_file FROM vulnerabilities ORDER BY source_file DESC;
     ```
   - **Selection Options**: Enable **Multi-value** and **Include All option**.
4. Click **Apply**.

---

### Step 2: Add Panel Visualizations & Query Design

Create panels on your dashboard and copy-paste the SQL queries below:

#### Panel A: Vulnerability Distribution Metrics (Stat Panels)
Visualizes overall critical, high, medium, and low risk summaries as giant counter cards.
- **Visualization**: `Stat`
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
- **Configuration Tip**: Set the Stat Panel options to display `Value + Name` and apply color mappings (e.g., Critical: Red, High: Orange, Medium: Yellow, Low: Blue).

#### Panel B: Asset Exposure Mapping (Bar or Pie Chart)
Identifies the network addresses containing the highest volume of risk exposures.
- **Visualization**: `Bar Chart` or `Pie Chart`
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

#### Panel C: Vulnerability Posture Tracking (Time Series / Line Graph)
Tracks historical trend lines of vulnerability ingestion quantities over scanning periods.
- **Visualization**: `Time Series`
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
- **Configuration Tip**: Set graph type to line/bars. Grouping by `risk` will automatically draw distinct timeline lines for Critical, High, Medium, and Low trends over time.

#### Panel D: Granular Data Inspection (Table / Grid)
Provides a deep-dive searchable grid displaying vulnerability names, definitions, references, and solutions.
- **Visualization**: `Table`
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
- **Configuration Tip**: Enable search filtering inside Grafana column settings for rapid key-text lookup.

---

## Operations & Failure Recovery

| Category | Issue | Action / Resolution |
| --- | --- | --- |
| **Startup Sequence** | Ingest engine starts too early. | Custom built-in TCP check in `ingest.py` waits dynamically until PostgreSQL accepts ports. |
| **Permissions** | Docker mount cannot write logs/files. | Standard Windows-to-Linux path conversions are handled cleanly by Docker Compose. Ensure Docker Desktop has read/write permissions on the workspace directory. |
| **Network** | Network connection drops. | Automatic reconnect retry loop in Ingest Engine prevents crashes and logs exact exception states. |
| **Parsing Fails** | Bad CSV format. | Errant files are prefixed with `FAILED_` and moved immediately to `./scan_files/archive/` to prevent blockages, and logged in the audit trail. |
