import os
import sys
import json
import asyncio
import websockets

# Calculate absolute path targeting project root workspace mapping context
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

# Import the monitored execution function from graph.py
from ai_orchestrator.agents.graph import run_monitored_agent

HOST = "0.0.0.0"
PORT = 8765

async def handle_stream_connection(websocket):
    """Handles incoming real-time network streams asynchronously using non-blocking I/O loops."""
    print("🔌 Incoming WebSocket connection established from client!")
    async_engine_loop = asyncio.get_running_loop()

    try:
        async for message in websocket:
            try:
                # Parse the streaming data block frame
                payload = json.loads(message)

                # Extract routing variables safely
                user_query = payload.get("query", "") or payload.get("input_query", "")
                session_id = payload.get("session_id", "default_session")
                role = payload.get("role", "nexus_agent")

                print(f"[Stream Input Captured]: '{user_query}' for Session: {session_id} [Role: {role}]")

                # Offload synchronous LangGraph execution steps to a pool worker thread
                output = await async_engine_loop.run_in_executor(
                    None,
                    lambda: run_monitored_agent(input_text=user_query, session_id=session_id, role=role)
                )

                # Build and stream response back to Java gateway architecture
                response_payload = {
                    "status": "STREAMING_COMPLETE",
                    "routing_path": output.get("routing_destination"),
                    "security_passed": output.get("security_passed"),
                    "final_response": output.get("final_response", "Inference routing dropped."),
                    "tokens_used": output.get("tokens_used", 0)
                }

                await websocket.send(json.dumps(response_payload))
                print(f"[Stream Output Dispatched]: Step processing complete.")

            except json.JSONDecodeError as jde:
                print(f"⚠️ [Payload Error] Malformed JSON structure received: {str(jde)}")
                error_payload = {"status": "ERROR", "message": "Invalid JSON payload format."}
                await websocket.send(json.dumps(error_payload))

            except Exception as inner_ex:
                print(f"❌ [Agent Processing Error] Caught during execution: {str(inner_ex)}")
                error_payload = {"status": "ERROR", "message": f"Execution dropped: {str(inner_ex)}"}
                await websocket.send(json.dumps(error_payload))

    except websockets.exceptions.ConnectionClosedOK:
        print("[Python Stream Server] Client closed connection gracefully.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"⚠️ [Stream Server Connection Reset]: Channel dropped unexpected: {e}")
    except Exception as e:
        print(f"❌ [Fatal Stream Server Error] Drop caught in runtime loop: {str(e)}")

async def main():
    print(f"Initializing Asynchronous Core Network Hub on ws://{HOST}:{PORT}...")
    async with websockets.serve(handle_stream_connection, HOST, PORT):
        await asyncio.Future()  # Keeps server running permanently

if __name__ == "__main__":
    asyncio.run(main())
