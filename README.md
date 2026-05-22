# Nessus Ingest & Grafana Dashboard

Hey there! This is a clean, multi-container pipeline built to automate the parsing, storage, and visualization of Nessus vulnerability reports (CSV exports). 

If you've ever tried manually formatting and copying vulnerability scan data, you know it is a headache. Column names change slightly, files overwrite each other, and tracking security trends over time is painful. This project automates the entire flow using Docker Compose, Python, PostgreSQL, and Grafana.

---

## How It Works (The Architecture)

Here is a quick overview of how the three containers work together:

1. **PostgreSQL Database (vadash_postgres)**: The storage layer. It initializes itself automatically using a custom schema (db_init.sql) with predefined tables and indexes optimized for security dashboards.
2. **Python Ingest Daemon (vadash_ingestion)**: The "brain" of the operation. This container actively watches a folder on your computer. When you drop a Nessus CSV in, it handles contention checks (waiting for files to finish copying), cleans up headers dynamically, parses the records, commits them to the database, audits the row count, and archives the file.
3. **Grafana Visualization (vadash_grafana)**: The presentation layer. It comes pre-provisioned, meaning it connects to the database automatically on startup so you don't have to manually configure usernames and passwords in the browser.

---

## Getting Started

### 1. Prerequisites
Make sure you have Docker Desktop installed and running on your computer.

### 2. Booting Up the Stack
Open a terminal in the root folder of this project and run:
```bash
docker compose up -d --build
```
This tells Docker to build our custom Python ingestion container, establish a private isolated bridge network, start PostgreSQL, and expose Grafana at http://localhost:3000.

### 3. Feeding a CSV Scan
1. Drag and drop any Nessus CSV report into the newly created ./scan_files folder in the project root.
2. Under the hood, the Python daemon will:
   - Detect the file within 5 seconds.
   - Wait 3 seconds and double-check that the file size has stopped growing (this makes sure it doesn't parse a half-written file!).
   - Normalize column names dynamically, insert the data, and append status to ./scan_files/ingestion_audit.log.
   - Rename and move the file into ./scan_files/archive/ (adding a timestamp to prevent naming collisions).

---

## Building Your Grafana Dashboard (The Fun Part!)

Grafana is already connected to your PostgreSQL database out of the box. 

1. Go to http://localhost:3000 in your web browser.
2. Log in with Username: admin / Password: admin (it will ask you to change this).
3. Create a new dashboard.

### Step 1: Set up a Dynamic File Filter (Variable)
Before making panels, let's create a dropdown filter so you can isolate specific scans:
- In your dashboard, click the Gear Icon (Dashboard settings) in the top-right corner.
- Go to Variables > Add variable.
- Configure these settings:
  - **Name**: source_file
  - **Type**: Query
  - **Label**: Scan File
  - **Data source**: PostgreSQL
  - **Query**: 
    ```sql
    SELECT DISTINCT source_file FROM vulnerabilities ORDER BY source_file DESC;
    ```
  - **Selection Options**: Turn on Multi-value and Include All option.
- Click Apply. You will now have a neat dropdown menu at the top of your dashboard.

---

### Step 2: Copy-Paste SQL Queries for Your Panels

Now, click Add Panel > Add a new panel and use these queries to build your visualizations:

#### Panel A: Risk Distribution (Stat Panels)
Shows you a quick count of Critical, High, Medium, and Low issues in the selected scans.
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
- *Tip*: Set the panel settings to show "Value + Name" and apply color overrides (e.g. Red for Critical, Orange for High, Yellow for Medium).

#### Panel B: Host Exposure Density (Bar Chart)
Finds the top 15 most vulnerable computers/IPs on your network.
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
A searchable table at the bottom of your dashboard showing specific plugin IDs, descriptions, and solutions.
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

## Behind the Scenes (Cool Engineering Details)

If you're looking at the code for class or curious how it works:
- **Resilient Startup Loop**: Standard Docker depends_on only checks if a container is started, not if the database is actually ready to accept connections. We wrote a custom socket retry loop in Python (ingest.py) that checks connection states and prevents the ingestion script from crashing on start.
- **Dynamic Name Cleaning Engine**: Nessus exports sometimes name columns Plugin ID or Plugin_ID or pluginid. The parser uses regex to clean column names, forcing everything to lowercase, stripping special characters, and converting spaces to underscores. It then maps them dynamically to standard database headers.
- **Integrity Auditing**: Every file ingestion writes to ./scan_files/ingestion_audit.log, verifying if the parsed CSV rows match the database written count. It is a quick way to double-check that no data was dropped!

Have fun scanning and visualizing! Let me know if you run into any issues.
