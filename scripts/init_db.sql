CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS chart_of_accounts (
  account_code VARCHAR PRIMARY KEY,
  account_name VARCHAR NOT NULL,
  category VARCHAR NOT NULL,
  sub_category VARCHAR,
  normal_balance VARCHAR
);

CREATE TABLE IF NOT EXISTS journal_entries (
  entry_id SERIAL PRIMARY KEY,
  entry_date DATE NOT NULL,
  account_code VARCHAR REFERENCES chart_of_accounts,
  description VARCHAR,
  debit NUMERIC(15,2) DEFAULT 0,
  credit NUMERIC(15,2) DEFAULT 0,
  entity VARCHAR DEFAULT 'ACME Corp',
  period_id INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reporting_periods (
  period_id SERIAL PRIMARY KEY,
  period_name VARCHAR NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  status VARCHAR DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS report_jobs (
  job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  period_id INTEGER REFERENCES reporting_periods,
  status VARCHAR DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  s3_url VARCHAR,
  error_message VARCHAR
);

CREATE TABLE IF NOT EXISTS audit_log (
  log_id SERIAL PRIMARY KEY,
  job_id UUID REFERENCES report_jobs,
  event VARCHAR NOT NULL,
  prompt_used TEXT,
  model_version VARCHAR,
  computed_values JSONB,
  timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS regulation_embeddings (
  id SERIAL PRIMARY KEY,
  rule_id VARCHAR,
  rule_text TEXT,
  source VARCHAR,
  embedding vector(1536),
  created_at TIMESTAMP DEFAULT NOW()
);
