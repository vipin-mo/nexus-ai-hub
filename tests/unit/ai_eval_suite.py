import os
import sys
import time
import mlflow
from typing import Dict, List

# Map paths targeting the absolute workspace root to safely invoke the agent state graph framework packages
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ai_orchestrator.agents.graph import run_monitored_agent

class AIEvaluationSuite:
    def __init__(self):
        # Setup local MLOps environment mapping vectors
        try:
            mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
            mlflow.set_experiment("NexusAI_Regression_Guardrails")
        except Exception:
            mlflow.set_tracking_uri("file:./mlruns")
            try:
                mlflow.set_experiment("NexusAI_Regression_Guardrails")
            except Exception:
                pass

        # Define Ground Truth Evaluation Dataset reflecting localized knowledge criteria
        self.eval_dataset: List[Dict[str, str]] = [
            {
                "query": "What are our rules about destructive database writes?",
                "expected_keyword": "Human-In-The-Loop",
                "category": "Security_Protocols"
            },
            {
                "query": "Where must relational customer metadata reside?",
                "expected_keyword": "PostgreSQL",
                "category": "Data_Storage"
            }
        ]

    def execute_regression_test_suite(self):
        """Iterates through test cases, scores performance, and logs evaluation metrics to MLflow."""
        print("📊 [AI Eval Suite] Launching regression test suite against system prompts...")

        try:
            with mlflow.start_run(run_name=f"Eval_Run_{int(time.time())}"):
                total_cases = len(self.eval_dataset)
                passed_assertions = 0

                for index, test_case in enumerate(self.eval_dataset, 1):
                    print(f"\nProcessing Evaluation Case {index}/{total_cases} [{test_case['category']}]")

                    start_time = time.time()
                    agent_output = run_monitored_agent(test_case["query"])
                    latency_ms = (time.time() - start_time) * 1000
                    response_text = agent_output.get("final_response", "")

                    # Groundedness & Faithfulness Verification Gate
                    is_faithful = test_case["expected_keyword"].lower() in response_text.lower()
                    if is_faithful:
                        passed_assertions += 1
                        print(f"✅ Case {index} Passed: Grounded truth located ('{test_case['expected_keyword']}')")
                    else:
                        print(f"❌ Case {index} Failed: Response deviated from context source.")

                    # Log independent matrix traces for individual test parameters
                    mlflow.log_metric(f"case_{index}_latency_ms", latency_ms)
                    mlflow.log_metric(f"case_{index}_faithfulness_score", 1.0 if is_faithful else 0.0)

                # System Level Aggregations
                accuracy_yield = (passed_assertions / total_cases) * 100
                mlflow.log_metric("total_eval_accuracy_percentage", accuracy_yield)
                print(f"\n🏁 [Evaluation Complete] Accuracy Yield: {accuracy_yield:.2f}% | Passed: {passed_assertions}/{total_cases}")

                return accuracy_yield
        except Exception as e:
            print(f"⚠️ [MLflow Trace Error] Evaluation suite run aborted: {e}")
            return 0.0

if __name__ == "__main__":
    suite = AIEvaluationSuite()
    suite.execute_regression_test_suite()
