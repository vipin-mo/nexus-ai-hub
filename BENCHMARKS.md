# Benchmarks and evaluation results

All numbers were measured on 2026-10-21 with the scripts in this repository, except the routing
threshold sweep and the end-to-end latency, which were re-measured on 2026-10-27. No number is estimated.
Where this file and a commit message disagree, this file is current (see [Earlier figures](#earlier-figures)).

**Machine:** Apple M5 (10 cores), 16 GB RAM, macOS 26.6. Docker Desktop with a 12 GB VM. Ollama ran on
the host (Metal). The machine was under memory pressure (swap in use), so treat latencies as
laptop numbers, not server numbers.

**Datasets:** all synthetic or hand-written for this project (`evals/datasets`). They are small, so a
single case moves a percentage by 2-5 points. Counts are given next to each result, and 95% Wilson
intervals where n is about 20 or fewer.

| What | Reproduce with |
|---|---|
| Retrieval, routing, security, recommendation, answer quality | `make eval-local` (or `--profile offline` for CI) |
| Gateway overhead, answer latency, speech-to-text | `make up && make bench` |
| Routing threshold sweep | `python -m evals.sweep_router_threshold --models qwen2.5:1.5b,qwen2.5:3b,llama3:8b` |
| Pipeline throughput, PII recall, Spark vs DuckDB | `LINES=200000 make pipeline-local`, `data_pipeline/scripts/benchmark_etl.py` |
| Speech-to-text word error rate | `python scripts/stt_wer.py` |

## 1. Answer quality (32 golden questions, local models)

Configuration: `qwen2.5:3b` (answers, security scan, routing fallback) and `nomic-embed-text`
(embeddings). The judge is `llama3:8b`.

| Metric | Result | Notes |
|---|---|---|
| Required facts present in the answer | 90.6% (29 / 32; 95% CI 76-97%) | regex per fact, e.g. "4 hours", "TLS 1.3" |
| Expected document retrieved | 96.4% (27 / 28) | across the whole pipeline, including the guard |
| Answer cites the expected document inline | 42.9% (12 / 28) | small models often skip `[file.md]` citations; the response always lists `sources` |
| Groundedness (LLM judge, 1-5 scaled to 0-1) | 0.975 | local judge |
| Refuses the 4 unanswerable questions | 3 / 4 | |

### Claude Haiku 4.5 on the same 32 questions (paid run, every route sent to Claude)

This run forced every route to Claude to compare answer quality. In normal operation only
`COMPLEX_REASONING` requests go to Claude, so the $0.039 below is the cost of this test, not of 32
typical requests.

| Metric | Local qwen2.5:3b | Claude Haiku 4.5 |
|---|---|---|
| Required facts present | 90.6% | **96.9%** |
| Cites the expected document inline | 42.9% | **96.4%** |
| Expected document retrieved | 96.4% | 96.4% (same retriever) |
| Refuses the 4 unanswerable questions | 3 / 4 | **4 / 4** |
| Groundedness, local judge / Claude judge | 0.975 / - | 1.0 / 1.0 |
| Answer latency p50 / p95 (eval process) | 3.8 s / 5.0 s | 1.7 s / 2.6 s |
| Cost of the 32 answers | $0 | **$0.039** (about $0.0012 per answer) |

The cost comes from `message.usage` and the pricing table ($1 / $5 per million input / output tokens).
The ledger, the MLflow trace and the API response all agreed on the first call: 1,062 + 301 tokens,
$0.002567. Two more checks: knowledge questions stayed on the local model at $0, and with
`NEXUS_SPEND_CAP_USD=0.001` the second request fell back to the local model (`degraded: true`). All
paid checks together cost about $0.13. Groundedness is at the top of its scale with both judges, so it
does not separate the two configurations; fact recall and citations do.

Local answer models compared on an earlier prompt version (fact recall / citations / refusals):
qwen2.5:1.5b 87.5% / 0% / 75%, **qwen2.5:3b 87.5% / 43% / 100%**, qwen2.5:7b 87.5% / 86% / 100% (about 4x
slower), llama3:8b 84.4% / 43% / 100%.

## 2. Retrieval (28 answerable golden questions, top-3)

| Mode | hit@1 | hit@3 | MRR | hit@3 on paraphrased questions |
|---|---|---|---|---|
| Dense (Chroma + nomic-embed-text) | 0.786 | 0.929 | 0.857 | 0.714 |
| Sparse (BM25) | **0.893** | **0.964** | **0.923** | 0.857 |
| Hybrid (reciprocal-rank fusion) | 0.786 | **0.964** | 0.875 | 0.857 |

On 8 short, keyword-rich policy documents, BM25 alone is the strongest retriever. Hybrid matches it at
hit@3 and does better than dense alone. Hybrid is kept as a guard against vocabulary mismatch on larger
corpora, but **this corpus does not show a gain from it**.

## 3. Intent routing (60 hand-written challenge queries)

| Router | Accuracy | Notes |
|---|---|---|
| TF-IDF + logistic regression, held-out templated split | 100% | not meaningful: the templates leak into the split |
| Same classifier on the hand-written challenge set | 86.7% | p50 0.55 ms |
| Classifier + qwen2.5:3b fallback below confidence 0.45 (shipped) | **90.0%** (54 / 60; 95% CI 80-95%) | 13% of queries go to the LLM (about 250-450 ms extra) |
| qwen2.5:3b alone on every query | 81.7% | the LLM is worse than the classifier on its own |

Confidence threshold sweep (final accuracy, 60 queries; each model labels every query once and the
threshold decides whose label is used):

| Threshold | Fallback rate | qwen2.5:1.5b | qwen2.5:3b (shipped) | llama3:8b |
|---|---|---|---|---|
| 0.00 (classifier only) | 0% | 86.7% | 86.7% | 86.7% |
| 0.40 | 3% | 90.0% | 90.0% | 90.0% |
| **0.45 (shipped)** | 13% | 90.0% | **90.0%** | 91.7% |
| 0.50 | 23% | 88.3% | 90.0% | 93.3% |
| 0.55 | 30% | 86.7% | 90.0% | 90.0% |
| 0.60 | 40% | 85.0% | 86.7% | 86.7% |
| 0.65 (first choice) | 47% | 81.7% | 85.0% | 86.7% |
| 0.70 | 58% | 80.0% | 85.0% | 83.3% |

llama3:8b at 0.50 scores 3 points higher (2 queries), but it would be a second resident model, which
costs far more latency than that (see section 6). The challenge set was used to choose the threshold,
so 90.0% is optimistic for new queries.

## 4. Security guard

Two datasets: a **development set** (62 cases) that informed the rules and the prompt, and a **held-out
set** (40 cases) written afterwards and never tuned on.

| Layer | Dev: attacks blocked | Dev: benign blocked | Held-out: attacks blocked | Held-out: benign blocked |
|---|---|---|---|---|
| Rules only (normalised regex) | 87.9% (29 / 33) | 0% (0 / 29) | **15.0%** (3 / 20) | 0% (0 / 20) |
| Rules + qwen2.5:3b classifier | 97.0% (32 / 33) | 0% (0 / 29) | **75.0%** (15 / 20) | 5.0% (1 / 20) |

With 20 held-out cases per class the 95% intervals are wide: 75% attacks blocked is 53-89%, 5% benign
blocked is 1-24%, and 15% for the rules alone is 5-36%. One case moves a held-out figure by 5 points.

The rules overfit the phrasings they were written for; the LLM layer does most of the work on new
phrasings. The classifier adds a median 445 ms. Configurations compared on the held-out set:

| Classifier | Prompt | Attacks blocked (of 20) | Benign blocked (of 20) |
|---|---|---|---|
| qwen2.5:3b | decomposed ("asking about rules?" vs "attacking?") | **75%** | **5%** |
| qwen2.5:1.5b | decomposed | 45% | 5% |
| qwen2.5:3b | single verdict | 85% | 20% |
| llama3:8b | single verdict | 60% | 0% |

## 5. Tool recommendations

| Metric | Result |
|---|---|
| Top-1 / top-3 correct tool (13 graded cases) | 84.6% / 92.3% |
| Tools returned that the caller's role may not use | 0 |
| Leave-one-out hit@1: item-item CF vs role popularity (74 synthetic users) | 0.878 vs 0.392 |
| Leave-one-out MRR: CF vs popularity | 0.937 vs 0.629 |

The usage data is synthetic, generated from latent workstreams, so CF recovering that structure is
expected. The point is the evaluation method, not the absolute number.

## 6. Latency

**End to end through the gateway** (8 questions, sequential, after one excluded warm-up request; answers
by qwen2.5:3b in both rows, only the security scanner differs):

| Security scanner | p50 | p95 | Guard | Route | Retrieve | Answer |
|---|---|---|---|---|---|---|
| qwen2.5:3b (shipped) | **1.79 s** | **2.17 s** | 473 ms | 2 ms | 14 ms | 965 ms |
| llama3:8b | 7.59 s | 9.35 s | 4,036 ms | 7 ms | 293 ms | 2,738 ms |

Stage columns are medians. Reproduce with `make bench`, or for the second row
`NEXUS_LOCAL_MODEL=llama3:8b make up && python scripts/benchmark.py --label llama3_scanner`.

Model residency matters more than model choice on a 16 GB machine. With llama3:8b as the scanner, swap
use reached 8.4 of 9.2 GB and every stage slowed down, including the ones that do not call the 8B model.
That is why one ~2 GB model does every local task.

**Gateway + orchestrator overhead** without a model call (400 requests that the rules layer blocks).
This covers API-key auth, two Postgres audit writes, the WebSocket hop, the guard and the event log.

| Concurrent clients | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| 1 | 99 req/s | 8.7 ms | 17 ms | 21 ms | 0 |
| 8 | 258 req/s | 22.6 ms | 35.8 ms | 386 ms | 0 |
| 32 | 342 req/s | 86 ms | 118 ms | 147 ms | 0 |

The first version of the bounded-concurrency change rejected excess requests immediately: at 32
clients only 150 of 400 succeeded. A bounded wait queue fixed that.

## 7. Speech-to-text (C++ + whisper.cpp base.en)

| Clip | Decode | VAD | Transcription | Real-time factor |
|---|---|---|---|---|
| 3.7 s, 16 kHz mono (Metal, warm) | 0.39 ms | 0.045 ms | 50 ms | 0.014 (about 70x faster than real time) |
| 7.7 s, 44.1 kHz stereo with noise and silence (Metal) | 4.0 ms (incl. resampling) | 0.11 ms | 56 ms | 0.007 |
| 3.7 s in the Linux container (CPU only) | - | - | about 750 ms | about 0.2 |

Word error rate on the 5 sample clips is **7.4%** (4 of 54 words, 95% CI 3-18%: "writes"→"rights",
"assistant"→"assist and"). Five TTS clips are a smoke test, not a WER benchmark; real speech will be
worse. Silence is detected
and never sent to the recogniser.

## 8. Data pipeline (200,000 synthetic log lines)

| Stage | Time | Notes |
|---|---|---|
| Perl parse + regex redaction | 2.9 s | about 70k lines/s on one core; 797 malformed lines rejected and reconciled |
| Spark (local[*]): NER redaction, lake, marts, DQ | 14.5 s | most of it spaCy NER on lines with candidate names |
| DuckDB warehouse rebuild + atomic swap | 0.19 s | |

PII redaction recall (ground truth from the generator):

| Type | Inserted | Leaked | Recall |
|---|---|---|---|
| Email (incl. "(at)/[dot]" spellings), phone, SSN, card, IP, secret, username | 76,248 | 0 | 100% |
| Person names (spaCy `en_core_web_sm`) | 19,558 | 1,003 | 94.9% |
| **All** | 95,806 | 1,003 | **98.95%** |

Order numbers wrongly redacted as cards: 0. Before the card-length and issuer-prefix rule it was
about 10%, because 1 in 10 random digit strings passes the Luhn check.

**Spark vs DuckDB** on the same hourly error-rate mart (199k rows): Spark 1.73 s, DuckDB 0.032 s. At
this size DuckDB alone is about 50x faster. Spark is used to show a job written to scale out, not
because this data needs it. All Spark numbers are from local mode (`local[*]`, one machine); the job
has not been run on a cluster.

## Tests

57 Python tests (offline: fake LLM, hashing embeddings), 17 Java tests (including 3 Testcontainers
PostgreSQL integration tests), and 7 C++ test groups. CI runs all of them, plus the offline evaluation
gate, the pipeline on 20k lines, image builds and Kubernetes manifest validation. The manifests were
also deployed on minikube once ([output](docs/evidence/minikube_run.txt)); CI does not deploy them.

## Earlier figures

Some commit messages quote figures from earlier setups. They are kept in the history but superseded:

| Commit message says | Setup then | Current figure |
|---|---|---|
| Routing 91.7%, threshold sweep 81.7% -> 91.7% (Phase 3) | llama3:8b as the routing fallback | 90.0% with qwen2.5:3b (section 3) |
| One resident model cut end-to-end p50 from 7.4 s to 1.2 s (Phase 7) | measured inside the orchestrator process, not through the gateway | 7.59 s -> 1.79 s through the gateway (section 6) |
| $0.039 for 32 answers (Phase 7) | every route forced to Claude for the comparison | same figure; it is the cost of that test run, not of normal traffic (section 1) |
