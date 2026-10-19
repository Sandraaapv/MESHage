import json
import urllib.request
import sys

def run_tests():
    base_url = "http://127.0.0.1:5000"

    # 1. State
    print("Testing GET /api/state...")
    with urllib.request.urlopen(f"{base_url}/api/state", timeout=5) as res:
        state = json.loads(res.read().decode("utf-8"))
        print(f"State: {len(state['nodes'])} nodes, {len(state['links'])} links")

    def post(path, data):
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read().decode("utf-8"))

    # 2. Send message
    print("Testing POST /api/message/send...")
    res_msg = post("/api/message/send", {"src": "N0", "dst": "N5"})
    print("Send message result:", res_msg.get("delivered"), "Path:", res_msg.get("final_path"))

    # 3. Emergency Alert
    print("Testing POST /api/alert...")
    res_alert = post("/api/alert", {"payload": "EVACUATE"})
    print("Alert reached nodes:", len(res_alert.get("reached_nodes", [])))

    # 4. Toggle Node
    print("Testing POST /api/node/toggle...")
    res_toggle = post("/api/node/toggle", {"name": "N3"})
    print("Toggle node N3 alive:", res_toggle.get("alive"))

    # 5. Kill random
    print("Testing POST /api/kill-random...")
    res_kill = post("/api/kill-random", {})
    print("Killed random node:", res_kill.get("killed"))

    # 6. Config update
    print("Testing POST /api/config...")
    res_cfg = post("/api/config", {"n_exponent": 3.4})
    print("Config n_exponent:", res_cfg.get("n_exponent"))

    # 7. Static dashboard HTML
    print("Testing GET /dashboard...")
    with urllib.request.urlopen(f"{base_url}/dashboard", timeout=5) as res:
        html = res.read().decode("utf-8")
        assert "<canvas id=\"mesh-canvas\"" in html
        print(f"Dashboard HTML served OK ({len(html)} bytes)")

    print("\nALL SERVER TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
