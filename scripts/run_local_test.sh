#!/usr/bin/env bash
# run local 3-node mesh test on localhost:
# A (5001) <-> B (5002) <-> C (5003)
# A knows only B, B knows A and C, C knows only B

echo "=== MESHage Local 3-Node Test ==="
echo "Topology: A (port 5001) <---> B (port 5002) <---> C (port 5003)"
echo "A knows only B. B knows A and C. C knows only B."

# clean up background processes on exit
trap 'kill $(jobs -p) 2>/dev/null; echo "Nodes stopped."' EXIT

# 1. start Node C (knows only B)
python node/mesh_node.py --name C --port 5003 --neighbors 127.0.0.1:5002 --non-interactive &
PID_C=$!

# 2. start Node B (knows A and C)
python node/mesh_node.py --name B --port 5002 --neighbors 127.0.0.1:5001,127.0.0.1:5003 --non-interactive &
PID_B=$!

# 3. start Node A (knows only B)
python node/mesh_node.py --name A --port 5001 --neighbors 127.0.0.1:5002 &
PID_A=$!

echo "Waiting for nodes to start and exchange hellos..."
sleep 2.5

echo ""
echo "Typing message into Node A (destination C)..."
python -c "
import time
from node.mesh_node import MeshNode

# connect to Node A's socket to trigger send
import socket
from core.message import Message

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# deliver to B for forwarding to C with path starting at A
msg = Message(src='A', dst='C', payload='hello from node A')
msg.path = ['A']
sock.sendto(msg.to_json().encode('utf-8'), ('127.0.0.1', 5002))
"

sleep 2
echo "=== Local test completed ==="
