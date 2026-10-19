#!/usr/bin/env bash
# =========================================================
# MESHage Node Runner Script for Android Phones (Termux)
# - Automatically detects phone's local IP address
# - Reads or prompts for node name
# - Loads neighbor configuration from config/nodes.json
# - Starts UDP mesh node + Flask web API
# - Displays browser UI URL (http://localhost:5000)
# =========================================================

set -e

# Resolve project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# Locate python binary
PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

echo "=================================================="
echo "          MESHage Phone Node Runner               "
echo "=================================================="

# 1. Acquire Termux wake lock if available to prevent sleep
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null || true
fi

# 2. Automatically detect this phone's local IP address
LOCAL_IP=$("$PYTHON_BIN" -c "
import socket, subprocess, re

def detect_ip():
    # Method A: UDP connect trick to local subnets (no actual traffic sent)
    for target in ['192.168.43.1', '192.168.43.255', '192.168.1.1', '10.0.0.1', '8.8.8.8']:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 53))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith('127.'):
                return ip
        except Exception:
            pass

    # Method B: Parse network interface tools (ip, ifconfig)
    for cmd in [['ip', '-4', 'addr', 'show'], ['ifconfig']]:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8')
            ips = re.findall(r'inet\s+(?:addr:)?(\d+\.\d+\.\d+\.\d+)', out)
            for ip in ips:
                if not ip.startswith('127.') and not ip.startswith('169.254.'):
                    return ip
        except Exception:
            pass

    # Method C: Hostname lookup
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith('127.'):
            return ip
    except Exception:
        pass

    return '127.0.0.1'

print(detect_ip())
")

echo "[+] Detected Phone IP: $LOCAL_IP"

# 3. Locate configuration file (nodes.json or nodes.example.json)
CONFIG_FILE=""
if [ -f "config/nodes.json" ]; then
    CONFIG_FILE="config/nodes.json"
elif [ -f "config/nodes.example.json" ]; then
    echo "[!] config/nodes.json not found, using config/nodes.example.json"
    CONFIG_FILE="config/nodes.example.json"
else
    echo "[-] Error: No configuration file found in config/"
    exit 1
fi

# 4. Determine Node Name (from CLI args, env var, or interactive prompt)
NODE_NAME=""

# Check CLI flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name|-n)
            NODE_NAME="$2"
            shift 2
            ;;
        --config|-c)
            CONFIG_FILE="$2"
            shift 2
            ;;
        *)
            if [ -z "$NODE_NAME" ]; then
                NODE_NAME="$1"
            fi
            shift
            ;;
    esac
done

# If not passed via args, check environment variable
if [ -z "$NODE_NAME" ] && [ -n "$MESH_NODE_NAME" ]; then
    NODE_NAME="$MESH_NODE_NAME"
fi

# If still empty, display available nodes and prompt user
if [ -z "$NODE_NAME" ]; then
    echo ""
    echo "Available nodes in $CONFIG_FILE:"
    "$PYTHON_BIN" -c "
import json, sys
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
nodes = cfg.get('nodes', cfg)
for k, v in nodes.items():
    role = v.get('role', '') if isinstance(v, dict) else ''
    ip = v.get('ip', '') if isinstance(v, dict) else ''
    nbrs = v.get('neighbors', []) if isinstance(v, dict) else v
    nbr_str = ', '.join(nbrs) if isinstance(nbrs, list) else str(nbrs)
    print(f'   • Node \"{k}\" (Configured IP: {ip}) -> Neighbors: [{nbr_str}]  {role}')
"
    echo ""
    read -rp "Enter node name for this phone (e.g. A, B, C): " USER_INPUT
    NODE_NAME=$(echo "$USER_INPUT" | tr -d '[:space:]')
fi

if [ -z "$NODE_NAME" ]; then
    echo "[-] Error: Node name cannot be empty."
    exit 1
fi

# 5. Extract node configuration from JSON
NODE_CONFIG=$("$PYTHON_BIN" -c "
import json, sys

cfg_file = '$CONFIG_FILE'
target_name = '$NODE_NAME'

with open(cfg_file) as f:
    cfg = json.load(f)

nodes = cfg.get('nodes', cfg)
default_routing = cfg.get('routing_mode', 'shortest')

if target_name in nodes:
    item = nodes[target_name]
    if isinstance(item, dict):
        port = item.get('port', 5001)
        api_port = item.get('api_port', 5000)
        routing = item.get('routing', default_routing)
        nbrs = item.get('neighbors', [])
    elif isinstance(item, list):
        port = 5001
        api_port = 5000
        routing = default_routing
        nbrs = item
    else:
        port = 5001
        api_port = 5000
        routing = default_routing
        nbrs = []
    print(f'{port}|{api_port}|{routing}|{\",\".join(nbrs)}')
else:
    # Node not found in config, output defaults
    print(f'5001|5000|{default_routing}|')
")

IFS='|' read -r PORT API_PORT ROUTING NEIGHBORS <<< "$NODE_CONFIG"

# 6. Display node banner and browser URL
echo ""
echo "=================================================="
echo " Starting MESHage Node: $NODE_NAME"
echo "--------------------------------------------------"
echo " Local Network IP:   $LOCAL_IP"
echo " UDP Listener Port:  $PORT"
echo " Web UI / API Port:  $API_PORT"
echo " Routing Mode:       $ROUTING"
echo " Neighbors List:     ${NEIGHBORS:-<None - waiting for hellos>}"
echo " Config File:        $CONFIG_FILE"
echo "=================================================="
echo ""
echo " 🌐 Open this URL in your phone's browser:"
echo ""
echo "      👉 http://localhost:$API_PORT"
echo "   or 👉 http://$LOCAL_IP:$API_PORT"
echo ""
echo "=================================================="
echo " Type 'status', 'send <dst> <msg>', or 'alert <msg>'"
echo " Press Ctrl+C to stop node."
echo "=================================================="
echo ""

# 7. Launch mesh node
exec "$PYTHON_BIN" node/mesh_node.py \
    --name "$NODE_NAME" \
    --port "$PORT" \
    --api-port "$API_PORT" \
    --routing "$ROUTING" \
    --neighbors "$NEIGHBORS"
