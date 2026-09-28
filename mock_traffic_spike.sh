#!/usr/bin/env bash
# Mocks concurrent enterprise activity spikes crossing endpoints

set -e
echo "🔥 Initiating Simulated High-Throughput Request Spike..."

queries=(
  "What are our rules about destructive database writes?"
  "Where must relational customer metadata reside?"
  "Querying data storage container configurations"
  "Check safety gates for autonomous tool execution"
)

# Loop to blast traffic arrays down into the active Java endpoint
for i in {1..15}; do
  random_idx=$(( RANDOM % 4 ))
  selected_query="${queries[$random_idx]}"
  session_id="spike_test_session_$(printf "%03d" $i)"

  echo "🚀 Dispatching Concurrent Request Loop [$i/15] for Session: $session_id"

  # Dispatches asynchronously using background operators (&) to simulate concurrent spikes
  curl -s -X POST http://localhost:8080/api/v1/gateway/dispatch \
       -H "Content-Type: application/json" \
       -d "{\"query\": \"$selected_query\", \"session_id\": \"$session_id\"}" > /dev/null &

  sleep 0.3 # Fast stagger interval mimicking intense burst traffic activity curves
done

wait
echo "✅ Traffic simulation burst run completed successfully."
