#!/usr/bin/env bash

# ==============================================================================
# NexusAI Local Stack Integration & Lifecycle Orchestrator
# ==============================================================================

set -euo pipefail

# Visual terminal coloring configurations
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }
log_success() { echo -e "${GREEN}[SUCCESS] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }
log_warn() { echo -e "${YELLOW}[WARN] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }
log_error() { echo -e "${RED}[ERROR] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }

cleanup_stack() {
    log_warn "Intercepted shutdown indicator. Tearing down local daemons and background tasks safely..."
    # Terminate background streaming servers and streamlit web panels if active
    jobs -p | xargs kill -9 2>/dev/null || true
    log_success "Background tracking loops unlinked. Stack execution halted."
}
trap cleanup_stack EXIT

st_title() {
    echo -e "${CYAN}========================================================================"
    echo -e "       NEXUSAI INTEGRATED SYSTEM EXECUTION RUNNER"
    echo -e "========================================================================${NC}"
}

st_title

# ------------------------------------------------------------------------------
# STEP 1: Verification of Prerequisite Host Environments
# ------------------------------------------------------------------------------
log_info "Verifying required environment runtimes and local installations..."
for cmd in docker cmake perl python3 java ollama; do
    if ! command -v "$cmd" &> /dev/null; then
        log_error "Missing required environment utility target command: $cmd"
        exit 1
    fi
done
log_success "All native compilers and toolchains located on the host."

# Check for .env profile file presence
if [ ! -f ".env" ]; then
    log_error ".env profiles file missing at project root context path layout location."
    exit 1
fi
source .env

# Verify Ollama service is active on the host machine
log_info "Checking local Ollama inference server availability..."
if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    log_error "Ollama is not running on your host machine."
    log_warn "Please start the Ollama application on your Mac/host and try again."
    exit 1
else
    log_success "Ollama daemon is active on the host machine."
fi

# Verify specific local model availability
REQUIRED_MODEL="llama3.2:1b"
if ! curl -s http://localhost:11434/api/tags | grep -q "$REQUIRED_MODEL"; then
    log_warn "Required model '$REQUIRED_MODEL' not found in local Ollama storage."
    log_info "Pulling '$REQUIRED_MODEL' now..."
    ollama pull "$REQUIRED_MODEL"
    log_success "Successfully pulled '$REQUIRED_MODEL'."
else
    log_success "Found verified Ollama model: $REQUIRED_MODEL"
fi

# ------------------------------------------------------------------------------
# STEP 2: Compile High-Performance Native Components
# ------------------------------------------------------------------------------
log_info "Compiling native high-performance core subsystems..."

# C++ Core Binary Construction Check
log_info "Building C++ Audio Streaming Frame Processing Engine..."
mkdir -p core_engines/audio-processor-cpp/build
(
    cd core_engines/audio-processor-cpp/build
    cmake .. > /dev/null
    make > /dev/null
)
log_success "C++ Ingestion Node compiled successfully."

# Java Maven Assembly Check
log_info "Compiling and packaging Java Spring Boot Router Core Middleware..."
(
    cd core_engines/gateway-service-java
    if [ -f "./mvnw" ]; then
        ./mvnw -B clean package -DskipTests > /dev/null
    else
        mvn -B clean package -DskipTests > /dev/null
    fi
)
log_success "Java Enterprise Gateway .JAR package assembled."

# ------------------------------------------------------------------------------
# STEP 3: Spin Up Docker Isolated Service Grid Mesh
# ------------------------------------------------------------------------------
log_info "Provisioning background databases and MLOps storage container mesh..."
(
    cd local_infra
    docker compose down -v 2>/dev/null || true
    docker compose up -d --build --wait postgres mongodb mlflow
)
log_success "PostgreSQL, MongoDB, and MLflow tracking servers successfully online."

# ------------------------------------------------------------------------------
# STEP 4: Initialize Python Workspace Environment & Execute Verification
# ------------------------------------------------------------------------------
log_info "Synchronizing python framework matrices and local virtual networks..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip &> /dev/null
log_info "Installing framework dependencies from requirements.txt matrix..."
pip install -r requirements.txt &> /dev/null
log_success "Python package ecosystem active."

log_info "Executing local test matrix to verify core algorithm validation gates..."
python3 -m unittest tests/unit/test_nexus_system_wide.py

log_info "Running AI Prompt Evaluation Suite to track model regression accuracy..."
python3 tests/unit/ai_eval_suite.py
log_success "All code logic verification checks and prompt regression scoring completed."

# ------------------------------------------------------------------------------
# STEP 5: Run Data Cleaning, PII Masking, and Big Data Batch Transforms
# ------------------------------------------------------------------------------
log_info "Triggering data preparation workflows and warehouse synchronization..."

# Run Perl sanitization string tokenizer
log_info "Executing Perl script regex-based data parsing over application logs..."
perl data_pipeline/scripts/parser.pl

# Run PySpark aggregate compilation job layers
log_info "Executing local PySpark single-node KPI batch summaries tracking jobs..."
python3 data_pipeline/scripts/etl_spark_job.py
log_success "Analytical DuckDB database tables seeded and ready."

# ------------------------------------------------------------------------------
# STEP 6: Execute Background Execution Servers and Frontends
# ------------------------------------------------------------------------------
log_info "Launching service daemons and background networking loops..."

# 1. Boot Python LangGraph Orchestrator (Override DB URIs to localhost)
log_info "Starting Python LangGraph AI WebSocket server daemon on port 8765..."
export MONGO_URI="mongodb://nexus_admin:nexus_secure_password@localhost:27017/nexus_ai_ops?authSource=admin"
export MLFLOW_TRACKING_URI="http://localhost:5001"
python3 ai_orchestrator/agents/streaming_server.py > /dev/null 2>&1 &
sleep 2 # Let the loop attach cleanly to host network addresses

# 2. Launch Java Gateway Endpoint (Override DNS aliases to localhost)
log_info "Booting Enterprise Java Spring Boot Broker Routing Server on port 8080..."
export DB_HOST="localhost"
export ORCHESTRATOR_HOST="localhost"
java -jar core_engines/gateway-service-java/target/gateway-service-1.0.0.jar > /dev/null 2>&1 &
sleep 5 # Allow Spring contexts to complete database validation matches

# 3. Launch the Compiled C++ Audio Ingestion Node
log_info "Booting High-Performance C++ Audio PCM Processor..."
export GATEWAY_URL="http://localhost:8080/api/v1/gateway/dispatch"

./core_engines/audio-processor-cpp/build/audio_processor > /dev/null 2>&1 &
sleep 2

log_success "All network systems online. Launching operational control panel dashboard..."
log_warn "Keep terminal workspace open to maintain active system tracing logging threads."
log_info "Access your executive BI reporting panel at: http://localhost:8501"

# Launch Streamlit web dashboard natively
streamlit run ui_analytics/app.py
