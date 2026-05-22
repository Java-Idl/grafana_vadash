-- Create Vulnerability Master Table
CREATE TABLE IF NOT EXISTS vulnerabilities (
    id SERIAL PRIMARY KEY,
    plugin_id INTEGER,
    cve VARCHAR(100),
    cvss_base_score NUMERIC(3,1),
    risk VARCHAR(20),  -- e.g., Critical, High, Medium, Low, None
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

-- Optimize queries for Grafana Panels
CREATE INDEX IF NOT EXISTS idx_vulnerabilities_risk ON vulnerabilities(risk);
CREATE INDEX IF NOT EXISTS idx_vulnerabilities_host ON vulnerabilities(host);
CREATE INDEX IF NOT EXISTS idx_vulnerabilities_source_file ON vulnerabilities(source_file);
CREATE INDEX IF NOT EXISTS idx_vulnerabilities_ingested_at ON vulnerabilities(ingested_at);
