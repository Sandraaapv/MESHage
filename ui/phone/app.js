/**
 * MESHage Phone UI Application
 * Plain Vanilla JavaScript, offline-first, SSE live updates
 */

(function () {
  "use strict";

  // Application State
  const state = {
    nodeName: "Node",
    port: 5000,
    neighbors: [],
    messages: new Map(), // id -> message
    theme: localStorage.getItem("meshage_theme") || "dark",
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
    headerSignalBars: document.getElementById("headerSignalBars"),
    themeToggleBtn: document.getElementById("themeToggleBtn"),
    themeIcon: document.getElementById("themeIcon"),
    chatContainer: document.getElementById("chatContainer"),
    emptyState: document.getElementById("emptyState"),
    destSelect: document.getElementById("destSelect"),
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
    moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>',
    sun: '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>',
    checkSingle: '<polyline points="20 6 9 17 4 12"></polyline>',
    checkDouble: '<path d="M18 6L7 17l-5-5"></path><path d="M22 10l-7.5 7.5-1.5-1.5"></path>',
    hop: '<polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline>',
  };

  // =========================================================
  // Theme Management
  // =========================================================
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("meshage_theme", theme);
    els.themeIcon.innerHTML = theme === "dark" ? icons.moon : icons.sun;
  }

  function toggleTheme() {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  }

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
      state.neighbors = data.neighbors || [];

      updateHeader();
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
      });
      renderAllMessages();
    } catch (err) {
      console.warn("Error fetching messages:", err);
    }
  }

  function updateHeader() {
    els.nodeNameHeader.textContent = `MESHage (${state.nodeName})`;
    const upNeighbors = state.neighbors.filter((n) => n.status === "UP");
    els.neighborCountText.textContent = upNeighbors.length;

    // update signal bars
    const bars = els.headerSignalBars.children;
    for (let i = 0; i < bars.length; i++) {
      if (upNeighbors.length > 0 && i < Math.min(upNeighbors.length, 3)) {
        bars[i].classList.add("active");
      } else {
        bars[i].classList.remove("active");
      }
    }

    // update destination dropdown options
    updateDestDropdown();
  }

  function updateDestDropdown() {
    const currentVal = els.destSelect.value;
    const upNeighbors = state.neighbors.filter((n) => n.status === "UP");

    let html = '<option value="ALL">Everyone (Broadcast)</option>';
    upNeighbors.forEach((n) => {
      html += `<option value="${n.name}">Node ${n.name}</option>`;
    });

    els.destSelect.innerHTML = html;
    if (currentVal && els.destSelect.querySelector(`option[value="${currentVal}"]`)) {
      els.destSelect.value = currentVal;
    }
  }

  function updateNeighborsUI() {
    if (!state.neighbors || state.neighbors.length === 0) {
      els.neighborsList.innerHTML = '<p style="color:var(--muted); text-align:center; padding:16px;">No neighbors in radio range yet.</p>';
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
            <span class="neighbor-card-name">Node ${n.name}</span>
            <span class="neighbor-card-addr">${n.address || "local link"} &bull; ${lastSeen}</span>
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
  // Chat Rendering
  // =========================================================
  function renderAllMessages() {
    if (state.messages.size === 0) {
      els.emptyState.style.display = "flex";
      return;
    }

    els.emptyState.style.display = "none";
    const existingIds = new Set();
    document.querySelectorAll(".message-row[data-id]").forEach((el) => {
      existingIds.add(el.getAttribute("data-id"));
    });

    const sorted = Array.from(state.messages.values()).sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

    sorted.forEach((msg) => {
      if (!existingIds.has(msg.id)) {
        appendMessageElement(msg, false);
      }
    });

    scrollToBottom();
  }

  function appendMessageElement(msg, autoScroll = true) {
    els.emptyState.style.display = "none";

    const isMine = msg.src === state.nodeName;
    const isEmergency = msg.type === "emergency";
    const row = document.createElement("div");
    row.className = `message-row ${isMine ? "mine" : "theirs"}`;
    row.setAttribute("data-id", msg.id);

    // time format
    const d = msg.timestamp ? new Date(msg.timestamp * 1000) : new Date();
    const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    // hop path display
    const pathStr = (msg.path && msg.path.length > 0) ? msg.path.join(" > ") : (isMine ? state.nodeName : msg.src);

    const bubbleClass = `message-bubble ${isEmergency ? "emergency" : ""}`;
    const senderHtml = (!isMine) ? `<div class="sender-name">${isEmergency ? "EMERGENCY: " : ""}Node ${msg.src}</div>` : "";

    const statusIconSvg = isMine
      ? `<svg class="status-icon delivered" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">${icons.checkDouble}</svg>`
      : "";

    row.innerHTML = `
      <div class="${bubbleClass}">
        ${senderHtml}
        <div class="message-content">${escapeHtml(msg.payload || "")}</div>
        <div class="message-meta">
          <span>${timeStr}</span>
          ${statusIconSvg}
        </div>
      </div>
      <div class="hop-chip">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">${icons.hop}</svg>
        <span>${escapeHtml(pathStr)}</span>
      </div>
    `;

    els.chatContainer.appendChild(row);
    if (autoScroll) {
      scrollToBottom();
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
  // Sending Messages
  // =========================================================
  async function sendMessage() {
    const text = els.messageInput.value.trim();
    if (!text) return;

    const dst = els.destSelect.value || "ALL";
    els.messageInput.value = "";

    try {
      const res = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dst: dst, payload: text }),
      });

      if (!res.ok) throw new Error("Failed to send");
      const data = await res.json();

      // create optimistic local message
      const msgObj = {
        id: data.id || `local-${Date.now()}`,
        src: state.nodeName,
        dst: dst,
        payload: text,
        path: [state.nodeName],
        timestamp: Date.now() / 1000,
        type: "chat",
      };

      state.messages.set(msgObj.id, msgObj);
      appendMessageElement(msgObj, true);
    } catch (err) {
      showToast("Failed to send message: " + err.message, "down");
    }
  }

  // =========================================================
  // Emergency SOS Trigger (1.5s press-and-hold)
  // =========================================================
  function startSosHold(e) {
    if (e.cancelable) e.preventDefault();
    els.sosWrapper.classList.add("holding");

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
    // vibrate on send if supported
    if ("vibrate" in navigator) {
      navigator.vibrate([200, 100, 200, 100, 400]);
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
      appendMessageElement(alertMsg, true);
      showToast("Emergency Alert Broadcast Sent!", "down");
    } catch (err) {
      showToast("Emergency broadcast failed: " + err.message, "down");
    }
  }

  // =========================================================
  // Incoming Emergency Overlay
  // =========================================================
  function showIncomingEmergency(msg) {
    els.emergencySender.textContent = `Alert from Node ${msg.src}`;
    els.emergencyPayload.textContent = msg.payload || "Emergency Alert Broadcast";
    const pathStr = (msg.path && msg.path.length > 0) ? msg.path.join(" > ") : msg.src;
    els.emergencyMeta.textContent = `Path: ${pathStr} \u2022 Hop count: ${Math.max(1, (msg.path || []).length - 1)}`;

    els.emergencyOverlay.classList.add("active");

    // trigger continuous phone vibration
    if ("vibrate" in navigator) {
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
    }
  }

  function acknowledgeEmergency() {
    els.emergencyOverlay.classList.remove("active");
    if ("vibrate" in navigator) {
      navigator.vibrate(0);
    }
    if (state.vibrationInterval) {
      clearInterval(state.vibrationInterval);
      state.vibrationInterval = null;
    }
    showToast("Emergency acknowledged", "up");
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
    }, 3200);
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
        // EventSource will automatically retry connecting
      };
    } catch (err) {
      console.warn("SSE Connection error:", err);
    }
  }

  function handleIncomingEvent(event) {
    const type = event.type;
    const data = event.data || {};

    if (type === "neighbor_up") {
      showToast(`Neighbor ${data.name || "node"} connected (UP)`, "up");
      fetchState();
    } else if (type === "neighbor_down") {
      showToast(`Neighbor ${data.name || "node"} disconnected (DOWN)`, "down");
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
        state.messages.set(msgId, msgObj);
        appendMessageElement(msgObj, true);

        // check if emergency
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
    // Theme toggle
    els.themeToggleBtn.addEventListener("click", toggleTheme);

    // Send button & enter key
    els.sendBtn.addEventListener("click", sendMessage);
    els.messageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        sendMessage();
      }
    });

    // Emergency button press-and-hold (pointer & touch)
    els.sosBtn.addEventListener("pointerdown", startSosHold);
    window.addEventListener("pointerup", endSosHold);
    window.addEventListener("pointercancel", endSosHold);

    // Acknowledge emergency
    els.ackEmergencyBtn.addEventListener("click", acknowledgeEmergency);

    // Bottom sheet open/close
    els.openNeighborsBtn.addEventListener("click", () => {
      fetchState();
      els.bottomSheetBackdrop.classList.add("open");
    });

    els.closeNeighborsBtn.addEventListener("click", () => {
      els.bottomSheetBackdrop.classList.remove("open");
    });

    els.bottomSheetBackdrop.addEventListener("click", (e) => {
      if (e.target === els.bottomSheetBackdrop) {
        els.bottomSheetBackdrop.classList.remove("open");
      }
    });

    // periodic background state refresh (every 5 seconds)
    setInterval(fetchState, 5000);
  }

  // =========================================================
  // App Boot
  // =========================================================
  function boot() {
    applyTheme(state.theme);
    initListeners();
    fetchState();
    fetchMessages();
    connectSSE();
  }

  // Start app when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
