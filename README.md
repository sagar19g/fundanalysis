1. Environment Setup
Verify that Docker Desktop is running, navigate to the project root, and ensure a .env.dev file exists in the root directory:
Ini, TOML
APP_ENV=dev
LOG_LEVEL=INFO
DATABASE_URL=sqlite:////app/data/reference_data.db

2. Load Input Data
Place raw monthly fund CSV files into the host input directory:
data/external-funds/

3. Execution Commands
Run execution commands via Docker Compose based on your operational target:
Run Full Pipeline (Ingestion → Reconciliation → Performance):
Bash
docker compose up --build
Run Data Ingestion Only:
Bash
docker compose run --rm pipeline --task ingestion
Run Price Reconciliation Only:
Bash
docker compose run --rm pipeline --task reconciliation
Run Performance Analysis Only:
Bash
docker compose run --rm pipeline --task performance

4. Verify Outputs & Logs
Inspect Run Status & Logs:
Bash
docker logs financial_pipeline_dev
Locate Generated CSV Reports: Output reports are automatically written to your local Mac/host directory:
data/output/price_reconciliation.csv
data/output/best_performing_funds.csv