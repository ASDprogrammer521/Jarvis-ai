#!/usr/bin/env python3
"""
Jarvis Phone Agent — reverse link from phone → PC (no ADB, no Metasploit).

Run on the phone with Termux:
  pkg install python
  pip install websocket-client
  python phone_agent.py 192.168.35.70 YOURKEY

The phone opens an outbound WebSocket to the PC dashboard.
"""
import json
import sys
import time

try:
    import websocket
except ImportError:
    print("Install: pip install websocket-client")
    sys.exit(1)


def main():
    if len(sys.argv) < 3:
        print("Usage: python phone_agent.py <PC-IP> <PAIRING-KEY>")
        print("Example: python phone_agent.py 192.168.35.70 AB12CD")
        sys.exit(1)

    host = sys.argv[1].replace("http://", "").replace("https://", "").split("/")[0]
    if ":" not in host:
        host = host + ":8000"
    key = sys.argv[2].strip().upper()
    url = f"ws://{host}/ws?token={key}"

    print(f"Connecting to {url.replace(key, '***')} …")

    def on_message(ws, message):
        try:
            m = json.loads(message)
            print("←", m.get("text") or m)
        except Exception:
            print("←", message)

    def on_open(ws):
        print("Connected. Type a command and press Enter. Ctrl+C to quit.")
        ws.send(json.dumps({"type": "hello", "client": "phone_agent"}))

    def on_error(ws, error):
        print("Error:", error)

    def on_close(ws, *args):
        print("Disconnected.")

    ws = websocket.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    import threading
    t = threading.Thread(target=ws.run_forever, kwargs={"ping_interval": 20}, daemon=True)
    t.start()

    try:
        while t.is_alive():
            line = input()
            if not line.strip():
                continue
            if ws.sock and ws.sock.connected:
                ws.send(json.dumps({"type": "command", "text": line.strip()}))
                print("→", line.strip())
            else:
                print("Not connected.")
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
        ws.close()


if __name__ == "__main__":
    main()
