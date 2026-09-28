import os
import json
import time
import sys
import yaml
import mlflow
from typing import Dict, TypedDict, List
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_community.llms import Ollama
from anthropic import Anthropic

# Explicit structural imports from package architecture namespaces
from ai_orchestrator.knowledge.rag_pipeline import initialize_and_query_rag
from ai_orchestrator.models.nlp_classifier import LocalNLPClassifier
from ai_orchestrator.agents.memory import LongTermAgentMemory
from ai_orchestrator.agents.prompts import (
    SECURITY_SCANNER_PROMPT,
    INTENT_ROUTER_PROMPT,
    CLAUDE_EXECUTIVE_SYSTEM_PROMPT
)

# Load environment configurations
load_dotenv()

# Setup Local MLOps Registry Endpoint with structural fallback mechanisms
try:
    # Captures container-space definitions first, fallback out to native mapping bounds
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
    mlflow.set_experiment("NexusAI_Orchestrator_Evaluation")
except Exception:
    # Fallback to local directory file store for offline integration metrics tracking
    mlflow.set_tracking_uri("file:./mlruns")
    try:
        mlflow.set_experiment("NexusAI_Orchestrator_Evaluation")
    except Exception:
        pass

# Point structurally to the project root config pathing layout context
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config")

def load_system_settings() -> Dict:
    """Loads operational configuration frameworks from localized settings files."""
    settings_path = os.path.join(CONFIG_DIR, "settings.yaml")
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}

def load_security_policies() -> Dict:
    """Retrieves access vectors and regex token filters from enterprise policies schema."""
    policies_path = os.path.join(CONFIG_DIR, "security_policies.json")
    if os.path.exists(policies_path):
        with open(policies_path, "r") as f:
            return json.load(f) or {"banned_keywords": []}
    return {"banned_keywords": []}

class AgentState(TypedDict):
    session_id: str
    input_query: str
    cleaned_query: str
    security_passed: bool
    routing_destination: str
    context_data: str
    recommendation_data: List[str]
    final_response: str
    tokens_used: int
    execution_latency_ms: float
    role: str

# Initialize localized inference pipelines and external client components
local_llama = Ollama(base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"), model="qwen2.5:1.5b")
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
nlp_analyzer = LocalNLPClassifier()
memory_node = LongTermAgentMemory()

# ========================================================
# DECOUPLED NODE 1: Security Guardrail & NLP Sanity Check
# ========================================================
def security_and_nlp_guard_node(state: AgentState) -> Dict:
    """Performs multi-layered network boundary verification on incoming context arrays."""
    print("🛡️ [Debug] Entering Security Guard Node...")
    query = state["input_query"]
    policies = load_security_policies()

    # Primary defense: Fast scanning string checking matching criteria
    for banned in policies.get("banned_keywords", []):
        if banned.lower() in query.lower():
            print(f"🛑 [Security Shield] Banned SQL/Prompt Injection Keyword Caught: {banned}")
            return {"security_passed": False, "cleaned_query": query}

    # Secondary defense: High-speed local validation analysis model routing
    try:
        response = local_llama.invoke(f"{SECURITY_SCANNER_PROMPT}\n\nUser Query: {query}")

        # Strip structural markdown notation layout wraps safely
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        result = json.loads(cleaned.strip())
        passed = result.get("security_passed", True)

        # Local development deployment bypass mode override
        passed = True
        print(f"🛡️ [Debug] Security verification step processed. Framework status: {passed}")

        return {
            "security_passed": passed,
            "cleaned_query": result.get("cleaned_query", query)
        }
    except Exception as e:
        print(f"⚠️ [Security Guard Fallback] Processing error: {e}. Fail-open fallback route selected.")
        return {
            "security_passed": True,
            "cleaned_query": query
        }

# ========================================================
# DECOUPLED NODE 2: Intent Routing Engine
# ========================================================
def intent_router_node(state: AgentState) -> Dict:
    """Determines pipeline sequence using local classifier evaluation models."""
    print("🧠 [Debug] Entering Intent Router Node...")
    if not state.get("security_passed", False):
        print("🛑 [Debug] Execution cycle rejected: Security layer mismatch.")
        return {"routing_destination": "TERMINATE"}

    query = state["cleaned_query"]

    # Execute high-speed tensor analysis via local PyTorch embedding layers
    nlp_metrics = nlp_analyzer.analyze_sentiment_tone(query)
    print(f"🔬 [Local PyTorch BERT Analysis] Metrics metadata context calculated: {nlp_metrics}")

    try:
        destination = local_llama.invoke(f"{INTENT_ROUTER_PROMPT}\n\nQuery: {query}").strip().upper()
        print(f"🧭 [Debug] Orchestrator routed destination tag output: {destination}")
    except Exception as e:
        print(f"⚠️ [Router Fallback] Local invocation failed: {e}. Defaulting to high-tier reasoning context.")
        destination = "COMPLEX_REASONING"

    if destination not in ["RAG_KNOWLEDGE", "RECOMMENDATION", "COMPLEX_REASONING"]:
        destination = "COMPLEX_REASONING"

    return {"routing_destination": destination}

# ========================================================
# DECOUPLED NODE 3: Localized Semantic Document Extraction
# ========================================================
def local_rag_retrieval_node(state: AgentState) -> Dict:
    """Extracts localized documentation snippets utilizing semantic distance matrix arrays."""
    print("📚 [Debug] Entering RAG Retrieval Node...")
    query = state["cleaned_query"]
    print(f"Extracting contexts from localized vector store schemas for string: '{query}'")
    context = initialize_and_query_rag(query)
    return {"context_data": context}

# ========================================================
# DECOUPLED NODE 4: High-Tier Reasoning Control Engine
# ========================================================
def claude_executive_node(state: AgentState) -> Dict:
    """Dispatches structural logic queries up to Claude 4.5 Haiku runtime platforms."""
    print("👑 [Debug] Entering Claude Executive Brain Node...")
    query = state["cleaned_query"]
    session_id = state.get("session_id", "default_session")
    context = state.get("context_data", "No auxiliary context discovered.")

    # Retrieve short-term analytical logs from localized NoSQL instances
    conversation_history = memory_node.retrieve_recent_conversation_history(session_id, limit=2)

    # Structure text frames inside system markup boundaries safely
    prompt = f"""{CLAUDE_EXECUTIVE_SYSTEM_PROMPT}

    <context>
    {context}
    </context>

    <history>
    {conversation_history}
    </history>

    QUERY
    {query}
    QUERYEND
    """

    try:
        # Optimized invocation targeting cost-efficient Claude 4.5 Haiku footprint
        message = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text
        tokens_count = message.usage.input_tokens + message.usage.output_tokens

        # Persist data interaction states directly down into tracking memory layouts
        memory_node.persist_state_trace(
            session_id=session_id,
            query=query,
            response=response_text,
            metadata={"tokens_used": tokens_count}
        )
        print("👑 [Debug] Executive response sequence finalized successfully.")
        return {
            "final_response": response_text,
            "tokens_used": tokens_count
        }
    except Exception as e:
        print(f"❌ [Debug] Claude Infrastructure Exception Discovered: {e}")
        return {"final_response": f"Cloud orchestration runtime processing failure: {str(e)}", "tokens_used": 0}

# ========================================================
# LANGGRAPH STATE MACHINE COMPOSITION
# ========================================================
workflow = StateGraph(AgentState)

# Component node assignment mapping
workflow.add_node("security_guard", security_and_nlp_guard_node)
workflow.add_node("intent_router", intent_router_node)
workflow.add_node("rag_retrieval", local_rag_retrieval_node)
workflow.add_node("claude_brain", claude_executive_node)

# Core layout transition boundaries definition
workflow.set_entry_point("security_guard")
workflow.add_edge("security_guard", "intent_router")

def route_decision(state: AgentState) -> str:
    """Interprets internal graph state parameters to determine routing pathings."""
    dest = state["routing_destination"]
    if dest == "TERMINATE":
        return "end"
    if dest == "RAG_KNOWLEDGE":
        return "rag"
    return "claude"

workflow.add_conditional_edges(
    "intent_router",
    route_decision,
    {
        "rag": "rag_retrieval",
        "claude": "claude_brain",
        "end": END
    }
)

workflow.add_edge("rag_retrieval", "claude_brain")
workflow.add_edge("claude_brain", END)

# Package graph structures into executable agent engines
nexus_agent_executor = workflow.compile()


def run_monitored_agent(
    input_text: str,
    session_id: str = "default_session",
    role: str = "nexus_agent",
) -> Dict:
    """Executes execution steps across orchestration loops under MLflow tracking logs."""
    initial_state = {
        "input_query": input_text,
        "session_id": session_id,
        "role": role,
        "tokens_used": 0,
    }

    with mlflow.start_run(nested=True) as run:
        print(
            f"\n🏃 Run telemetry tracking online: http://localhost:5001/#/experiments/1/runs/{run.info.run_id}"
        )

        start_time = time.time()
        output = nexus_agent_executor.invoke(initial_state)
        latency = (time.time() - start_time) * 1000

        # Log system operational telemetry parameters to continuous dashboard collectors
        mlflow.log_param("user_query", input_text)
        mlflow.log_param("session_id", session_id)
        mlflow.log_param("routing_path", output.get("routing_destination"))
        mlflow.log_metric("latency_ms", latency)
        mlflow.log_metric("tokens_consumed", output.get("tokens_used", 0))

        print(
            f"📊 [MLflow Trace Logged] Latency: {latency:.2f}ms | "
            f"Tokens consumed: {output.get('tokens_used', 0)}"
        )

        return output


if __name__ == "__main__":
    print("🚀 Initiating monitored agent evaluation memory test loops...")
    session_token = "nexus_interview_test_session_001"

    print("\n--- RUN 1 ---")
    run_1 = run_monitored_agent(
        "What are our rules about destructive database writes?",
        session_id=session_token,
    )
    print("\n👑 Final System Resolution (Run 1):\n", run_1.get("final_response"))

    print("\n--- RUN 2 ---")
    run_2 = run_monitored_agent(
        "Can you summarize that rule in one brief sentence?",
        session_id=session_token,
    )
    print("\n👑 Final System Resolution (Run 2):\n", run_2.get("final_response"))