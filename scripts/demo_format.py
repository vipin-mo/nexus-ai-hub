"""Pretty-printers for scripts/demo.sh (reads JSON from stdin)."""
import json
import sys


def answer() -> None:
    r = json.load(sys.stdin)
    route, sec, use = r.get("route") or {}, r.get("security") or {}, r.get("usage") or {}
    print(f"  status={r.get('status')} route={route.get('intent')}/{route.get('source')} model={use.get('model')} "
          f"tokens={use.get('input_tokens')}+{use.get('output_tokens')} pii={sec.get('pii_redacted')} "
          f"latency={r.get('gateway_latency_ms')}ms")
    if r.get("status") == "BLOCKED":
        print(f"  blocked by {sec.get('layer')}: {sec.get('category')}")
    if r.get("recommendations"):
        print("  tools:", [t["id"] for t in r["recommendations"]])
    print("  answer:", (r.get("answer") or r.get("error") or "")[:300].replace("\n", " "))


def audio() -> None:
    for line in sys.stdin:
        r = json.loads(line)
        g = r.get("gateway_reply") or {}
        print(f"  {r['file']}: \"{r['transcript']}\" stt={r['stt_ms']:.0f}ms -> {g.get('status') or r.get('error')}"
              f" | {(g.get('answer') or '')[:120]}")


def audit() -> None:
    for e in json.load(sys.stdin):
        print(f"  {e['createdAt'][:19]} {e['eventType']:9s} {e['clientName']:14s} {e['status']:16s} "
              f"route={e['route']} sha256={str(e['querySha256'])[:12]}")


if __name__ == "__main__":
    {"answer": answer, "audio": audio, "audit": audit}[sys.argv[1]]()
