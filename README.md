# MESHage — Offline Mesh Messaging System

**MESHage** is an offline, peer-to-peer mesh messaging system designed for situations where there is **no internet, no cellular network, and no central router or server**. 

Whether it's a natural disaster, search-and-rescue mission, a remote trek, or a campus network blackout, MESHage turns everyday Android smartphones and laptops into wireless relay nodes. Messages hop from device to device across dynamically discovered routes using standard UDP sockets over local Wi-Fi hotspots.

---

## How It Works

```text
[Phone A]                       [Phone B (Relay)]                     [Phone C (Target)]
   |                                    |                                     |
   |--- 1. Periodic Hello (TTL=1) ----->|                                     |
   |                                    |<--- Periodic Hello (TTL=1) ---------|
   |<-- 2. Link State Learned ----------|--- Link State Learned ------------->|
   |                                    |                                     |
   |=== 3. Chat: "Hello C" ============>|                                     |
   |    (Path: [A], TTL=10)             |=== 4. Forwarded: "Hello C" ========>|
   |                                    |    (Path: [A, B], TTL=9)            |=== 5. Delivered: "Hello C"
   |                                    |                                     |    (Path: [A, B, C])
   |                                    |                                     |
   |                               [B GOES OFFLINE]                           |
   |                                    X                                     |
   |--- 6. Missed 3 Hellos ------------>X                                     |
   |    [Mark B as DOWN]                                                      |
   |    [Dijkstra recalculates]                                               |
   |=== 7. Automatically reroutes through alternate Node D ==================>|
```

1. **Self-Discovery via Hellos:** Every 2.5 seconds, each node broadcasts a short 1-hop UDP "Hello" packet to its configured radio neighbors. Nodes learn who is around them and build a local topology map.
2. **Shortest-Path Routing (Dijkstra):** If Phone A wants to message Phone C, but is only in radio range of Phone B, Phone B automatically acts as a router and forwards the packet.
3. **Self-Healing:** If a middle node shuts down or walks out of range, the mesh notices missed hellos within seconds, marks the node down, and recalculates alternate routes.
4. **End-to-End Encryption:** All chat payloads are authenticated and encrypted using AES-256-GCM with sliding-window replay protection.
5. **No Special Hardware:** Uses ordinary Wi-Fi chips on unmodified Android phones (running via Termux) and laptops.

---

## Architecture at a Glance

```text
+-----------------------------------------------------------------------------------+
|                                 APPLICATION LAYER                                 |
|   +------------------------------------+    +---------------------------------+   |
|   |  Phone Web UI (ui/phone/)          |    | Live Projector Radar Dashboard  |   |
|   |  Dark-mode, mobile-first PWA       |    | (ui/dashboard/ - 60 FPS Canvas) |   |
|   +------------------------------------+    +---------------------------------+   |
|                                     \          /                                  |
|                                      v        v                                   |
|                             TRANSPORT & API LAYER                                 |
|   +------------------------------------+    +---------------------------------+   |
|   |  Flask REST & SSE Server           |    |  UDP Socket Listener & Sender   |   |
|   |  (node/api.py, sim/server.py)      |    |  (node/mesh_node.py, port 5001) |   |
|   +------------------------------------+    +---------------------------------+   |
|                                      \        /                                   |
|                                       v      v                                    |
|                              CORE ROUTING LAYER                                   |
|   +---------------------------------------------------------------------------+   |
|   |  * ShortestPathRouter  : Dynamic link-state Dijkstra with hello exchange  |   |
|   |  * FloodingRouter      : Bounded broadcast flooding with TTL decrement    |   |
|   |  * GossipRouter        : Probabilistic forwarding (p = 0.6)               |   |
|   |  * SeenIdCache         : Bounded LRU deduplication cache (prevents loops) |   |
|   +---------------------------------------------------------------------------+   |
|                                       |                                           |
|                                       v                                           |
|                           SECURITY & CRYPTO LAYER                                 |
|   +---------------------------------------------------------------------------+   |
|   |  * Authenticated Encryption : AES-256-GCM confidentiality & integrity     |   |
|   |  * Replay Protection        : Sliding time window (+-60s) + random nonces|   |
|   +---------------------------------------------------------------------------+   |
|                                       |                                           |
|                                       v                                           |
|                         PHYSICAL & SIMULATION LAYER                               |
|   +---------------------------------------------------------------------------+   |
|   |  * Log-Distance Path Loss   : PL(d) = PL(d0) + 10*n*log10(d/d0)           |   |
|   |  * Log-Normal Shadowing     : Gaussian zero-mean random fading X_sigma    |   |
|   |  * Logistic Packet Success  : P(succ) = 1 / (1 + exp(-0.5 * (Prx - S)))   |   |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+
```

---

## Quick Start on Your Computer

### 1. Run the Test Suite
Make sure everything passes before doing live demos:
```bash
python -m unittest discover -s tests -p "test_*.py"
```

### 2. Run a Local 3-Node Test (Single Machine)
You can test multi-hop routing right on your laptop without any phones:
```bash
python scripts/run_local_test.py
```
This spawns Nodes A, B, and C in a chain (`A <-> B <-> C`) on localhost ports 5001, 5002, 5003 and confirms that A can message C through B.

---

## Live Projector Radar Dashboard (For Presentations & Viva)

During a viva or project demonstration, you can run the interactive simulation server on your laptop connected to a projector:

```bash
python sim/server.py
```
Open **`http://localhost:5000/dashboard`** in your browser.

- **Live 60 FPS Canvas:** Displays 30 nodes with dynamic link quality (Green $\ge 70\%$, Amber $30\% - 70\%$, Grey $< 30\%$).
- **Interactive Physics:** Drag any node to see links transition from green to amber to disconnected as distance increases in real time.
- **Path-Loss Slider:** Adjust the environmental path loss exponent ($n \in [2.0, 5.0]$) to simulate free space, suburban, urban, and high-obstruction buildings.
- **Failure & Self-Healing:** Click **"Kill Random Node"** to knock out a relay and watch the metrics track how quickly the mesh discovers alternate routes.
- **Emergency Alert:** Click **"🚨 Emergency Alert"** to trigger a broadcast wave sweeping across all nodes.

---

## Running on Physical Android Phones (Step-by-Step)

Follow these steps to run MESHage across 2 or 3 Android phones:

### Step 1: Install Termux on Each Phone
- Download Termux from **[F-Droid](https://f-droid.org/packages/com.termux/)**.  
  *(Do not use Google Play Store; that version is outdated and cannot install packages).*

### Step 2: Run Setup on Each Phone
Open Termux with an active internet connection (just for the initial install) and run:
```bash
pkg update -y && pkg install -y git && git clone https://github.com/Sandraaapv/MESHage.git && cd MESHage && bash scripts/setup_termux.sh
```
This installs Python, Git, network tools, Flask, and Cryptography.

### Step 3: Connect Phones to Offline Wi-Fi
1. Pick **Phone A** to be the hotspot:
   - Turn **OFF Mobile Data**.
   - Turn **ON Portable Hotspot**.
2. On **Phone B** and **Phone C**:
   - Turn on Wi-Fi and connect to Phone A's hotspot.
   *(No internet is needed—the phones communicate purely over the local Wi-Fi network).*

### Step 4: Find Each Phone's IP Address
- **Phone A (Hotspot Host):** Usually `192.168.43.1` (or check inside Termux when starting).
- **Phone B & C:** 
  - Look in Android **Settings &rarr; Wi-Fi &rarr; Connected Network &rarr; Details** to see the IP.
  - Or run this one-liner in Termux:
    ```bash
    python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('192.168.43.1', 80)); print(s.getsockname()[0]); s.close()"
    ```

### Step 5: Configure `config/nodes.json`
On each phone, edit the configuration file:
```bash
cp config/nodes.example.json config/nodes.json
nano config/nodes.json
```

**For a 2-phone setup (A <-> B):**
```json
{
  "routing_mode": "shortest",
  "nodes": {
    "A": {
      "ip": "PHONE_A_IP",
      "port": 5001,
      "api_port": 5000,
      "neighbors": ["PHONE_B_IP:5001"]
    },
    "B": {
      "ip": "PHONE_B_IP",
      "port": 5001,
      "api_port": 5000,
      "neighbors": ["PHONE_A_IP:5001"]
    }
  }
}
```

**For a 3-phone linear mesh (A <-> B <-> C):**
```json
{
  "routing_mode": "shortest",
  "nodes": {
    "A": {
      "ip": "192.168.43.1",
      "port": 5001,
      "api_port": 5000,
      "neighbors": ["PHONE_B_IP:5001"]
    },
    "B": {
      "ip": "PHONE_B_IP",
      "port": 5001,
      "api_port": 5000,
      "neighbors": ["192.168.43.1:5001", "PHONE_C_IP:5001"]
    },
    "C": {
      "ip": "PHONE_C_IP",
      "port": 5001,
      "api_port": 5000,
      "neighbors": ["PHONE_B_IP:5001"]
    }
  }
}
```
*(In nano: press `Ctrl + O` then `Enter` to save, `Ctrl + X` to exit).*

### Step 6: Start the Node
- On Phone A: `bash scripts/run_node.sh A`
- On Phone B: `bash scripts/run_node.sh B`
- On Phone C: `bash scripts/run_node.sh C`

### Step 7: Open the Chat UI
Open Chrome or Firefox on your phone and go to:
```text
http://localhost:5000
```
The dark-mode mobile web UI will load with live peer detection, multi-hop routing, recipient chips, and emergency SOS broadcast.

---

## Frequently Asked Questions

### 1. How do I add another phone? How do other phones know it exists?
You don't need to rebuild or touch all existing phones to add a new device:
1. Connect the new phone (e.g., **Phone D**) to the Wi-Fi hotspot.
2. Give Phone D an entry in `config/nodes.json` and point it to **at least one** existing phone it can reach (e.g., Phone C).
3. On Phone C, add Phone D to its `neighbors` list.
4. **How the rest of the network learns about D:**
   Every 2.5 seconds, nodes exchange link-state Hello packets containing their active neighbor lists. When Phone C broadcasts its hello, Phone B hears about D, and Phone A hears from B. Phone A automatically calculates the multi-hop path: `A -> B -> C -> D` without Phone A ever needing to know Phone D's IP directly!

### 2. What is the maximum number of phones that can connect?
- **Protocol Limit:** The MESHage routing engine uses bounded LRU deduplication caches (up to 2,000 active message IDs) and has been benchmarked in simulations up to **50+ active nodes** with sub-second delivery.
- **Physical Hotspot Limit:** Standard smartphone Wi-Fi hotspot chipsets (Qualcomm/MediaTek) typically limit simultaneous connections to **8 to 10 devices** per hotspot.
- **Scaling Larger:** To scale beyond 10 physical phones in the real world, you can connect phones across multiple ad-hoc Wi-Fi cells, Wi-Fi Direct groups, or small battery-powered travel routers, allowing chains of **30–50+ phones** to hop messages across kilometers.

### 3. Why Python and not Java?
- **Single Cross-Platform Codebase:** The same core router, packet format, and crypto runs on Android phones (via Termux), laptops, and Raspberry Pis without having to build and maintain a separate Android Studio Java APK and Desktop Java project.
- **Zero Compilation Friction:** Code updates can be pushed and pulled via `git pull` in 2 seconds directly in the field, without building and reinstalling `.apk` files on each device.
- **Bypasses Android Background Restrictions:** Native Android Java apps get aggressively killed by Android's Doze battery saver after 60 seconds of background socket activity. Termux runs standard POSIX Berkeley UDP sockets directly on the Linux kernel level with a wake lock.
- **Scientific Simulation:** Python's scientific ecosystem (`matplotlib`, `numpy`, `simpy`) made it simple to run automated multi-trial benchmarks and generate publication-ready plots.

---

## Troubleshooting Guide

1. **"Permission denied" when running `ifconfig`:**
   - Android 10+ restricts `ifconfig` for non-root apps. Check your IP directly in **Settings &rarr; Wi-Fi &rarr; Details**, or run `bash scripts/run_node.sh` which automatically uses Python socket inspection to find your IP.
2. **Packets showing `[DROPPED] Ignored packet from unlisted sender`:**
   - MESHage uses a neighbor whitelist for secure multi-hop routing. If Phone B receives a packet from `10.91.24.43`, make sure that exact IP is listed under Phone B's `neighbors` in `config/nodes.json`.
3. **Termux sleeping when screen turns off:**
   - In Termux, run `termux-wake-lock`. Also go to Android **Settings &rarr; Apps &rarr; Termux &rarr; Battery** and set to **Unrestricted**.
4. **Phones cannot ping each other on Hotspot (AP Isolation):**
   - Some carrier phones block connected hotspot devices from talking to each other. Check Hotspot settings and disable "AP Isolation" or "Client Isolation", or designate a different phone as the hotspot.
5. **VPNs or Ad-Blockers:**
   - Disable local VPN apps (AdGuard, Blokada, NetGuard) because they capture network sockets and block incoming UDP packets on port 5001.

---

## Automated Simulation Benchmarks

To reproduce the four research benchmarks:
```bash
python experiments/run_all.py
```
This runs 20 trials across each condition and saves graphs in `results/`:
1. `exp1_routing_comparison.png` — Flooding vs Shortest Path vs Gossip across delivery rate, hops, and packet overhead.
2. `exp2_scalability.png` — Overhead scaling across 5, 10, 20, and 50 nodes.
3. `exp3_path_loss.png` — Delivery success vs distance for path-loss exponents $n \in \{2, 3, 4\}$.
4. `exp4_failure.png` — Recovery time and self-healing when relay nodes fail.
