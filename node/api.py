"""
flask api server for mesh node
provides rest endpoints, sse event streaming, and static file serving
"""
import json
import logging
import os
import queue
import sys
import threading
import time
from typing import Any, Dict, Optional

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask, Response, jsonify, request, send_from_directory


def create_app(mesh_node: Any, ui_dir: Optional[str] = None) -> Flask:
    # disable verbose flask startup logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.WARNING)

    app = Flask(__name__)

    # resolve ui directory: prefer ui/phone if exists, else ui/
    base_ui = ui_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ui"))
    phone_ui = os.path.join(base_ui, "phone")

    # allow requests from local network
    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.route("/api/state", methods=["GET"])
    def get_state():
        # calculate neighbor signal quality and status
        now = time.time()
        neighbors_info = []

        with mesh_node.lock:
            for name, info in mesh_node.neighbor_table.items():
                last_seen_diff = now - info.get("last_seen", 0)
                status = info.get("status", "DOWN")
                addr = info.get("addr", ("", 0))
                addr_str = f"{addr[0]}:{addr[1]}" if addr else ""

                if status == "UP":
                    if last_seen_diff < 4.0:
                        signal = "strong"
                        bars = 3
                    elif last_seen_diff < 8.0:
                        signal = "fair"
                        bars = 2
                    else:
                        signal = "weak"
                        bars = 1
                else:
                    signal = "down"
                    bars = 0

                neighbors_info.append({
                    "name": name,
                    "status": status,
                    "address": addr_str,
                    "last_seen_seconds": round(last_seen_diff, 1),
                    "signal_quality": signal,
                    "signal_bars": bars,
                })

            state = {
                "node_name": mesh_node.name,
                "port": mesh_node.port,
                "routing_mode": mesh_node.routing_mode,
                "neighbors": neighbors_info,
                "counters": dict(getattr(mesh_node, "counters", {})),
                "total_messages": len(mesh_node.messages),
                "total_events": len(mesh_node.events),
            }

        return jsonify(state)

    @app.route("/api/send", methods=["POST"])
    def send_message():
        # send chat message to a destination or ALL
        data = request.get_json(silent=True) or request.form
        dst = data.get("dst") or data.get("destination") or "ALL"
        payload = data.get("payload") or data.get("message") or data.get("text", "")

        if not payload:
            return jsonify({"status": "error", "error": "payload is required"}), 400

        msg = mesh_node.send_chat(dst=dst, payload=payload, msg_type="chat")
        if not msg:
            return jsonify({"status": "error", "error": "failed to originate message"}), 500

        return jsonify({
            "status": "ok",
            "id": msg.id,
            "src": msg.src,
            "dst": msg.dst,
            "payload": msg.payload,
            "type": msg.type,
            "timestamp": msg.timestamp,
        })

    @app.route("/api/alert", methods=["POST"])
    def send_alert():
        # broadcast emergency alert to ALL
        data = request.get_json(silent=True) or request.form
        payload = data.get("payload") or data.get("message") or data.get("alert", "EMERGENCY ALERT")

        msg = mesh_node.send_chat(dst="ALL", payload=payload, msg_type="emergency")
        if not msg:
            return jsonify({"status": "error", "error": "failed to broadcast alert"}), 500

        return jsonify({
            "status": "ok",
            "id": msg.id,
            "src": msg.src,
            "dst": "ALL",
            "payload": msg.payload,
            "type": "emergency",
            "timestamp": msg.timestamp,
        })

    @app.route("/api/messages", methods=["GET"])
    def get_messages():
        # return message history with path and delivery status
        with mesh_node.lock:
            history = []
            for m in mesh_node.messages:
                item = dict(m)
                item["delivery_status"] = "delivered" if (m.get("dst") == mesh_node.name or m.get("dst") == "ALL") else "sent"
                history.append(item)
        return jsonify(history)

    @app.route("/api/events", methods=["GET"])
    def stream_events():
        # server-sent events stream for live updates
        def event_stream():
            q: queue.Queue = queue.Queue(maxsize=100)
            with mesh_node.lock:
                # send initial backlog of recent events
                recent = list(mesh_node.events[-15:])
                mesh_node.event_subscribers.append(q)

            for evt in recent:
                yield f"data: {json.dumps(evt)}\n\n"

            try:
                while True:
                    try:
                        evt = q.get(timeout=8.0)
                        yield f"data: {json.dumps(evt)}\n\n"
                    except queue.Empty:
                        # keepalive ping to maintain connection
                        yield ": keepalive\n\n"
            finally:
                with mesh_node.lock:
                    if q in mesh_node.event_subscribers:
                        mesh_node.event_subscribers.remove(q)

        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # serve static UI files from ui/ or ui/phone/
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_static(path: str):
        # 1. check in ui/phone/
        if os.path.exists(phone_ui):
            target = os.path.join(phone_ui, path)
            if path and os.path.isfile(target):
                return send_from_directory(phone_ui, path)
            # root index
            if not path and os.path.isfile(os.path.join(phone_ui, "index.html")):
                return send_from_directory(phone_ui, "index.html")

        # 2. check in ui/
        if os.path.exists(base_ui):
            target = os.path.join(base_ui, path)
            if path and os.path.isfile(target):
                return send_from_directory(base_ui, path)
            if not path and os.path.isfile(os.path.join(base_ui, "index.html")):
                return send_from_directory(base_ui, "index.html")

        # default stub html if UI files not yet created
        return f"""<!DOCTYPE html>
<html>
<head><title>MESHage Node {mesh_node.name}</title></head>
<body style="font-family:sans-serif; background:#0B1220; color:#E8ECF6; padding:2rem;">
  <h1>MESHage Node: {mesh_node.name}</h1>
  <p>Status: Running on port {mesh_node.port} (mode: {mesh_node.routing_mode})</p>
  <p>API endpoints active: <code>/api/state</code>, <code>/api/messages</code>, <code>/api/events</code></p>
</body>
</html>"""

    return app


def start_api_server(
    mesh_node: Any,
    host: str = "0.0.0.0",
    port: int = 5000,
    ui_dir: Optional[str] = None,
) -> threading.Thread:
    app = create_app(mesh_node, ui_dir=ui_dir)
    server_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True),
        daemon=True,
    )
    server_thread.start()
    return server_thread
