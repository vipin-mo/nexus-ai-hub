# NexusAI developer entry points. Run `make help`.
SHELL := /bin/bash
.DEFAULT_GOAL := help

PY        := .venv/bin/python
COMPOSE   := docker compose --env-file .env -f local_infra/docker-compose.yml
CPP_BUILD := core_engines/audio-processor-cpp/build
OLLAMA_MODELS := llama3:8b qwen2.5:3b nomic-embed-text

.PHONY: help setup env models test test-python test-java test-cpp lint eval eval-local train prompts \
        up down ps logs demo pipeline pipeline-local bench k8s-validate

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup:  ## create .venv, install Python deps, train the router, build the C++ binary
	python3.11 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-pipeline.txt -r requirements-dev.txt
	$(PY) -m ai_orchestrator.training.train_router
	cmake -S core_engines/audio-processor-cpp -B $(CPP_BUILD) -DCMAKE_BUILD_TYPE=Release
	cmake --build $(CPP_BUILD) -j

env:  ## create .env with random secrets (or add missing keys to an existing one)
	@if [ -f .env ]; then scripts/generate_env.sh --merge; else scripts/generate_env.sh; fi

models:  ## pull the Ollama models and the whisper.cpp model
	@for m in $(OLLAMA_MODELS); do ollama pull $$m; done
	scripts/download_whisper_model.sh base.en

test: test-python test-java test-cpp  ## all unit and integration tests

test-python:  ## Python unit tests (offline)
	$(PY) -m pytest

test-java:  ## needs Docker (Testcontainers)
	cd core_engines/gateway-service-java && mvn -B -q verify

test-cpp:  ## C++ build + ctest
	cmake --build $(CPP_BUILD) -j && ctest --test-dir $(CPP_BUILD) --output-on-failure

lint:  ## ruff + perl syntax check
	$(PY) -m ruff check ai_orchestrator evals tests scripts data_pipeline ui_analytics
	perl -c data_pipeline/scripts/parser.pl

eval:  ## offline evaluation + quality gate (what CI runs; free, deterministic)
	$(PY) -m evals.run_evals --profile offline --gate

eval-local:  ## full evaluation on local Ollama models with an LLM judge (free, ~5 min)
	$(PY) -m evals.run_evals --profile local --judge ollama --mlflow-uri http://localhost:5001 --gate

train:  ## retrain the intent router and register it in MLflow (champion/challenger)
	$(PY) -m ai_orchestrator.training.train_router --mlflow-uri http://localhost:5001

prompts:  ## register prompts.py in the MLflow Prompt Registry (@production)
	$(PY) -m ai_orchestrator.prompt_registry --mlflow-uri http://localhost:5001

up:  ## start the stack (Postgres, Mongo, MLflow, orchestrator, gateway, audio, dashboard)
	$(COMPOSE) up -d --build --wait
	@echo "dashboard http://localhost:8501 | gateway http://localhost:8080 | MLflow http://localhost:5001"

down:  ## stop the stack (data volumes are kept; add -v yourself to wipe them)
	$(COMPOSE) down

ps:  ## stack status
	$(COMPOSE) ps

logs:  ## follow stack logs
	$(COMPOSE) logs -f --tail=100

demo:  ## send sample questions and the sample WAVs through the running stack
	scripts/demo.sh

pipeline:  ## run the batch log pipeline in its container (LINES=200000 make pipeline)
	$(COMPOSE) --profile batch run --rm -e LINES=$${LINES:-100000} -e REGENERATE=1 pipeline

pipeline-local:  ## run the batch log pipeline on the host (.venv, Java 17, Perl)
	REGENERATE=1 LINES=$${LINES:-100000} bash data_pipeline/run_pipeline.sh

bench:  ## reproduce the numbers in BENCHMARKS.md (stack must be up)
	$(PY) scripts/benchmark.py

k8s-validate:  ## render the Kubernetes manifests and validate them against the API schemas
	kubectl kustomize local_infra/k8s > /tmp/nexus-k8s.yaml && kubectl apply --dry-run=client -f /tmp/nexus-k8s.yaml
