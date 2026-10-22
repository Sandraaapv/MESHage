/**
 * MESHage Phone UI Application
 * Offline-first, mobile mesh messenger
 * Vanilla JavaScript, SSE live stream & local REST API
 */

(function () {
  "use strict";

  // Application State
  const state = {
    nodeName: "Node",
    port: 5000,
    neighbors: [],
    messages: new Map(), // id -> message object
    outgoingStatuses: new Map(), // id -> { status, path, hops, error }
    peerStatuses: new Map(), // name -> "UP" | "DOWN"
    peerHops: new Map(), // name -> number
    selectedDst: "ALL",
    sosTimer: null,
    sosHoldDuration: 1500, // 1.5 seconds
    vibrationInterval: null,
  };

  // DOM Elements
  const els = {
    connectionDot: document.getElementById("connectionDot"),
    nodeNameHeader: document.getElementById("nodeNameHeader"),
    openNeighborsBtn: document.getElementById("openNeighborsBtn"),
    neighborCountText: document.getElementById("neighborCountText"),
    meshBannerCard: document.getElementById("meshBannerCard"),
    bannerStatusText: document.getElementById("bannerStatusText"),
    bannerRouteTag: document.getElementById("bannerRouteTag"),
    bannerTitle: document.getElementById("bannerTitle"),
    bannerSubtitle: document.getElementById("bannerSubtitle"),
    bannerPeersRow: document.getElementById("bannerPeersRow"),
    bannerHint: document.getElementById("bannerHint"),
    chatContainer: document.getElementById("chatContainer"),
    emptyHint: document.getElementById("emptyHint"),
    destChipsContainer: document.getElementById("destChipsContainer"),
    destChipsScroll: document.getElementById("destChipsScroll"),
    messageInput: document.getElementById("messageInput"),
    sendBtn: document.getElementById("sendBtn"),
    sosWrapper: document.getElementById("sosWrapper"),
    sosBtn: document.getElementById("sosBtn"),
    bottomSheetBackdrop: document.getElementById("bottomSheetBackdrop"),
    closeNeighborsBtn: document.getElementById("closeNeighborsBtn"),
    neighborsList: document.getElementById("neighborsList"),
    emergencyOverlay: document.getElementById("emergencyOverlay"),
    emergencySender: document.getElementById("emergencySender"),
    emergencyPayload: document.getElementById("emergencyPayload"),
    emergencyMeta: document.getElementById("emergencyMeta"),
    ackEmergencyBtn: document.getElementById("ackEmergencyBtn"),
    toastContainer: document.getElementById("toastContainer"),
  };

  // SVG Icons
  const icons = {
    checkSingle: '<polyline points="20 6 9 17 4 12"></polyline>',
    checkDouble: '<path d="M18 6L7 17l-5-5"></path><path d="M22 10l-7.5 7.5-1.5-1.5"></path>',
    hop: '<polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline>',
  };

  // =========================================================
  // API Fetching & State
  // =========================================================
  async function fetchState() {
    try {
      const res = await fetch("/api/state");
      if (!res.ok) throw new Error("Failed to fetch state");
      const data = await res.json();

      state.nodeName = data.node_name || "Node";
      state.port = data.port || 5000;
      const previousNeighbors = state.neighbors || [];
      state.neighbors = data.neighbors || [];

      // Check for peer status transitions (e.g. peer dropped mid-conversation)
      checkPeerTransitions(previousNeighbors, state.neighbors);

      updateHeader();
      updateBanner();
      updateRecipientChips();
      updateNeighborsUI();
    } catch (err) {
      console.warn("Error fetching state:", err);
    }
  }

  async function fetchMessages() {
    try {
      const res = await fetch("/api/messages");
      if (!res.ok) throw new Error("Failed to fetch messages");
      const messages = await res.json();
      messages.forEach((m) => {
        state.messages.set(m.id, m);

        // Learn peer hops from incoming message paths
        if (m.path && Array.isArray(m.path) && m.src && m.src !== state.nodeName) {
          const hops = Math.max(1, m.path.length - 1);
          state.peerHops.set(m.src, hops);
        }

        // If outgoing message from this node, mark delivered if delivered locally/sent
        if (m.src === state.nodeName && !state.outgoingStatuses.has(m.id)) {
          const hops = m.path ? Math.max(1, m.path.length - 1) : 1;
          state.outgoingStatuses.set(m.id, {
            status: "delivered",
            path: m.path || [state.nodeName],
            hops: hops,
          });
        }
      });
      renderAllMessages();
    } catch (err) {
      console.warn("Error fetching messages:", err);
    }
  }

  // =========================================================
  // Peer Transitions (System Line on Peer Drop)
  // =========================================================
  function checkPeerTransitions(oldNeighbors, newNeighbors) {
    const oldMap = new Map();
    oldNeighbors.forEach((n) => oldMap.set(n.name, n.status));

    newNeighbors.forEach((n) => {
      const prevStatus = state.peerStatuses.get(n.name) || oldMap.get(n.name);
      if (prevStatus === "UP" && n.status === "DOWN") {
        appendSystemLine(`${n.name} went offline, rerouting`);
      }
      state.peerStatuses.set(n.name, n.status);

      // Default direct neighbors to 1 hop if UP
      if (n.status === "UP" && !state.peerHops.has(n.name)) {
        state.peerHops.set(n.name, 1);
      }
    });
  }

  function appendSystemLine(text) {
    const line = document.createElement("div");
    line.className = "system-line";
    line.textContent = text;
    els.chatContainer.appendChild(line);
    scrollToBottom();
  }

  // =========================================================
  // 1. Header & Live Peer Count
  // =========================================================
  function updateHeader() {
    els.nodeNameHeader.textContent = `MESHage (${state.nodeName})`;
    const upNeighbors = state.neighbors.filter((n) => n.status === "UP");
    const count = upNeighbors.length;
    els.neighborCountText.textContent = `${count} ${count === 1 ? "peer" : "peers"}`;
  }

  // =========================================================
  // 2. Compact Mint Node Card & Peer Circles
  // =========================================================
  function updateBanner() {
    if (!els.bannerTitle) return;
    els.bannerTitle.textContent = `Node ${state.nodeName}`;
    els.bannerStatusText.textContent = "Mesh online";
    els.bannerRouteTag.textContent = "Ready";
    els.bannerSubtitle.textContent = "Wi-Fi UDP port 5001 \u2022 AES-256 encrypted";

    // Gather unique known peers
    const knownPeers = new Map();

    state.neighbors.forEach((n) => {
      knownPeers.set(n.name, {
        name: n.name,
        status: n.status,
        hops: state.peerHops.get(n.name) || 1,
      });
    });

    // Also include any peers seen from message history
    state.peerHops.forEach((hops, name) => {
      if (name !== state.nodeName && !knownPeers.has(name)) {
        knownPeers.set(name, {
          name: name,
          status: state.peerStatuses.get(name) || "UP",
          hops: hops,
        });
      }
    });

    let html = `
      <div class="banner-peer-item" title="Your Node (${state.nodeName})">
        <div class="banner-peer-circle is-you">
          <span>${escapeHtml(state.nodeName.slice(0, 2).toUpperCase())}</span>
        </div>
        <span class="banner-peer-label">You</span>
      </div>
    `;

    if (knownPeers.size === 0) {
      els.bannerHint.style.display = "block";
    } else {
      els.bannerHint.style.display = "none";

      knownPeers.forEach((p) => {
        const isUp = p.status === "UP";
        const circleClass = isUp ? "is-peer" : "is-offline";
        const hopText = isUp ? `${p.hops} ${p.hops === 1 ? "hop" : "hops"}` : "Offline";

        html += `
          <div class="banner-peer-item" data-peer="${escapeHtml(p.name)}" title="Select Node ${escapeHtml(p.name)}">
            <div class="banner-peer-circle ${circleClass}">
              <span>${escapeHtml(p.name.slice(0, 2).toUpperCase())}</span>
            </div>
            <span class="banner-peer-label">${hopText}</span>
          </div>
        `;
      });
    }

    els.bannerPeersRow.innerHTML = html;

    // Tapping peer circle selects that peer
    els.bannerPeersRow.querySelectorAll(".banner-peer-item[data-peer]").forEach((item) => {
      item.addEventListener("click", () => {
        const peer = item.getAttribute("data-peer");
        if (peer) selectRecipient(peer);
      });
    });
  }

  // =========================================================
  // 5. Recipient Selector Chips
  // =========================================================
  function updateRecipientChips() {
    const knownPeers = new Set();
    state.neighbors.forEach((n) => knownPeers.add(n.name));
    state.peerHops.forEach((_, name) => {
      if (name !== state.nodeName) knownPeers.add(name);
    });

    let html = `
      <button type="button" class="dest-chip ${state.selectedDst === "ALL" ? "active" : ""}" data-dst="ALL">
        Everyone
      </button>
    `;

    Array.from(knownPeers).sort().forEach((name) => {
      const isActive = state.selectedDst === name;
      html += `
        <button type="button" class="dest-chip ${isActive ? "active" : ""}" data-dst="${escapeHtml(name)}">
          Node ${escapeHtml(name)}
        </button>
      `;
    });

    els.destChipsScroll.innerHTML = html;

    // Attach click events to chips
    els.destChipsScroll.querySelectorAll(".dest-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const dst = chip.getAttribute("data-dst");
        if (dst) selectRecipient(dst);
      });
    });
  }

  function selectRecipient(dst) {
    state.selectedDst = dst;
    els.destChipsScroll.querySelectorAll(".dest-chip").forEach((chip) => {
      if (chip.getAttribute("data-dst") === dst) {
        chip.classList.add("active");
        chip.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
      } else {
        chip.classList.remove("active");
      }
    });
    els.messageInput.focus();
  }

  // =========================================================
  // 3 & 4. Chat Rendering & Messages
  // =========================================================
  function renderAllMessages() {
    if (state.messages.size === 0) {
      els.emptyHint.style.display = "block";
      return;
    }

    els.emptyHint.style.display = "none";
    const existingIds = new Set();
    document.querySelectorAll(".message-row[data-id], .emergency-broadcast-card[data-id]").forEach((el) => {
      existingIds.add(el.getAttribute("data-id"));
    });

    const sorted = Array.from(state.messages.values()).sort(
      (a, b) => (a.timestamp || 0) - (b.timestamp || 0)
    );

    sorted.forEach((msg) => {
      if (!existingIds.has(msg.id)) {
        appendMessageElement(msg, false);
      }
    });

    scrollToBottom();
  }

  function appendMessageElement(msg, autoScroll = true) {
    els.emptyHint.style.display = "none";

    const isMine = msg.src === state.nodeName;
    const isEmergency = msg.type === "emergency";
    const d = msg.timestamp ? new Date(msg.timestamp * 1000) : new Date();
    const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    // Path calculation
    const path = msg.path && msg.path.length > 0 ? msg.path : [msg.src];
    const hops = Math.max(1, path.length - 1);
    const pathStr = path.join(" > ");
    const hopText = hops <= 1 ? "direct" : `${hops} hops`;

    // 1. Incoming Emergency Broadcast: Full-width coral-outlined card
    if (isEmergency && !isMine) {
      const card = document.createElement("div");
      card.className = "emergency-broadcast-card";
      card.setAttribute("data-id", msg.id);
      card.innerHTML = `
        <div class="emergency-broadcast-header">EMERGENCY \u2022 FROM NODE ${escapeHtml(msg.src)}</div>
        <div class="emergency-broadcast-payload">${escapeHtml(msg.payload || "")}</div>
        <div class="emergency-broadcast-path">Relay path: ${escapeHtml(pathStr)} \u2022 ${hopText} \u2022 ${timeStr}</div>
      `;
      els.chatContainer.appendChild(card);
      if (autoScroll) scrollToBottom();
      return;
    }

    // 2. Chat Message Row
    const row = document.createElement("div");
    row.className = `message-row ${isMine ? "mine" : "theirs"}`;
    row.setAttribute("data-id", msg.id);

    if (isMine) {
      // Outgoing message status
      const outStatus = state.outgoingStatuses.get(msg.id) || { status: "delivered", path: path, hops: hops };
      const statusHtml = renderOutgoingStatusHtml(msg, outStatus, timeStr);

      row.innerHTML = `
        <div class="message-bubble ${isEmergency ? "emergency" : ""}">
          <div class="message-content">${escapeHtml(msg.payload || "")}</div>
        </div>
        <div class="message-status-line" id="status-${escapeHtml(msg.id)}">
          ${statusHtml}
        </div>
      `;
    } else {
      // Incoming message
      row.innerHTML = `
        <div class="message-bubble ${isEmergency ? "emergency" : ""}">
          <div class="message-content">${escapeHtml(msg.payload || "")}</div>
        </div>
        <div class="message-meta-sub">
          <span>Node ${escapeHtml(msg.src)}</span>
          <span>\u2022</span>
          <span>${hopText}</span>
          <span>\u2022</span>
          <span>${timeStr}</span>
        </div>
      `;
    }

    els.chatContainer.appendChild(row);
    attachRetryListeners(row);

    if (autoScroll) scrollToBottom();
  }

  function renderOutgoingStatusHtml(msg, outStatus, timeStr) {
    if (outStatus.status === "sending") {
      return `<span>Sending...</span>`;
    } else if (outStatus.status === "failed") {
      return `
        <span class="status-failed">
          Failed \u2022
          <button type="button" class="retry-link" data-retry-id="${escapeHtml(msg.id)}">Tap to retry</button>
        </span>
      `;
    } else if (outStatus.status === "relayed") {
      return `<span>Relayed \u2022 ${timeStr}</span>`;
    } else {
      // Delivered
      if (msg.dst === "ALL") {
        return `<span>Broadcast sent \u2022 ${timeStr}</span>`;
      } else if (outStatus.hops <= 1) {
        return `<span>Delivered to ${escapeHtml(msg.dst)} \u2022 direct \u2022 ${timeStr}</span>`;
      } else {
        const pathStr = outStatus.path ? outStatus.path.join(" > ") : `${state.nodeName} > ${msg.dst}`;
        return `<span>Delivered to ${escapeHtml(msg.dst)} \u2022 via ${escapeHtml(pathStr)} \u2022 ${outStatus.hops} hops \u2022 ${timeStr}</span>`;
      }
    }
  }

  function attachRetryListeners(container) {
    container.querySelectorAll(".retry-link").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const msgId = btn.getAttribute("data-retry-id");
        if (msgId) retryMessage(msgId);
      });
    });
  }

  function updateMessageStatusUI(msgId) {
    const statusEl = document.getElementById(`status-${msgId}`);
    const msg = state.messages.get(msgId);
    const outStatus = state.outgoingStatuses.get(msgId);
    if (statusEl && msg && outStatus) {
      const d = msg.timestamp ? new Date(msg.timestamp * 1000) : new Date();
      const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      statusEl.innerHTML = renderOutgoingStatusHtml(msg, outStatus, timeStr);
      attachRetryListeners(statusEl);
    }
  }

  async function retryMessage(msgId) {
    const msg = state.messages.get(msgId);
    if (!msg) return;

    state.outgoingStatuses.set(msgId, { status: "sending", path: [state.nodeName], hops: 1 });
    updateMessageStatusUI(msgId);

    try {
      const res = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dst: msg.dst, payload: msg.payload }),
      });

      if (!res.ok) throw new Error("Retry failed");
      const data = await res.json();

      const hops = data.path ? Math.max(1, data.path.length - 1) : 1;
      state.outgoingStatuses.set(msgId, {
        status: "delivered",
        path: data.path || [state.nodeName, msg.dst],
        hops: hops,
      });
      updateMessageStatusUI(msgId);
    } catch (err) {
      state.outgoingStatuses.set(msgId, { status: "failed", error: err.message });
      updateMessageStatusUI(msgId);
    }
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      els.chatContainer.scrollTop = els.chatContainer.scrollHeight;
    });
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // =========================================================
  // Sending Messages & Send Button State
  // =========================================================
  function updateSendButtonState() {
    const hasText = els.messageInput.value.trim().length > 0;
    els.sendBtn.disabled = !hasText;
    if (hasText) {
      els.sendBtn.classList.remove("disabled");
    } else {
      els.sendBtn.classList.add("disabled");
    }
  }

  async function sendMessage() {
    const text = els.messageInput.value.trim();
    if (!text) return;

    const dst = state.selectedDst || "ALL";
    els.messageInput.value = "";
    updateSendButtonState();

    const tempId = `msg-${Date.now()}`;
    const msgObj = {
      id: tempId,
      src: state.nodeName,
      dst: dst,
      payload: text,
      path: [state.nodeName],
      timestamp: Date.now() / 1000,
      type: "chat",
    };

    // Optimistically record as sending
    state.messages.set(tempId, msgObj);
    state.outgoingStatuses.set(tempId, { status: "sending", path: [state.nodeName], hops: 1 });
    appendMessageElement(msgObj, true);

    try {
      const res = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dst: dst, payload: text }),
      });

      if (!res.ok) throw new Error("Failed to send");
      const data = await res.json();

      const serverId = data.id || tempId;
      if (serverId !== tempId) {
        state.messages.delete(tempId);
        msgObj.id = serverId;
        state.messages.set(serverId, msgObj);
        state.outgoingStatuses.delete(tempId);
      }

      // Check if direct or multi-hop path
      const hops = state.peerHops.get(dst) || 1;
      const path = [state.nodeName];
      if (hops > 1) path.push("relay");
      path.push(dst);

      state.outgoingStatuses.set(msgObj.id, {
        status: "delivered",
        path: path,
        hops: hops,
      });
      updateMessageStatusUI(msgObj.id);
    } catch (err) {
      state.outgoingStatuses.set(msgObj.id, { status: "failed", error: err.message });
      updateMessageStatusUI(msgObj.id);
    }
  }

  // =========================================================
  // 6. SOS Button (1.5s press-and-hold, haptics, hold caption)
  // =========================================================
  function startSosHold(e) {
    if (e.cancelable) e.preventDefault();
    els.sosWrapper.classList.add("holding");

    // gentle vibration pulse on hold start
    if ("vibrate" in navigator) {
      try {
        navigator.vibrate([40, 60, 40, 60]);
      } catch (_) {}
    }

    state.sosTimer = setTimeout(() => {
      triggerEmergencyAlert();
      endSosHold();
    }, state.sosHoldDuration);
  }

  function endSosHold() {
    if (state.sosTimer) {
      clearTimeout(state.sosTimer);
      state.sosTimer = null;
    }
    els.sosWrapper.classList.remove("holding");
  }

  async function triggerEmergencyAlert() {
    // Distinct haptic vibration on completion
    if ("vibrate" in navigator) {
      try {
        navigator.vibrate([200, 100, 200]);
      } catch (_) {}
    }

    try {
      const alertText = `EMERGENCY ALERT from Node ${state.nodeName}! Need immediate assistance.`;
      const res = await fetch("/api/alert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: alertText }),
      });

      if (!res.ok) throw new Error("Alert send failed");
      const data = await res.json();

      const alertMsg = {
        id: data.id || `alert-${Date.now()}`,
        src: state.nodeName,
        dst: "ALL",
        payload: alertText,
        path: [state.nodeName],
        timestamp: Date.now() / 1000,
        type: "emergency",
      };

      state.messages.set(alertMsg.id, alertMsg);
      state.outgoingStatuses.set(alertMsg.id, { status: "delivered", path: [state.nodeName], hops: 1 });
      appendMessageElement(alertMsg, true);

      showToast("SOS broadcast sent", "down");
    } catch (err) {
      showToast("SOS broadcast failed: " + err.message, "down");
    }
  }

  // =========================================================
  // Incoming Emergency Full-Screen Overlay
  // =========================================================
  function showIncomingEmergency(msg) {
    els.emergencySender.textContent = `Alert from Node ${msg.src}`;
    els.emergencyPayload.textContent = msg.payload || "Emergency Alert Broadcast";
    const pathStr = msg.path && msg.path.length > 0 ? msg.path.join(" > ") : msg.src;
    els.emergencyMeta.textContent = `Path: ${pathStr} \u2022 Hop count: ${Math.max(1, (msg.path || []).length - 1)}`;

    els.emergencyOverlay.classList.add("active");

    if ("vibrate" in navigator) {
      try {
        navigator.vibrate([300, 150, 300, 150, 500]);
        if (!state.vibrationInterval) {
          state.vibrationInterval = setInterval(() => {
            if (els.emergencyOverlay.classList.contains("active")) {
              navigator.vibrate([300, 150, 300, 150, 500]);
            } else {
              clearInterval(state.vibrationInterval);
              state.vibrationInterval = null;
            }
          }, 1500);
        }
      } catch (_) {}
    }
  }

  function acknowledgeEmergency() {
    els.emergencyOverlay.classList.remove("active");
    if ("vibrate" in navigator) {
      try {
        navigator.vibrate(0);
      } catch (_) {}
    }
    if (state.vibrationInterval) {
      clearInterval(state.vibrationInterval);
      state.vibrationInterval = null;
    }
    showToast("Emergency acknowledged", "up");
  }

  // =========================================================
  // Bottom Sheet (Neighbors List)
  // =========================================================
  function updateNeighborsUI() {
    if (!state.neighbors || state.neighbors.length === 0) {
      els.neighborsList.innerHTML =
        '<p style="color:var(--muted); text-align:center; padding:16px;">Scanning for mesh neighbors...</p>';
      return;
    }

    let html = "";
    state.neighbors.forEach((n) => {
      const isUp = n.status === "UP";
      const statusClass = isUp ? "up" : "down";
      const statusText = isUp ? "Connected" : "Disconnected";
      const lastSeen = n.last_seen_seconds ? `${n.last_seen_seconds}s ago` : "just now";

      html += `
        <div class="neighbor-card">
          <div class="neighbor-card-left">
            <div class="neighbor-card-info">
              <span class="neighbor-card-name">Node ${escapeHtml(n.name)}</span>
              <span class="neighbor-card-addr">${escapeHtml(n.address || "local link")} \u2022 ${lastSeen}</span>
            </div>
          </div>
          <div class="neighbor-card-right">
            <span class="status-badge ${statusClass}">${statusText}</span>
          </div>
        </div>
      `;
    });

    els.neighborsList.innerHTML = html;
  }

  // =========================================================
  // Toasts
  // =========================================================
  function showToast(message, type = "up") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;

    els.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 200ms";
      setTimeout(() => {
        if (toast.parentElement) toast.parentElement.removeChild(toast);
      }, 200);
    }, 3000);
  }

  // =========================================================
  // Server-Sent Events (SSE) Live Stream
  // =========================================================
  function connectSSE() {
    let evtSource = null;

    try {
      evtSource = new EventSource("/api/events");

      evtSource.onopen = function () {
        els.connectionDot.classList.remove("disconnected");
        els.connectionDot.title = "Connected to mesh node";
      };

      evtSource.onmessage = function (e) {
        if (!e.data || e.data.trim() === "") return;
        try {
          const event = JSON.parse(e.data);
          handleIncomingEvent(event);
        } catch (err) {
          console.warn("Malformed SSE JSON:", err);
        }
      };

      evtSource.onerror = function () {
        els.connectionDot.classList.add("disconnected");
        els.connectionDot.title = "Disconnected from mesh node (reconnecting...)";
      };
    } catch (err) {
      console.warn("SSE Connection error:", err);
    }
  }

  function handleIncomingEvent(event) {
    const type = event.type;
    const data = event.data || {};

    if (type === "neighbor_up") {
      state.peerStatuses.set(data.name, "UP");
      state.peerHops.set(data.name, 1);
      showToast(`Neighbor ${data.name || "node"} connected (UP)`, "up");
      fetchState();
    } else if (type === "neighbor_down") {
      const name = data.name || "Peer";
      if (state.peerStatuses.get(name) === "UP") {
        appendSystemLine(`${name} went offline, rerouting`);
      }
      state.peerStatuses.set(name, "DOWN");
      showToast(`Neighbor ${name} disconnected (DOWN)`, "down");
      fetchState();
    } else if (type === "delivered") {
      const msgId = data.id;
      if (msgId && !state.messages.has(msgId)) {
        const msgObj = {
          id: msgId,
          src: data.src,
          dst: state.nodeName,
          payload: data.payload,
          path: data.path || [data.src, state.nodeName],
          timestamp: event.timestamp || Date.now() / 1000,
          type: "chat",
        };

        if (data.src && msgObj.path) {
          state.peerHops.set(data.src, Math.max(1, msgObj.path.length - 1));
          state.peerStatuses.set(data.src, "UP");
          updateBanner();
          updateRecipientChips();
        }

        state.messages.set(msgId, msgObj);
        appendMessageElement(msgObj, true);

        if (event.description && event.description.toLowerCase().includes("emergency")) {
          msgObj.type = "emergency";
          showIncomingEmergency(msgObj);
        }
      }
    }
  }

  // =========================================================
  // Event Listeners Initialization
  // =========================================================
  function initListeners() {
    // Send button & enter key
    els.sendBtn.addEventListener("click", sendMessage);
    els.messageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !els.sendBtn.disabled) {
        sendMessage();
      }
    });

    // Update send button disabled state on input
    els.messageInput.addEventListener("input", updateSendButtonState);

    // Emergency button: 1.5s hold only, never trigger on single tap
    els.sosBtn.addEventListener("pointerdown", startSosHold);
    window.addEventListener("pointerup", endSosHold);
    window.addEventListener("pointercancel", endSosHold);
    els.sosBtn.addEventListener("click", (e) => e.preventDefault());

    // Acknowledge emergency
    els.ackEmergencyBtn.addEventListener("click", acknowledgeEmergency);

    // Bottom sheet open/close
    const openSheet = () => {
      fetchState();
      els.bottomSheetBackdrop.classList.add("open");
    };

    els.openNeighborsBtn.addEventListener("click", openSheet);

    els.closeNeighborsBtn.addEventListener("click", () => {
      els.bottomSheetBackdrop.classList.remove("open");
    });

    els.bottomSheetBackdrop.addEventListener("click", (e) => {
      if (e.target === els.bottomSheetBackdrop) {
        els.bottomSheetBackdrop.classList.remove("open");
      }
    });

    // periodic background state refresh (every 4 seconds)
    setInterval(fetchState, 4000);
  }

  // =========================================================
  // App Boot
  // =========================================================
  function boot() {
    initListeners();
    updateSendButtonState();
    fetchState();
    fetchMessages();
    connectSSE();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
