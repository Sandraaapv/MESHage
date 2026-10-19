/**
 * MESHage Minimal Network Dashboard
 * High-performance 60 FPS HTML5 Canvas graph visualizer
 * Pure neutral greys, hairline borders, Linear/Vercel sleek aesthetic.
 */

(function () {
  'use strict';

  // =========================================================
  // 1. Channel Physics & Formulas (matches sim/channel.py)
  // =========================================================
  const TX_POWER_DBM = 14.0;
  const D0 = 1.0;
  const PL_D0 = 40.0;
  const SENSITIVITY_DBM = -85.0;
  let pathLossExponent = 3.0; // n
  let txRange = 195.0; // transmission range in canvas pixels

  function calcPathLoss(dist, n) {
    const d = Math.max(dist, D0);
    return PL_D0 + 10.0 * n * Math.log10(d / D0);
  }

  function calcSuccessProbability(dist, n) {
    const pl = calcPathLoss(dist, n);
    const prx = TX_POWER_DBM - pl;
    const diff = prx - SENSITIVITY_DBM;
    if (diff > 20.0) return 1.0;
    if (diff < -20.0) return 0.0;
    return 1.0 / (1.0 + Math.exp(-0.5 * diff));
  }

  // =========================================================
  // 2. State & Data Structures
  // =========================================================
  const state = {
    nodes: [], // Array of { name, x, y, alive, radius: 4, neighbors: [] }
    nodeMap: new Map(),
    links: [], // Array of { u, v, dist, prob, isDown }
    routingMode: 'shortest', // 'flooding', 'shortest', 'gossip'
    nodeCount: 30,
    selectedSource: null,
    hoveredNode: null,
    activePath: null, // { path: ['N0', 'N1'], expiresAt }
    particles: [], // In-flight animation particles
    alertWaves: [], // Expanding alert rings
    recoveryStartTime: null,
    lastRecoveryTime: 0.0,
    messagesSent: 0,
    messagesDelivered: 0,
    totalHops: 0,
    totalTransmissions: 0,
    metricHistory: {
      delivery_rate: [100.0],
      avg_delay: [1.0],
      packets_per_msg: [1.0],
      active_nodes: [30],
      recovery_time: [0.0],
    },
    eventLog: [],
    activeFilter: 'ALL',
    autoScroll: true,
    sseConnected: false,
    sseSource: null,
  };

  // DOM Elements
  const canvas = document.getElementById('mesh-canvas');
  const ctx = canvas.getContext('2d');
  const canvasWrapper = document.getElementById('canvas-wrapper');

  const connectionDot = document.getElementById('connection-dot');
  const connectionStatus = document.getElementById('connection-status');
  const activeRoutingMode = document.getElementById('active-routing-mode');
  const topologyStats = document.getElementById('topology-stats');
  const fpsCounter = document.getElementById('fps-counter');

  // Metric displays
  const elMetricDelivery = document.getElementById('metric-delivery-rate');
  const elMetricDelay = document.getElementById('metric-avg-delay');
  const elMetricOverhead = document.getElementById('metric-packets-msg');
  const elMetricActive = document.getElementById('metric-active-nodes');
  const elMetricTotal = document.getElementById('metric-total-nodes');
  const elMetricRecovery = document.getElementById('metric-recovery-time');

  // Single sparkline for delivery rate
  const sparkDelivery = document.getElementById('spark-delivery');

  // Controls
  const btnEmergencyAlert = document.getElementById('btn-emergency-alert');
  const btnKillRandom = document.getElementById('btn-kill-random');
  const btnReset = document.getElementById('btn-reset');
  const routingSelector = document.getElementById('routing-selector');
  const sliderPathLoss = document.getElementById('slider-path-loss');
  const badgePathLoss = document.getElementById('path-loss-badge');
  const nodeCountSelector = document.getElementById('node-count-selector');

  // Canvas Overlays & Hint
  const selectionPill = document.getElementById('selection-pill');
  const selectionText = document.getElementById('selection-text');
  const btnCancelSelection = document.getElementById('btn-cancel-selection');
  const guideText = document.getElementById('guide-text');

  // Event Log
  const eventStream = document.getElementById('event-stream');
  const logCountBadge = document.getElementById('log-count');
  const btnClearLog = document.getElementById('btn-clear-log');
  const autoScrollCb = document.getElementById('auto-scroll-cb');
  const logFilters = document.querySelector('.log-filters');

  // =========================================================
  // 3. Topology Initialization & Link Building
  // =========================================================
  function initTopology(count) {
    state.nodeCount = count;
    state.nodes = [];
    state.nodeMap.clear();
    state.selectedSource = null;
    hideSelectionPill();
    state.activePath = null;
    state.particles = [];
    state.alertWaves = [];

    const rect = canvasWrapper.getBoundingClientRect();
    const w = Math.max(600, rect.width || 1000);
    const h = Math.max(400, rect.height || 600);

    const padX = 60;
    const padY = 50;
    const availW = w - padX * 2;
    const availH = h - padY * 2;

    const cols = Math.max(3, Math.round(Math.sqrt(count * (availW / availH))));
    const rows = Math.max(2, Math.ceil(count / cols));
    const cellW = availW / cols;
    const cellH = availH / rows;

    let idx = 0;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (idx >= count) break;
        const jitterX = (Math.random() - 0.5) * cellW * 0.55;
        const jitterY = (Math.random() - 0.5) * cellH * 0.55;
        const x = padX + (c + 0.5) * cellW + jitterX;
        const y = padY + (r + 0.5) * cellH + jitterY;

        const node = {
          name: `N${idx}`,
          x: Math.round(x),
          y: Math.round(y),
          alive: true,
          radius: 4, // 8px diameter
          neighbors: [],
        };
        state.nodes.push(node);
        state.nodeMap.set(node.name, node);
        idx++;
      }
    }

    rebuildLinks();
    updateCanvasStats();
    updateMetricsUI();
    logEvent('PARAM', `Topology initialized with ${count} nodes (${getRoutingModeLabel(state.routingMode)}, n=${pathLossExponent.toFixed(1)})`);
  }

  function rebuildLinks() {
    state.links = [];
    state.nodes.forEach(n => { n.neighbors = []; });

    const n = pathLossExponent;
    const nodes = state.nodes;

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const u = nodes[i];
        const v = nodes[j];
        const dx = u.x - v.x;
        const dy = u.y - v.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist <= txRange) {
          const prob = calcSuccessProbability(dist, n);
          const isDown = !u.alive || !v.alive || prob < 0.28;

          if (u.alive && v.alive && prob >= 0.28) {
            u.neighbors.push(v.name);
            v.neighbors.push(u.name);
          }

          state.links.push({
            u: u.name,
            v: v.name,
            dist: dist,
            prob: prob,
            isDown: isDown,
          });
        }
      }
    }
    updateCanvasStats();
  }

  function updateCanvasStats() {
    const totalNodes = state.nodes.length;
    if (topologyStats) topologyStats.textContent = `${totalNodes} nodes`;
  }

  function getRoutingModeLabel(mode) {
    if (mode === 'shortest') return 'Shortest path';
    if (mode === 'flooding') return 'Flooding';
    if (mode === 'gossip') return 'Gossip (p=0.6)';
    return mode;
  }

  // =========================================================
  // 4. Routing Algorithms
  // =========================================================
  function dijkstraShortestPath(srcName, dstName) {
    if (!state.nodeMap.has(srcName) || !state.nodeMap.has(dstName) || srcName === dstName) {
      return null;
    }
    const srcNode = state.nodeMap.get(srcName);
    const dstNode = state.nodeMap.get(dstName);
    if (!srcNode.alive || !dstNode.alive) return null;

    const distances = new Map();
    const previous = new Map();
    const unvisited = new Set();

    state.nodes.forEach(n => {
      if (n.alive) {
        distances.set(n.name, Infinity);
        unvisited.add(n.name);
      }
    });

    distances.set(srcName, 0);

    while (unvisited.size > 0) {
      let current = null;
      let minDistance = Infinity;

      unvisited.forEach(nodeName => {
        const d = distances.get(nodeName);
        if (d < minDistance) {
          minDistance = d;
          current = nodeName;
        }
      });

      if (current === null || minDistance === Infinity) break;
      if (current === dstName) break;

      unvisited.delete(current);
      const currNode = state.nodeMap.get(current);

      currNode.neighbors.forEach(neighborName => {
        if (!unvisited.has(neighborName)) return;
        const neighborNode = state.nodeMap.get(neighborName);
        if (!neighborNode.alive) return;

        const dx = currNode.x - neighborNode.x;
        const dy = currNode.y - neighborNode.y;
        const linkDist = Math.sqrt(dx * dx + dy * dy);
        const alt = distances.get(current) + linkDist;

        if (alt < distances.get(neighborName)) {
          distances.set(neighborName, alt);
          previous.set(neighborName, current);
        }
      });
    }

    if (!previous.has(dstName) && srcName !== dstName) {
      return null;
    }

    const path = [];
    let curr = dstName;
    while (curr) {
      path.unshift(curr);
      curr = previous.get(curr);
    }
    return path;
  }

  function simulateFlooding(srcName, dstName) {
    if (!state.nodeMap.has(srcName) || !state.nodeMap.has(dstName)) return null;
    const queue = [[srcName]];
    const visited = new Set([srcName]);
    let transmissions = 0;

    while (queue.length > 0) {
      const path = queue.shift();
      const current = path[path.length - 1];

      if (current === dstName) {
        return { path, transmissions };
      }

      const currNode = state.nodeMap.get(current);
      if (!currNode || !currNode.alive) continue;

      currNode.neighbors.forEach(nb => {
        transmissions++;
        if (!visited.has(nb)) {
          visited.add(nb);
          queue.push([...path, nb]);
        }
      });
    }
    return null;
  }

  function simulateGossip(srcName, dstName, gossipProb = 0.6) {
    if (!state.nodeMap.has(srcName) || !state.nodeMap.has(dstName)) return null;
    const queue = [[srcName]];
    const visited = new Set([srcName]);
    let transmissions = 0;

    while (queue.length > 0) {
      const path = queue.shift();
      const current = path[path.length - 1];

      if (current === dstName) {
        return { path, transmissions };
      }

      const currNode = state.nodeMap.get(current);
      if (!currNode || !currNode.alive) continue;

      currNode.neighbors.forEach(nb => {
        if (Math.random() <= gossipProb) {
          transmissions++;
          if (!visited.has(nb)) {
            visited.add(nb);
            queue.push([...path, nb]);
          }
        }
      });
    }
    return null;
  }

  // =========================================================
  // 5. Message Dispatch & Routing Handlers
  // =========================================================
  function sendMessage(src, dst) {
    state.messagesSent++;

    if (state.sseConnected) {
      fetch('/api/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ src, dst, payload: `Payload from ${src}` }),
      })
        .then(res => res.json())
        .then(data => {
          if (data.delivered && data.final_path) {
            handleSuccessfulRoute(src, dst, data.final_path, data.hops, data.transmissions);
          } else {
            handleDroppedMessage(src, dst);
          }
        })
        .catch(() => {
          fallbackLocalRouting(src, dst);
        });
    } else {
      fallbackLocalRouting(src, dst);
    }
  }

  function fallbackLocalRouting(src, dst) {
    let result = null;
    let hops = 0;
    let transmissions = 0;

    if (state.routingMode === 'shortest') {
      const path = dijkstraShortestPath(src, dst);
      if (path) {
        result = { path };
        hops = path.length - 1;
        transmissions = hops;
      }
    } else if (state.routingMode === 'flooding') {
      const flood = simulateFlooding(src, dst);
      if (flood) {
        result = { path: flood.path };
        hops = flood.path.length - 1;
        transmissions = flood.transmissions;
      }
    } else if (state.routingMode === 'gossip') {
      const gossip = simulateGossip(src, dst, 0.6);
      if (gossip) {
        result = { path: gossip.path };
        hops = gossip.path.length - 1;
        transmissions = gossip.transmissions;
      }
    }

    if (result && result.path && result.path.length >= 2) {
      handleSuccessfulRoute(src, dst, result.path, hops, transmissions);
    } else {
      handleDroppedMessage(src, dst);
    }
  }

  function handleSuccessfulRoute(src, dst, path, hops, transmissions) {
    state.messagesDelivered++;
    state.totalHops += (hops || (path.length - 1));
    state.totalTransmissions += (transmissions || (path.length - 1));

    animateHopChain(path);

    // Active path drawn in single accent color #3DDC97
    state.activePath = {
      path: [...path],
      expiresAt: performance.now() + 3500,
    };

    logEvent('DELIVERY', `Delivered ${src} -> ${dst} via [${path.join(' -> ')}] (${hops || path.length - 1} hops)`);
    updateMetricsUI();
  }

  function handleDroppedMessage(src, dst) {
    logEvent('DROP', `Message from ${src} to ${dst} dropped (no path available)`);
    updateMetricsUI();
  }

  function sendEmergencyAlert() {
    const aliveNodes = state.nodes.filter(n => n.alive);
    if (aliveNodes.length === 0) {
      logEvent('ALERT', 'No active nodes available to broadcast emergency alert');
      return;
    }

    const src = aliveNodes[0].name;
    state.messagesSent++;

    if (state.sseConnected) {
      fetch('/api/alert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: 'EMERGENCY: ALL STATIONS' }),
      })
        .then(res => res.json())
        .then(() => triggerAlertVisuals(src))
        .catch(() => triggerAlertVisuals(src));
    } else {
      triggerAlertVisuals(src);
    }
  }

  function triggerAlertVisuals(src) {
    state.messagesDelivered++;
    state.totalHops += 2;
    state.totalTransmissions += state.nodes.length * 1.5;

    // Single thin red ring expanding outward from the origin node
    const origin = state.nodeMap.get(src) || state.nodes.find(n => n.alive);
    if (origin) {
      state.alertWaves.push({
        x: origin.x,
        y: origin.y,
        radius: 4,
        maxRadius: Math.max(canvas.width, canvas.height),
        alpha: 1.0,
      });
    }

    // Small white dots moving along links
    state.links.forEach((l, idx) => {
      if (!l.isDown && idx % 2 === 0) {
        const u = state.nodeMap.get(l.u);
        const v = state.nodeMap.get(l.v);
        if (u && v && u.alive && v.alive) {
          state.particles.push({
            x1: u.x,
            y1: u.y,
            x2: v.x,
            y2: v.y,
            progress: 0,
            speed: 0.045,
          });
        }
      }
    });

    logEvent('ALERT', `Emergency alert broadcast active across network`);
    updateMetricsUI();
  }

  function killRandomNode() {
    const aliveNodes = state.nodes.filter(n => n.alive);
    if (aliveNodes.length === 0) {
      logEvent('NODE', 'All nodes are already offline');
      return;
    }
    const target = aliveNodes[Math.floor(Math.random() * aliveNodes.length)];
    toggleNodeAlive(target.name);
  }

  function toggleNodeAlive(name) {
    const node = state.nodeMap.get(name);
    if (!node) return;

    node.alive = !node.alive;
    if (!node.alive) {
      state.recoveryStartTime = performance.now();
      logEvent('NODE', `Node ${name} disconnected`);
    } else {
      if (state.recoveryStartTime) {
        state.lastRecoveryTime = (performance.now() - state.recoveryStartTime) / 1000.0;
        state.recoveryStartTime = null;
      }
      logEvent('NODE', `Node ${name} recovered`);
    }

    rebuildLinks();
    updateMetricsUI();

    if (state.sseConnected) {
      fetch('/api/node/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }).catch(() => {});
    }
  }

  function animateHopChain(path) {
    if (!path || path.length < 2) return;

    for (let i = 0; i < path.length - 1; i++) {
      const u = state.nodeMap.get(path[i]);
      const v = state.nodeMap.get(path[i + 1]);
      if (!u || !v) continue;

      const delay = i * 220;
      setTimeout(() => {
        state.particles.push({
          x1: u.x,
          y1: u.y,
          x2: v.x,
          y2: v.y,
          progress: 0,
          speed: 0.035,
        });
      }, delay);
    }
  }

  // =========================================================
  // 6. Metrics & Single Minimal Sparkline
  // =========================================================
  function updateMetricsUI() {
    const delivRate = state.messagesSent > 0
      ? ((state.messagesDelivered / state.messagesSent) * 100.0).toFixed(1)
      : '100.0';
    const avgDelay = state.messagesDelivered > 0
      ? (state.totalHops / state.messagesDelivered).toFixed(2)
      : '1.0';
    const overhead = state.messagesDelivered > 0
      ? (state.totalTransmissions / state.messagesDelivered).toFixed(2)
      : '1.0';
    const aliveCount = state.nodes.filter(n => n.alive).length;

    if (elMetricDelivery) elMetricDelivery.textContent = delivRate;
    if (elMetricDelay) elMetricDelay.textContent = avgDelay;
    if (elMetricOverhead) elMetricOverhead.textContent = overhead;
    if (elMetricActive) elMetricActive.textContent = aliveCount;
    if (elMetricTotal) elMetricTotal.textContent = `/ ${state.nodes.length}`;
    if (elMetricRecovery) elMetricRecovery.textContent = state.lastRecoveryTime.toFixed(1);

    pushHistory('delivery_rate', parseFloat(delivRate));

    // Only one small sparkline under delivery rate
    drawSparkline(sparkDelivery, state.metricHistory.delivery_rate);
  }

  function pushHistory(key, val) {
    const buf = state.metricHistory[key];
    buf.push(val);
    if (buf.length > 25) buf.shift();
  }

  function drawSparkline(canvasEl, data) {
    if (!canvasEl || !data || data.length < 2) return;
    const sCtx = canvasEl.getContext('2d');
    const w = canvasEl.width;
    const h = canvasEl.height;

    sCtx.clearRect(0, 0, w, h);

    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = (max - min) === 0 ? 1 : (max - min);

    const step = (w - 4) / (data.length - 1);

    sCtx.beginPath();
    data.forEach((val, i) => {
      const x = 2 + i * step;
      const normalized = (val - min) / range;
      const y = h - 3 - normalized * (h - 6);
      if (i === 0) sCtx.moveTo(x, y);
      else sCtx.lineTo(x, y);
    });

    sCtx.strokeStyle = '#7A7A7A';
    sCtx.lineWidth = 1;
    sCtx.stroke();
  }

  // =========================================================
  // 7. Event Log Stream & Plain Monospace Formatting
  // =========================================================
  function logEvent(type, message, meta = {}) {
    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0];
    const item = {
      id: state.eventLog.length + 1,
      type: type, // 'ALERT', 'DELIVERY', 'NODE', 'PARAM', 'DROP'
      message: message,
      time: timeStr,
      meta: meta,
    };
    state.eventLog.push(item);
    if (state.eventLog.length > 150) state.eventLog.shift();

    if (logCountBadge) logCountBadge.textContent = state.eventLog.length;
    renderSingleEvent(item);
  }

  function renderSingleEvent(item) {
    if (state.activeFilter !== 'ALL' && state.activeFilter !== item.type) {
      return;
    }
    const el = document.createElement('div');
    el.className = `event-line ${item.type}`;
    el.innerHTML = `<span class="event-time">${item.time}</span> <span class="event-content">${escapeHtml(item.message)}</span>`;
    eventStream.appendChild(el);

    if (state.autoScroll) {
      eventStream.scrollTop = eventStream.scrollHeight;
    }
  }

  function reRenderEventLog() {
    eventStream.innerHTML = '';
    state.eventLog.forEach(item => {
      renderSingleEvent(item);
    });
  }

  function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // =========================================================
  // 8. Canvas 60 FPS Rendering Loop
  // =========================================================
  let frameCount = 0;
  let fpsTimer = performance.now();

  function resizeCanvas() {
    const rect = canvasWrapper.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function render(now) {
    frameCount++;
    if (now - fpsTimer >= 1000) {
      if (fpsCounter) fpsCounter.textContent = `${frameCount} fps`;
      frameCount = 0;
      fpsTimer = now;
    }

    const rect = canvasWrapper.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    // 1. Links (1px hairline grey / dashed weak)
    drawLinks();

    // 2. Highlighted Route (Single Muted Green #3DDC97)
    drawActivePath(now);

    // 3. In-Flight Message Packets (Small White Dots)
    drawParticles();

    // 4. Emergency Alert Wave (Single Thin Red Ring)
    drawAlertWaves();

    // 5. Mesh Nodes (8px solid white dots / hollow red if dead)
    drawNodes();

    requestAnimationFrame(render);
  }

  function drawLinks() {
    ctx.save();
    for (let i = 0; i < state.links.length; i++) {
      const link = state.links[i];
      const u = state.nodeMap.get(link.u);
      const v = state.nodeMap.get(link.v);
      if (!u || !v) continue;

      ctx.beginPath();
      ctx.moveTo(u.x, u.y);
      ctx.lineTo(v.x, v.y);

      if (link.isDown || !u.alive || !v.alive) {
        // Down / dead links: dim dashed
        ctx.strokeStyle = '#141414';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 4]);
      } else if (link.prob < 0.65) {
        // Weak links: slightly dimmer and dashed, no amber or orange
        ctx.strokeStyle = '#1C1C1C';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
      } else {
        // Default grey (#2A2A2A)
        ctx.strokeStyle = '#2A2A2A';
        ctx.lineWidth = 1;
        ctx.setLineDash([]);
      }

      ctx.stroke();
    }
    ctx.restore();
  }

  function drawActivePath(now) {
    if (!state.activePath) return;

    if (now > state.activePath.expiresAt) {
      state.activePath = null;
      return;
    }

    const path = state.activePath.path;
    if (path.length < 2) return;

    ctx.save();
    ctx.beginPath();

    for (let i = 0; i < path.length; i++) {
      const node = state.nodeMap.get(path[i]);
      if (!node) continue;
      if (i === 0) ctx.moveTo(node.x, node.y);
      else ctx.lineTo(node.x, node.y);
    }

    // Single muted green accent #3DDC97, no glows or shadows
    ctx.strokeStyle = '#3DDC97';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
    ctx.stroke();
    ctx.restore();
  }

  function drawParticles() {
    ctx.save();
    for (let i = state.particles.length - 1; i >= 0; i--) {
      const p = state.particles[i];
      p.progress += p.speed;

      if (p.progress >= 1.0) {
        state.particles.splice(i, 1);
        continue;
      }

      const currX = p.x1 + (p.x2 - p.x1) * p.progress;
      const currY = p.y1 + (p.y2 - p.y1) * p.progress;

      // Small white dots (radius 2.5px), no glows or colored tails
      ctx.beginPath();
      ctx.arc(currX, currY, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = '#EDEDED';
      ctx.fill();
    }
    ctx.restore();
  }

  function drawAlertWaves() {
    ctx.save();
    for (let i = state.alertWaves.length - 1; i >= 0; i--) {
      const w = state.alertWaves[i];
      w.radius += 2.0;
      w.alpha -= 0.015;

      if (w.alpha <= 0 || w.radius >= w.maxRadius) {
        state.alertWaves.splice(i, 1);
        continue;
      }

      // Single thin red ring expanding outward
      ctx.beginPath();
      ctx.arc(w.x, w.y, w.radius, 0, Math.PI * 2);
      ctx.strokeStyle = '#FF4D4D';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawNodes() {
    ctx.save();
    for (let i = 0; i < state.nodes.length; i++) {
      const node = state.nodes[i];
      const isSelected = state.selectedSource && state.selectedSource.name === node.name;
      const isHovered = state.hoveredNode && state.hoveredNode.name === node.name;

      if (node.alive) {
        // Small solid dot (8px diameter = radius 4), white-ish #EDEDED
        ctx.beginPath();
        ctx.arc(node.x, node.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#EDEDED';
        ctx.fill();

        // Active selection indicator: static 1px accent ring
        if (isSelected) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, 7, 0, Math.PI * 2);
          ctx.strokeStyle = '#3DDC97';
          ctx.lineWidth = 1;
          ctx.stroke();
        } else if (isHovered) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, 7, 0, Math.PI * 2);
          ctx.strokeStyle = '#7A7A7A';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      } else {
        // Dead node: hollow dot with a red outline #FF4D4D
        ctx.beginPath();
        ctx.arc(node.x, node.y, 4, 0, Math.PI * 2);
        ctx.strokeStyle = '#FF4D4D';
        ctx.lineWidth = 1;
        ctx.stroke();

        if (isSelected) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, 7, 0, Math.PI * 2);
          ctx.strokeStyle = '#FF4D4D';
          ctx.lineWidth = 1;
          ctx.stroke();
        } else if (isHovered) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, 7, 0, Math.PI * 2);
          ctx.strokeStyle = '#7A7A7A';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }

      // Name shown ONLY on hover or when selected
      if (isHovered || isSelected) {
        ctx.font = '12px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillStyle = isSelected ? '#3DDC97' : (node.alive ? '#EDEDED' : '#FF4D4D');
        ctx.fillText(node.name, node.x, node.y - 8);
      }
    }
    ctx.restore();
  }

  // =========================================================
  // 9. Interactive Pointer Handlers (Drag, Click, Hover)
  // =========================================================
  let draggingNode = null;
  let dragStartX = 0;
  let dragStartY = 0;
  let hasMoved = false;

  function getNodeAtCoords(px, py) {
    for (let i = state.nodes.length - 1; i >= 0; i--) {
      const n = state.nodes[i];
      const dist = Math.hypot(n.x - px, n.y - py);
      if (dist <= 12) { // 12px hit radius for easy clicking/dragging 8px nodes
        return n;
      }
    }
    return null;
  }

  canvas.addEventListener('pointerdown', e => {
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;

    const hit = getNodeAtCoords(px, py);
    if (hit) {
      draggingNode = hit;
      dragStartX = px;
      dragStartY = py;
      hasMoved = false;
      canvas.setPointerCapture(e.pointerId);
    }
  });

  canvas.addEventListener('pointermove', e => {
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;

    if (draggingNode) {
      if (Math.hypot(px - dragStartX, py - dragStartY) > 5) {
        hasMoved = true;
      }
      draggingNode.x = Math.max(20, Math.min(rect.width - 20, px));
      draggingNode.y = Math.max(20, Math.min(rect.height - 20, py));

      rebuildLinks();
    } else {
      const hit = getNodeAtCoords(px, py);
      if (hit !== state.hoveredNode) {
        state.hoveredNode = hit;
        canvas.style.cursor = hit ? 'pointer' : 'crosshair';
      }
    }
  });

  canvas.addEventListener('pointerup', e => {
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;

    if (draggingNode) {
      if (hasMoved) {
        if (state.sseConnected) {
          fetch('/api/node/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: draggingNode.name, x: draggingNode.x, y: draggingNode.y }),
          }).catch(() => {});
        }
      } else {
        handleNodeClick(draggingNode);
      }
      draggingNode = null;
    } else {
      if (state.selectedSource) {
        state.selectedSource = null;
        hideSelectionPill();
      }
    }
  });

  function handleNodeClick(node) {
    if (!node.alive) {
      toggleNodeAlive(node.name);
      return;
    }

    if (!state.selectedSource) {
      state.selectedSource = node;
      showSelectionPill(`Source: ${node.name} · Click destination to route packet`);
      return;
    }

    if (state.selectedSource.name === node.name) {
      toggleNodeAlive(node.name);
      state.selectedSource = null;
      hideSelectionPill();
      return;
    }

    const src = state.selectedSource.name;
    const dst = node.name;
    state.selectedSource = null;
    hideSelectionPill();

    sendMessage(src, dst);
  }

  function showSelectionPill(text) {
    if (selectionText) selectionText.textContent = text;
    if (selectionPill) selectionPill.classList.remove('hidden');
  }

  function hideSelectionPill() {
    if (selectionPill) selectionPill.classList.add('hidden');
  }

  if (btnCancelSelection) {
    btnCancelSelection.addEventListener('click', () => {
      state.selectedSource = null;
      hideSelectionPill();
    });
  }

  // =========================================================
  // 10. Control Bar Handlers
  // =========================================================
  btnEmergencyAlert.addEventListener('click', () => {
    sendEmergencyAlert();
  });

  btnKillRandom.addEventListener('click', () => {
    killRandomNode();
  });

  btnReset.addEventListener('click', () => {
    state.messagesSent = 0;
    state.messagesDelivered = 0;
    state.totalHops = 0;
    state.totalTransmissions = 0;
    state.lastRecoveryTime = 0.0;
    state.recoveryStartTime = null;
    initTopology(state.nodeCount);
    logEvent('PARAM', 'Network topology and counters reset');

    if (state.sseConnected) {
      fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_count: state.nodeCount }),
      }).catch(() => {});
    }
  });

  // Routing Mode Selector
  routingSelector.addEventListener('click', e => {
    const btn = e.target.closest('.segment-btn');
    if (!btn) return;

    routingSelector.querySelectorAll('.segment-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const mode = btn.dataset.mode;
    state.routingMode = mode;
    if (activeRoutingMode) activeRoutingMode.textContent = getRoutingModeLabel(mode);

    logEvent('PARAM', `Routing strategy set to ${getRoutingModeLabel(mode)}`);

    if (state.sseConnected) {
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ routing_mode: mode }),
      }).catch(() => {});
    }
  });

  // Path-Loss Slider
  sliderPathLoss.addEventListener('input', e => {
    const val = parseFloat(e.target.value);
    pathLossExponent = val;
    badgePathLoss.textContent = val.toFixed(1);
    rebuildLinks();

    if (state.sseConnected) {
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ n_exponent: val }),
      }).catch(() => {});
    }
  });

  sliderPathLoss.addEventListener('change', e => {
    const val = parseFloat(e.target.value);
    logEvent('PARAM', `Path loss exponent set to ${val.toFixed(1)}`);
  });

  // Node Count Presets (15, 30, 50)
  nodeCountSelector.addEventListener('click', e => {
    const btn = e.target.closest('.segment-btn');
    if (!btn) return;

    nodeCountSelector.querySelectorAll('.segment-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const count = parseInt(btn.dataset.count, 10);
    initTopology(count);

    if (state.sseConnected) {
      fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_count: count }),
      }).catch(() => {});
    }
  });

  // Event Log Filter Tabs
  if (logFilters) {
    logFilters.addEventListener('click', e => {
      const tab = e.target.closest('.filter-tab');
      if (!tab) return;

      logFilters.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      state.activeFilter = tab.dataset.filter;
      reRenderEventLog();
    });
  }

  btnClearLog.addEventListener('click', () => {
    state.eventLog = [];
    eventStream.innerHTML = '';
    if (logCountBadge) logCountBadge.textContent = '0';
  });

  autoScrollCb.addEventListener('change', e => {
    state.autoScroll = e.target.checked;
  });

  // =========================================================
  // 11. Server-Sent Events (SSE) Client Synchronization
  // =========================================================
  function connectSSE() {
    try {
      if (state.sseSource) {
        state.sseSource.close();
      }

      state.sseSource = new EventSource('/api/stream');

      state.sseSource.onopen = () => {
        state.sseConnected = true;
        connectionDot.className = 'status-dot live';
        connectionStatus.textContent = 'Connected';
      };

      state.sseSource.addEventListener('init', e => {
        try {
          const data = JSON.parse(e.data);
          syncFromServerState(data);
        } catch (err) {}
      });

      state.sseSource.addEventListener('topology_updated', e => {
        try {
          const data = JSON.parse(e.data);
          syncFromServerState(data);
        } catch (err) {}
      });

      state.sseSource.addEventListener('event_log', e => {
        try {
          const item = JSON.parse(e.data);
          if (!state.eventLog.some(existing => existing.id === item.id && existing.time === item.time)) {
            state.eventLog.push(item);
            if (state.eventLog.length > 150) state.eventLog.shift();
            if (logCountBadge) logCountBadge.textContent = state.eventLog.length;
            renderSingleEvent(item);
          }
        } catch (err) {}
      });

      state.sseSource.addEventListener('metrics_updated', e => {
        try {
          const payload = JSON.parse(e.data);
          if (payload.metrics) {
            if (elMetricDelivery) elMetricDelivery.textContent = payload.metrics.delivery_rate.toFixed(1);
            if (elMetricDelay) elMetricDelay.textContent = payload.metrics.avg_delay.toFixed(2);
            if (elMetricOverhead) elMetricOverhead.textContent = payload.metrics.packets_per_msg.toFixed(2);
            if (elMetricActive) elMetricActive.textContent = payload.metrics.active_nodes;
            if (elMetricRecovery) elMetricRecovery.textContent = payload.metrics.recovery_time.toFixed(1);
          }
          if (payload.metric_history && payload.metric_history.delivery_rate) {
            state.metricHistory.delivery_rate = payload.metric_history.delivery_rate;
            drawSparkline(sparkDelivery, state.metricHistory.delivery_rate);
          }
        } catch (err) {}
      });

      state.sseSource.addEventListener('message_result', e => {
        try {
          const res = JSON.parse(e.data);
          if (res.delivered && res.final_path) {
            animateHopChain(res.final_path);
            state.activePath = {
              path: [...res.final_path],
              expiresAt: performance.now() + 3500,
            };
          }
        } catch (err) {}
      });

      state.sseSource.addEventListener('alert_broadcast', e => {
        try {
          const res = JSON.parse(e.data);
          triggerAlertVisuals(res.src || 'N0');
        } catch (err) {}
      });

      state.sseSource.onerror = () => {
        state.sseConnected = false;
        connectionDot.className = 'status-dot standalone';
        connectionStatus.textContent = 'Standalone';
        setTimeout(connectSSE, 4000);
      };
    } catch (err) {
      state.sseConnected = false;
      connectionDot.className = 'status-dot standalone';
      connectionStatus.textContent = 'Standalone';
    }
  }

  function syncFromServerState(serverState) {
    if (!serverState || !serverState.nodes) return;

    serverState.nodes.forEach(sn => {
      const existing = state.nodeMap.get(sn.name);
      if (existing) {
        existing.alive = sn.alive;
        existing.neighbors = sn.neighbors || [];
      } else {
        const newNode = {
          name: sn.name,
          x: sn.x,
          y: sn.y,
          alive: sn.alive,
          radius: 4,
          neighbors: sn.neighbors || [],
        };
        state.nodes.push(newNode);
        state.nodeMap.set(sn.name, newNode);
      }
    });

    if (serverState.config) {
      if (serverState.config.n_exponent !== undefined) {
        pathLossExponent = serverState.config.n_exponent;
        sliderPathLoss.value = pathLossExponent;
        badgePathLoss.textContent = pathLossExponent.toFixed(1);
      }
      if (serverState.config.routing_mode) {
        state.routingMode = serverState.config.routing_mode;
        if (activeRoutingMode) activeRoutingMode.textContent = getRoutingModeLabel(state.routingMode);
        routingSelector.querySelectorAll('.segment-btn').forEach(b => {
          b.classList.toggle('active', b.dataset.mode === state.routingMode);
        });
      }
    }

    rebuildLinks();
    updateCanvasStats();
  }

  // =========================================================
  // 12. Startup & Window Resize
  // =========================================================
  window.addEventListener('resize', () => {
    resizeCanvas();
  });

  resizeCanvas();
  initTopology(30);
  connectSSE();
  requestAnimationFrame(render);

})();
