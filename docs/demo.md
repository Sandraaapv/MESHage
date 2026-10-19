# MESHage — Viva Demonstration Script & Presentation Guide

This document contains the step-by-step procedure, commands, talking points, and contingency fallbacks for demonstrating MESHage during the viva examination.

---

## 1. Pre-Demo Checklist (5 Minutes Before)

- [ ] **Hardware Setup**:
  - **Phone A** (Hotspot Host): Mobile data **OFF**, Hotspot **ON** (SSID: `MESHage-Net`, Password: `meshpassword`).
  - **Phone B** & **Phone C**: Connected to `MESHage-Net` Wi-Fi.
- [ ] **IP Verification**:
  - Phone A IP: `192.168.43.1` (Hotspot host default).
  - Phone B IP: Check via `ifconfig wlan0` or Android Wi-Fi settings (e.g., `192.168.43.2`).
  - Phone C IP: Check via `ifconfig wlan0` or Android Wi-Fi settings (e.g., `192.168.43.3`).
- [ ] **Config Check**:
  - Verify `config/nodes.json` on each phone matches the assigned IPs.
- [ ] **Laptop/Projector Setup**:
  - Laptop connected to projector.
  - Python virtual environment activated.
  - Verification tests passed: `python -m unittest discover -s tests -p "test_*.py"`.

---

## 2. Viva Presentation Flow (10-15 Minutes)

### Phase 1: High-Level Overview (1 Minute)
> **Spoken intro:**  
> *"Good morning/afternoon. Today we are demonstrating MESHage, an offline, decentralized peer-to-peer mesh messaging system designed for disaster relief, search-and-rescue, and cellular blackout scenarios.*  
> *MESHage requires no cellular towers, no internet access, and no central servers. Nodes discover each other over local wireless links, dynamically route messages across multiple hops, heal around hardware failures, and provide end-to-end AES-256-GCM authenticated encryption."*

---

### Phase 2: Live Network Radar on Projector (4 Minutes)

Launch the simulation server to give examiners a visual radar view of mesh behavior:

```powershell
python sim/server.py
```
*Open in browser:* **`http://localhost:5000/dashboard`**

#### Step-by-Step Actions:
1. **Explain the Mesh View**:
   - Point out the 30 active nodes, and explain link color coding:
     - **Green (Strong)**: $P_{succ} \ge 70\%$ ($>-75\text{ dBm}$)
     - **Amber (Weak)**: $30\% \le P_{succ} < 70\%$ (marginal SNR)
     - **Grey (Down)**: $P_{succ} < 30\%$ or endpoint offline
2. **Interactive Node Physics & Real-Time Channel Attenuation**:
   - Drag a node away from its cluster: show how its links transition from green to amber to disconnected as distance increases, computed live at 60 FPS using log-distance path loss:
     $$PL(d) = PL(d_0) + 10 \cdot n \cdot \log_{10}\left(\frac{d}{d_0}\right) + X_\sigma$$
3. **Path-Loss Exponent Slider**:
   - Drag the `Path Loss (n)` slider from `2.0` (Free space) to `3.2` (Urban) and `4.2` (High obstruction):
   - Explain how environmental obstruction shrinks communication range and forces messages onto multi-hop alternate paths.
4. **Point-to-Point Message Routing**:
   - Click a node to select it as Source (observe pulsing cyan halo).
   - Click a distant destination node: observe message particles travelling hop-by-hop along links and the final end-to-end path highlighted in electric cyan.
5. **Simulated Node Failure & Self-Healing**:
   - Click **"Kill Random Node"**: observe a node turning red with dashed border.
   - Point to the **Metrics Panel**: observe Active Nodes decrease and the **Recovery Time** metric activate.
   - Send another message through that sector: show the router automatically detecting the missed hellos and rerouting traffic around the failed node.
6. **Emergency Broadcast Alert**:
   - Click **"🚨 Emergency Alert"**: observe network-wide broadcast waves expanding radially across all clusters.

---

### Phase 3: Physical Multi-Phone Demo (5 Minutes)

Demonstrate physical multi-hop message relaying between actual Android smartphones using Termux.

#### Step 1: Start Nodes on Each Phone
In Termux on each phone:

- **Phone A (Hotspot Host)**:
  ```bash
  bash scripts/run_node.sh A
  ```
- **Phone B (Middle Relay)**:
  ```bash
  bash scripts/run_node.sh B
  ```
- **Phone C (End Client)**:
  ```bash
  bash scripts/run_node.sh C
  ```

*Topology configured in `config/nodes.json`:*  
**`Phone A` &harr; `Phone B` &harr; `Phone C`**  
*(Note: Phone A and Phone C do not list each other as direct neighbors; all communication MUST hop through Phone B).*

#### Step 2: Open Phone Web UI
On Phone A and Phone C, open their mobile browsers:
```text
http://localhost:5000
```
- Show the dark-theme mobile UI:
  - Header: Peer connection status dot (`ONLINE`).
  - Active Neighbors list: Phone A shows Phone B (`UP`, strong signal).
  - Phone C shows Phone B (`UP`, strong signal).

#### Step 3: Multi-Hop Unicast Messaging
1. On **Phone A**, select destination `C`, type:
   ```text
   "Status report: Team Alpha reached evacuation zone."
   ```
   and tap **Send**.
2. Observe:
   - On **Phone A**: Message marked sent with path `['A']`.
   - On **Phone B** (Terminal): Logs show:
     `[RELAYED] Forwarded message ... to 'C' at 192.168.43.3:5001`
   - On **Phone C**: Message pops up instantly with delivery notification:
     `Received from A via B (2 hops: A -> B -> C)`
3. Point out to examiners:
   *"Phone A could not reach Phone C directly; Phone B verified the packet integrity and relayed it along the optimal path."*

#### Step 4: Emergency Alert Broadcast
1. On **Phone A**, tap **"Emergency Alert"**, enter:
   ```text
   "FLASH FLOOD WARNING: RETREAT TO HIGH GROUND"
   ```
2. Observe both **Phone B** and **Phone C** sound/display the emergency warning banner simultaneously.

#### Step 5: Fault Tolerance & Recovery
1. Kill Node B by pressing `Ctrl+C` in Phone B's Termux.
2. In Phone A's UI or terminal, show that Node B's status changes to `DOWN` after missed hello timeout ($3 \times 2.5\text{s} = 7.5\text{s}$).

---

## 3. Contingency Fallbacks (If Hotspot Fails)

In a live viva, Wi-Fi interference, campus network security, or phone battery issues can happen. Use these pre-tested fallbacks:

### Fallback A: Standalone 3-Node Local Simulation (Zero Hardware Required)
If phones cannot connect to the hotspot, demonstrate multi-hop routing locally on the laptop:

```bash
python scripts/run_local_test.py
```
*or in bash:*
```bash
bash scripts/run_local_test.sh
```
- Spawns Node A (port 5001), Node B (port 5002), and Node C (port 5003) on `127.0.0.1`.
- Injects a multi-hop packet from A targeted at C.
- Demonstrates B relaying to C and C delivering the message with verified hop path.

### Fallback B: Laptop-Hosted Mobile Hotspot
If phone hotspot refuses to broadcast without cellular data:
1. Turn on **Mobile Hotspot** on the Windows/Linux laptop.
2. Connect all 3 phones to the laptop's Wi-Fi.
3. Check phone IPs via `arp -a` or hotspot status.
4. Run `bash scripts/run_node.sh` on each phone.

### Fallback C: Offline Canvas Dashboard Demo
If Termux is unavailable:
1. Run `python sim/server.py`.
2. Open `http://localhost:5000/dashboard`.
3. The browser dashboard includes full client-side emulation of all channel physics, flooding, Dijkstra routing, node kills, and emergency alerts.

---

## 4. Viva Q&A Cheat Sheet

| Likely Examiner Question | Recommended Response |
| :--- | :--- |
| **"Why did you choose UDP instead of TCP?"** | *"TCP requires a point-to-point connection-oriented handshake and maintain state per connection, which fails in intermittent, high-mobility mesh networks. UDP is connectionless and lightweight, allowing multi-hop packet forwarding and broadcast hellos with zero connection establishment overhead."* |
| **"How does MESHage prevent routing loops and broadcast storms?"** | *"Every message carries a unique UUID, a decremented Time-to-Live (TTL), and an appended path list. Each node maintains a bounded `SeenIdCache` with TTL expiration. If a message ID was already processed or if the next hop is already in `message.path`, the packet is dropped immediately."* |
| **"How does shortest path routing detect node failures?"** | *"Nodes broadcast periodic hello packets every 2.5 seconds. The `ShortestPathRouter` tracks missed hellos per neighbor. If a neighbor misses 3 consecutive hellos (7.5s), it is marked DOWN, its edges are pruned from the link-state graph, and Dijkstra recomputes an alternate route."* |
| **"How is replay protection handled without an NTP internet time server?"** | *"We use a sliding time window ($\pm 60\text{s}$) combined with AES-GCM 12-byte random nonces and message IDs cached in a memory-bounded `SeenIdCache`. Even if clocks drift slightly, duplicate IDs and nonces within the window are rejected."* |
| **"What are the channel model parameters?"** | *"We use a log-distance path loss model with log-normal shadowing: $PL(d) = PL(d_0) + 10n \log_{10}(d/d_0) + X_\sigma$, where $PL(d_0) = 40\text{ dBm}$ at $d_0 = 1\text{m}$, $n \in [2.0, 4.0]$, transmit power $+14\text{ dBm}$, and receiver sensitivity $-85\text{ dBm}$."* |
