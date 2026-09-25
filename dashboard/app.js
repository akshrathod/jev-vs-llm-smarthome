const rooms = [
  { id: "living_room", label: "Living Room", domains: ["lighting", "climate"] },
  { id: "bedroom", label: "Bedroom", domains: ["lighting", "climate"] },
  { id: "kitchen", label: "Kitchen", domains: ["lighting", "appliance", "security"] },
  { id: "entrance", label: "Entrance", domains: ["lighting", "security"] },
];

const state = {
  recordsBySystem: { A: [], B: [] },
  currentIndex: { A: -1, B: -1 },
  baselineHomeState: defaultHomeState(),
  startedAt: 0,
  pausedAt: 0,
  playing: false,
  raf: null,
  speed: 2,
};

const fileInput = document.querySelector("#file-input");
const eventLabel = document.querySelector("#event-label");
const summaryEl = document.querySelector("#summary");
const speedInput = document.querySelector("#speed");
const speedValue = document.querySelector("#speed-value");

fileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  loadRun(JSON.parse(await file.text()));
});

const runParam = new URLSearchParams(window.location.search).get("run");
if (runParam) {
  fetch(runParam)
    .then((response) => response.json())
    .then(loadRun)
    .catch((error) => {
      summaryEl.textContent = `Could not load run: ${error.message}`;
    });
}

document.querySelector("#play").addEventListener("click", togglePlay);
document.querySelector("#reset").addEventListener("click", resetPlayback);
speedInput.addEventListener("input", () => {
  const elapsed = playbackElapsedMs();
  state.speed = Number(speedInput.value);
  speedValue.textContent = `${state.speed}x`;
  state.startedAt = performance.now() - elapsed / state.speed;
});

function loadRun(payload) {
  stopPlayback();
  state.recordsBySystem = { A: [], B: [] };
  for (const record of payload.records || []) {
    if (record.system === "A" || record.system === "B") {
      state.recordsBySystem[record.system].push(record);
    }
  }
  state.baselineHomeState = homeStateFromFirstEvent(payload.records || []);
  for (const system of ["A", "B"]) {
    let elapsed = 0;
    state.recordsBySystem[system]
      .sort((a, b) => a.event.id - b.event.id)
      .forEach((record) => {
        record.playbackStartMs = elapsed;
        elapsed += eventLatencyMs(record);
        record.playbackEndMs = elapsed;
      });
    state.currentIndex[system] = state.recordsBySystem[system].length ? 0 : -1;
  }
  summaryEl.innerHTML = formatSummary(payload.summary || {});
  renderAt(0);
}

function eventLatencyMs(record) {
  const costs = record.latency_cost || {};
  return ["decision_layer", "fallback_layer", "tool_layer"].reduce((sum, key) => {
    return sum + Number(costs[key]?.latency_ms || 0);
  }, 0);
}

function playbackElapsedMs() {
  if (!state.playing) return state.pausedAt;
  return (performance.now() - state.startedAt) * state.speed;
}

function togglePlay() {
  if (!hasRecords()) return;
  if (state.playing) {
    state.pausedAt = playbackElapsedMs();
    stopPlayback();
    return;
  }
  state.playing = true;
  state.startedAt = performance.now() - state.pausedAt / state.speed;
  document.querySelector("#play").textContent = "Pause";
  tick();
}

function stopPlayback() {
  state.playing = false;
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = null;
  document.querySelector("#play").textContent = "Play";
}

function resetPlayback() {
  stopPlayback();
  state.pausedAt = 0;
  state.currentIndex = {
    A: state.recordsBySystem.A.length ? 0 : -1,
    B: state.recordsBySystem.B.length ? 0 : -1,
  };
  renderAt(0);
}

function tick() {
  const elapsed = playbackElapsedMs();
  renderAt(elapsed);
  if (elapsed >= totalDurationMs()) {
    state.pausedAt = totalDurationMs();
    stopPlayback();
    return;
  }
  state.raf = requestAnimationFrame(tick);
}

function renderAt(elapsedMs) {
  for (const system of ["A", "B"]) {
    const records = state.recordsBySystem[system];
    const index = indexForElapsed(records, elapsedMs);
    state.currentIndex[system] = index;
    renderSystem(system, records[index] || null, elapsedMs, records);
  }
  eventLabel.textContent = hasRecords()
    ? `Shared clock: ${formatMs(elapsedMs)} recorded time`
    : "No run loaded";
}

function indexForElapsed(records, elapsedMs) {
  if (!records.length) return -1;
  let completed = -1;
  for (let i = 0; i < records.length; i += 1) {
    if (elapsedMs >= records[i].playbackEndMs) completed = i;
    if (elapsedMs < records[i].playbackEndMs) return completed;
  }
  return records.length - 1;
}

function renderSystem(system, record, sharedElapsedMs, records) {
  const systemTotal = records.at(-1)?.playbackEndMs || 0;
  const homeState = homeStateFor(records, state.currentIndex[system]);
  document.querySelector(`#elapsed-${system}`).textContent = formatMs(Math.min(sharedElapsedMs, systemTotal));
  document.querySelector(`#event-${system}`).textContent = record
    ? `Event ${record.event.id}: ${record.event.text}`
    : records.length
      ? "Waiting for first event latency to elapse..."
      : "No record loaded";

  const plan = document.querySelector(`#plan-${system}`);
  plan.innerHTML = "";
  for (const room of rooms) {
    const roomEl = document.createElement("div");
    roomEl.className = "room";
    if (roomIsActive(record, room.id)) roomEl.classList.add("active");
    roomEl.innerHTML = `
      <div class="room-name">${room.label}</div>
      <div class="icons">${room.domains.map((domain) => renderDomainIcon(record, room.id, domain, homeState)).join("")}</div>
    `;
    plan.appendChild(roomEl);
  }
  document.querySelector(`#details-${system}`).innerHTML = record ? formatRecord(record) : "No record loaded.";
}

function renderDomainIcon(record, roomId, domain, homeState) {
  const active = record?.domain === domain && outputTargetsRoom(record.tool?.output, roomId);
  const fallback = domainFallbackBadge(record, domain);
  if (domain === "lighting") {
    const brightness = homeState.lighting[roomId] ?? 50;
    const stateText = brightness === 0 ? "off" : `${brightness}%`;
    return `<div class="agent ${active ? "active" : ""}" title="Lighting"><span>L</span><span>${stateText}</span>${fallback}</div>`;
  }
  if (domain === "climate") {
    const temperature = homeState.climate[roomId] ?? 70;
    return `<div class="agent ${active ? "active" : ""}" title="Climate"><span>T</span><span>${temperature}</span>${fallback}</div>`;
  }
  if (domain === "security") {
    const stateText = homeState.security[roomId] || "locked";
    return `<div class="agent ${active ? "active" : ""}" title="Security"><span>${stateText}</span>${fallback}</div>`;
  }
  const applianceState = homeState.appliances[roomId] || { appliance: "appliance", action: "idle" };
  const appliance = applianceState.appliance;
  const action = applianceState.action;
  return `<div class="agent ${active ? "active" : ""}" title="Appliance"><span>${appliance}</span><span>${action}</span>${fallback}</div>`;
}

function defaultHomeState() {
  return {
    lighting: { living_room: 50, bedroom: 50, kitchen: 50, entrance: 50 },
    climate: { living_room: 70, bedroom: 70 },
    security: { entrance: "locked", kitchen: "locked" },
    appliances: { kitchen: { appliance: "appliance", action: "idle" } },
  };
}

function homeStateFromFirstEvent(records) {
  const firstRecord = [...records].sort((a, b) => a.event.id - b.event.id)[0];
  const baseline = defaultHomeState();
  const initial = firstRecord?.event?.initial_state || {};
  return {
    ...baseline,
    lighting: { ...baseline.lighting, ...(initial.lighting || {}) },
    climate: { ...baseline.climate, ...(initial.climate || {}) },
  };
}

function homeStateFor(records, currentIndex) {
  const homeState = structuredClone(state.baselineHomeState);
  for (let i = 0; i <= currentIndex; i += 1) {
    applyToolOutput(homeState, records[i]?.tool?.output);
  }
  return homeState;
}

function applyToolOutput(homeState, output) {
  if (!output) return;
  if (output.room && Object.prototype.hasOwnProperty.call(output, "brightness")) {
    homeState.lighting[output.room] = Number(output.brightness);
    return;
  }
  if (output.room && Object.prototype.hasOwnProperty.call(output, "target_f")) {
    homeState.climate[output.room] = Number(output.target_f);
    return;
  }
  if (output.door) {
    const room = output.door === "kitchen_back_door" ? "kitchen" : "entrance";
    homeState.security[room] = output.state;
    return;
  }
  if (output.appliance) {
    homeState.appliances.kitchen = {
      appliance: output.appliance,
      action: output.action,
    };
  }
}

function outputTargetsRoom(output, roomId) {
  if (!output || !Object.keys(output).length) return false;
  if (output.room === roomId) return true;
  if (roomId === "entrance" && output.door === "entrance_front_door") return true;
  if (roomId === "kitchen" && (output.door === "kitchen_back_door" || output.appliance)) return true;
  return false;
}

function roomIsActive(record, roomId) {
  return Boolean(record && outputTargetsRoom(record.tool?.output, roomId));
}

function domainFallbackBadge(record, domain) {
  if (!record || record.domain !== domain) return "";
  const supervisorFallback = record.supervisor?.target_domain?.used_llm_fallback;
  const domainFallback = Object.values(record.domain_decision || {}).some((field) => field.used_llm_fallback);
  return supervisorFallback || domainFallback ? `<span class="fallback">LLM fallback</span>` : "";
}

function formatRecord(record) {
  const domainDecision = record.domain_decision || {};
  const fields = Object.entries(domainDecision)
    .map(([key, field]) => `${key}=${field.value}`)
    .join(", ") || "none";
  return [
    `<strong>Domain:</strong> ${record.domain}`,
    `<strong>Decision:</strong> ${fields}`,
    `<strong>Tool:</strong> ${record.tool.tool}`,
    `<strong>Event latency:</strong> ${formatMs(eventLatencyMs(record))}`,
    `<strong>Confirmation:</strong> ${escapeHtml(record.final_confirmation)}`,
  ].join("<br>");
}

function formatSummary(summary) {
  if (!Object.keys(summary).length) return "Load a benchmark JSON file to begin.";
  const lines = Object.entries(summary)
    .filter(([key]) => key !== "evaluation")
    .map(([system, value]) => {
      const fallbackRate = Number(value.fallback_rate || 0) * 100;
      return `<strong>System ${system}</strong>: events=${value.events}, fallback rate=${fallbackRate.toFixed(1)}%, decision latency=${formatMs(value.decision_latency_ms || 0)}`;
    });
  const evaluation = summary.evaluation;
  if (evaluation) {
    lines.push("<strong>Accuracy</strong>");
    for (const [system, value] of Object.entries(evaluation.accuracy || {})) {
      if (Object.prototype.hasOwnProperty.call(value, "categorical")) {
        lines.push(`System ${system}: categorical=${value.categorical.toFixed(3)}, magnitude=${value.magnitude_directional.toFixed(3)}`);
      } else {
        lines.push(`System ${system}: domain=${value.target_domain.toFixed(3)}, fields=${value.domain_fields.toFixed(3)}`);
      }
    }
    lines.push("<strong>Agreement</strong>");
    for (const [key, value] of Object.entries(evaluation.inter_system_agreement || {})) {
      lines.push(`${key}: ${(value * 100).toFixed(1)}%`);
    }
  }
  return lines.join("<br>");
}

function formatMs(ms) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

function hasRecords() {
  return state.recordsBySystem.A.length || state.recordsBySystem.B.length;
}

function totalDurationMs() {
  return Math.max(
    state.recordsBySystem.A.at(-1)?.playbackEndMs || 0,
    state.recordsBySystem.B.at(-1)?.playbackEndMs || 0
  );
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

renderAt(0);
