# Raw result files

The output files behind the numbers in [BENCHMARKS.md](../../../BENCHMARKS.md), copied unchanged from
the runs (the two `.log` files only have their terminal colour codes removed). They hold metrics and
run settings; IDs are random request, trace and MLflow run IDs from a local stack.

| File | Produced by | Backs |
|---|---|---|
| `eval_local.json` | `make eval-local`, 2026-10-21 (qwen2.5:3b, llama3:8b judge) | Sections 1-5: fact recall 0.9062, citations 0.4286, held-out guard 0.75 / 0.05, routing 0.90, recommendations |
| `eval_cloud.json` | `run_evals --profile cloud`, 2026-10-21 (Claude Haiku 4.5, local judge) | Section 1: fact recall 0.9688, citations 0.9643, 4 / 4 refusals, $0.039362 |
| `eval_cloud_claude_judge.json` | the same with a Claude judge | Section 1: groundedness with a Claude judge, Claude p50 1.7 s / p95 2.6 s |
| `model_comparison/*.json` | `make eval-local` per answer model, earlier prompt version | Section 1: the 1.5B / 3B / 7B / llama3 comparison (the 1.5B figure is the `_v2` run) |
| `router_threshold_sweep.json` | `python -m evals.sweep_router_threshold`, 2026-10-27 | Section 3: the threshold sweep |
| `gateway_latency_laptop.json` | `scripts/benchmark.py --only answers`, 2026-10-27 | Section 6: p50 1.79 s / p95 2.17 s (qwen2.5:3b scanner) and 7.59 s / 9.35 s (llama3:8b scanner) |
| `paid_claude_checks/` | the paid checklist, 2026-10-21 | Section 1: tokens and cost of the first Claude call, model tiering, the spend-cap fallback |
| `aws_benchmark_2026-11-12.json` | `scripts/benchmark.py --only overhead,answers` on the AWS instance, 2026-11-12 | Section 6: the second AWS run (answers p50 34.8 s, overhead 63 req/s) |

Other evidence lives next to this folder: [aws_run.txt](../aws_run.txt) and
[aws_run_2026-11-12.txt](../aws_run_2026-11-12.txt) (AWS demo, benchmark and, in the second, the Ollama
binding and reboot checks) and
[minikube_run.txt](../minikube_run.txt) (Kubernetes run).

**Not kept as raw files:** the laptop gateway-overhead run (342 req/s), the speech-to-text timings and
word error rate, and the data-pipeline throughput and PII-recall runs. Their numbers are in
BENCHMARKS.md, but the output files were overwritten by later runs. Reproduce them with `make bench`,
`python scripts/stt_wer.py` and `LINES=200000 make pipeline-local`.
