# MESHage — Offline Mesh Messaging System

**MESHage** is an offline, peer-to-peer mesh messaging system engineered for communication in scenarios without internet access, cellular network coverage, or centralized infrastructure (e.g., natural disasters, search-and-rescue operations, remote wilderness exploration, and tactical communications).

Messages hop peer-to-peer between devices across dynamically discovered multi-hop routes using standard UDP sockets over local Wi-Fi or ad-hoc hotspots.

---

## Architecture Diagram

```text
+-----------------------------------------------------------------------------------+
|                                 APPLICATION LAYER                                 |
|   +------------------------------------+    +---------------------------------+   |
|   |  Phone Web UI (ui/phone/)          |    | Live Projector Radar Dashboard  |   |
|   |  Offline Dark Theme, Mobile-First  |    | (ui/dashboard/ - 60 FPS Canvas) |   |
|   +------------------------------------+    +---------------------------------+   |
|                                     \          /                                  |
+--------------------------------------\--------/-----------------------------------+
|                                       v      v                                    |
|                             TRANSPORT & API LAYER                                 |
|   +------------------------------------+    +---------------------------------+   |
|   |  Flask REST & SSE Server           |    |  UDP Socket Listener & Sender   |   |
|   |  (node/api.py, sim/server.py)      |    |  (node/mesh_node.py - Port 5001)|   |
|   +------------------------------------+    +---------------------------------+   |
|                                     \          /                                  |
+--------------------------------------\--------/-----------------------------------+
|                                       v      v                                    |
|                              CORE ROUTING LAYER                                   |
|   +---------------------------------------------------------------------------+   |
|   |                       core/router.py & core/message.py                    |   |
|   |  * FloodingRouter      : Bounded broadcast flooding with TTL decrement    |   |
|   |  * ShortestPathRouter  : Dynamic link-state Dijkstra with hello exchange  |   |
|   |  * GossipRouter        : Probabilistic forwarding (p = 0.6)               |   |
|   |  * SeenIdCache         : Bounded LRU cache with time-to-live (TTL) expiry |   |
|   |  * Loop Prevention     : Path tracking & exclusion of visited hops        |   |
|   +---------------------------------------------------------------------------+   |
|                                       |                                           |
+---------------------------------------|-------------------------------------------+
|                                       v                                           |
|                           SECURITY & CRYPTO LAYER                                 |
|   +---------------------------------------------------------------------------+   |
|   |                       core/crypto.py (AES-256-GCM)                        |   |
|   |  * Authenticated Encryption : Confidentiality & tamper-proof integrity    |   |
|   |  * Replay Protection        : Sliding time window (+-60s) + random nonces|   |
|   +---------------------------------------------------------------------------+   |
|                                       |                                           |
+---------------------------------------|-------------------------------------------+
|                                       v                                           |
|                         PHYSICAL & SIMULATION LAYER                               |
|   +---------------------------------------------------------------------------+   |
|   |                       sim/channel.py & sim/network.py                     |   |
|   |  * Log-Distance Path Loss   : PL(d) = PL(d0) + 10*n*log10(d/d0)           |   |
|   |  * Log-Normal Shadowing     : Gaussian zero-mean random fading X_sigma    |   |
|   |  * Logistic Packet Success  : P(succ) = 1 / (1 + exp(-0.5 * (Prx - S)))   |   |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+
```

---

## Packet Traversal & Self-Healing Flow

```text
[Node A]                       [Node B (Relay)]                     [Node C (Relay)]                  [Node D (Target)]
   |                                  |                                    |                                 |
   |--- 1. Periodic Hello (TTL=1) --->|                                    |                                 |
   |                                  |<--- Periodic Hello (TTL=1) --------|                                 |
   |<-- 2. Link State Learned --------|--- Link State Learned ------------>|<--- Periodic Hello (TTL=1) -----|
   |                                  |                                    |                                 |
   |=== 3. Chat: "Hello D" ===========>|                                    |                                 |
   |    (Path: [A], TTL: 10)          |=== 4. Forwarded: "Hello D" =======>|                                 |
   |                                  |    (Path: [A, B], TTL: 9)          |=== 5. Delivered: "Hello D" ====>|
   |                                  |                                    |    (Path: [A, B, C], TTL: 8)    |
   |                                  |                                    |                                 |
   |                             [NODE B FAILS]                            |                                 |
   |                                    X                                  |                                 |
   |--- 6. Hellos Missed (x3) -------->X                                   |                                 |
   |    [Mark B as DOWN]              X                                    |                                 |
   |    [Dijkstra Recomputes]         X                                    |                                 |
   |                                                                       |                                 |
   |=== 7. Rerouted via Alternate Path E =================================>|================================>|
```

---

## Quick Start & Verification

### 1. Run Core Unit Tests
Execute the full test suite covering flooding, shortest path, hello timeouts, replay protection, and authenticated encryption:
```bash
python -m unittest discover -s tests -p "test_*.py"
```

### 2. Run Local 3-Node Test
Run a complete 3-node loopback mesh (`A <---> B <---> C`) on your local machine:
```bash
python scripts/run_local_test.py
```
*or in bash:*
```bash
bash scripts/run_local_test.sh
```

---

## Simulation & Interactive Projector Radar

### 1. Interactive Projector Radar Dashboard
Start the real-time simulation server with Server-Sent Events (SSE):
```bash
python sim/server.py
```
Open **`http://localhost:5000/dashboard`** in any web browser.
- **60 FPS Canvas Graph**: Renders 15 to 50 nodes with dynamic link quality (Green $\ge 70\%$, Amber $30\% - 70\%$, Grey $< 30\%$).
- **Live Physics**: Drag any node to update link SNR and topology in real time.
- **Path-Loss Slider**: Adjust channel exponent $n \in [2.0, 5.0]$ to simulate Free Space, Suburban, Urban, and High-Obstruction environments.
- **Interactions**: Click 2 nodes to route packets with traveling particle animations; click a node to kill/revive it.
- **Projector KPI Cards**: Live delivery rate, average delay, packets per message, active nodes, and failure recovery time with sparklines.
- **Emergency Alert**: Network-wide broadcast waves sweeping across mesh clusters.

### 2. Standalone Simulation Demos
- **Channel Characteristics Plot**:
  ```bash
  python sim/plot_channel.py --no-show
  ```
  Generates `results/channel_plots.png` showing received power (dBm) and packet success probability vs distance for $n \in \{2, 3, 4\}$.
- **Flooding Path Demo**:
  ```bash
  python sim/demo.py 30 --no-show
  ```
  Generates `results/demo_path.png` highlighting multi-hop packet propagation across 10 random nodes.
- **Fault Recovery & Self-Healing Demo**:
  ```bash
  python sim/demo_heal.py --no-show
  ```
  Generates `results/demo_heal.png` demonstrating node failure mid-delivery and automatic rerouting via hello timeout detection.

---

## Automated Experiments

Run the comprehensive simulation benchmark suite:
```bash
python experiments/run_all.py
```
Executes 4 experiments with 20 trials each, saving CSV data and publication-ready graphs in `results/`:
1. **Experiment 1: Routing Protocol Comparison** (`results/exp1_routing_comparison.png`, `exp1_routing_comparison.csv`)
   - Compares Flooding, Shortest Path (Dijkstra), and Gossip ($p=0.6$) across Delivery Rate (%), Average Delay (hops), and Packet Overhead (packets/msg).
2. **Experiment 2: Network Scalability** (`results/exp2_scalability.png`, `exp2_scalability.csv`)
   - Evaluates Flooding vs Shortest Path across 5, 10, 20, and 50 nodes, demonstrating that Shortest Path scales with $O(H)$ overhead while Flooding exhibits exponential packet growth.
3. **Experiment 3: Distance and Path Loss** (`results/exp3_path_loss.png`, `exp3_path_loss.csv`)
   - Measures single-hop link success and multi-hop delivery rates across node spacings from $10\text{m}$ to $50\text{m}$ under path-loss exponents $n \in \{2, 3, 4\}$.
4. **Experiment 4: Fault Recovery & Node Failures** (`results/exp4_failure.png`, `exp4_failure.csv`)
   - Measures recovery time and delivery success when 1, 2, or 3 critical relay nodes are killed simultaneously.

---

## Phone setup

Follow these numbered steps to deploy MESHage nodes across physical Android smartphones using Termux:

1. **Install Termux from F-Droid**
   - Download and install Termux from **[F-Droid](https://f-droid.org/packages/com.termux/)**.
   - *Important:* Do **not** install Termux from the Google Play Store; the Play Store build is deprecated and cannot install packages due to Android target SDK restrictions.

2. **Run the setup script**
   - Open Termux on each phone with an active internet connection.
   - Clone the repository and execute the setup script:
     ```bash
     pkg install -y git
     git clone https://github.com/Sandraaapv/MESHage.git
     cd MESHage
     bash scripts/setup_termux.sh
     ```
   - This script installs Python, Git, network tools (`iproute2`, `net-tools`), and installs required Python packages (`flask`, `cryptography`).

3. **Start the hotspot with mobile data off**
   - Choose one phone to serve as the local Wi-Fi Hotspot (e.g., Phone A).
   - Turn **OFF** Cellular / Mobile Data on this phone.
   - Turn **ON** Personal Hotspot / Portable Wi-Fi Hotspot.
   - This establishes an offline local wireless network (WLAN) without consuming cellular data or requiring internet access.

4. **Join the other phones**
   - On the remaining phones (Phone B, Phone C, etc.), enable Wi-Fi.
   - Connect to Phone A's hotspot network.

5. **Find IPs**
   - Identify each phone's local IP address on the hotspot network:
     - **Phone A (Hotspot Host):** Almost always `192.168.43.1`.
     - **Connected Phones (Clients):** Run this command inside Termux:
       ```bash
       ifconfig wlan0
       ```
       or check Android **Settings &rarr; Wi-Fi &rarr; [Connected Network] &rarr; Advanced &rarr; IP address** (typically `192.168.43.x`).
     - Alternatively, Phone A can view all assigned client IP addresses in **Settings &rarr; Hotspot & Tethering &rarr; Connected Devices**.

6. **Edit the config**
   - Create your local network topology configuration:
     ```bash
     cp config/nodes.example.json config/nodes.json
     nano config/nodes.json
     ```
   - Enter each phone's actual IP address and list its direct neighbors (for example, a linear mesh `A <---> B <---> C` where A only knows B, B knows A and C, and C only knows B).

7. **Start the node**
   - On each phone in Termux, launch the node runner script:
     ```bash
     bash scripts/run_node.sh
     ```
   - The script will automatically detect your phone's IP address, ask for your node name (e.g., `A`, `B`, or `C`), load the corresponding neighbors from `config/nodes.json`, and start the UDP listener and API server.
   - *Tip:* You can also pass the node name directly:
     ```bash
     bash scripts/run_node.sh A
     ```

8. **Open the URL**
   - Open Chrome, Firefox, or any web browser on the phone and navigate to:
     ```text
     http://localhost:5000
     ```
   - The offline phone UI will load, showing live peer connectivity, chat messaging, emergency broadcast alerts, and multi-hop routing paths.

---

## Troubleshooting

### 1. Phones cannot reach each other
- **AP Isolation / Client Isolation:** Some Android hotspot implementations prevent connected Wi-Fi clients from communicating directly with each other or with the host phone.
  - *Fix:* Open Hotspot settings and verify that options such as "AP Isolation" or "Client Isolation" are disabled. If your phone's firmware forces AP isolation, designate a different phone as the hotspot, or connect all phones to a portable battery-powered Wi-Fi travel router.
- **Dynamic IP Changes:** Android's DHCP server may assign a new IP address if a phone disconnects and reconnects. Always re-verify IP addresses using `bash scripts/run_node.sh` or `ifconfig wlan0` and update `config/nodes.json`.
- **Neighbor Whitelist:** MESHage nodes enforce a neighbor whitelist for secure multi-hop routing. If Node A receives a packet from an IP/port not present in its configured `neighbors` list, it will drop the packet. Ensure bidirectional configuration (if A lists B, B must also list A).

### 2. Termux paused in the background
- **Android Battery Optimization / Doze Mode:** Android aggressively suspends background apps and terminates network sockets when the screen turns off or another app takes focus.
  - *Fix 1:* Acquire a wake lock in Termux by running:
    ```bash
    termux-wake-lock
    ```
    This displays a persistent notification in your status bar keeping Termux active.
  - *Fix 2:* Open Android **Settings &rarr; Apps &rarr; Termux &rarr; Battery** and set to **Unrestricted** (or disable "Battery Optimization").
  - *Fix 3:* Disable "Pause app activity if unused" under Termux app permissions.

### 3. Hotspot refuses to start without mobile data
- **Carrier / OEM Hotspot Restrictions:** Certain carrier firmware prevents toggling the Hotspot switch if mobile data is disabled or if no SIM card is present.
  - *Workaround 1:* Turn on Mobile Data and enable Hotspot; once the hotspot is broadcasting, immediately toggle Mobile Data off. On most Android devices, the Wi-Fi AP remains active.
  - *Workaround 2:* Enable Airplane Mode first, then turn on Wi-Fi and Portable Hotspot manually.
  - *Workaround 3:* Use Wi-Fi Direct or an offline Wi-Fi tethering utility from F-Droid (such as *NetShare* or *WiFi Hotspot*).

### 4. Firewall & VPN issues
- **Local VPNs & Ad-Blockers:** Apps like AdGuard, Blokada, NetGuard, TrackerControl, or WireGuard intercept all network traffic via a local Android VPN tunnel (`tun0`). This frequently blocks or drops local UDP packets on port `5001`.
  - *Fix:* Temporarily pause or bypass all local VPN and ad-blocker apps while running MESHage.
- **Private DNS:** If Android Private DNS is configured in strict mode (e.g., using Cloudflare or NextDNS), DNS lookups will fail on an offline Wi-Fi network and can stall local socket bindings.
  - *Fix:* Set Android **Settings &rarr; Network & internet &rarr; Private DNS** to **Off** or **Automatic**.
- **Port Conflicts:** Ensure port `5001` (UDP mesh) and port `5000` (HTTP Web UI) are not in use by other services on the device.

---

## Demonstration Script

For a detailed, step-by-step presentation guide for examiners during the viva (including live screen setups, talking points, and contingency fallbacks), see **[docs/demo.md](file:///d:/Sandra/projects/MESHage/docs/demo.md)**.
