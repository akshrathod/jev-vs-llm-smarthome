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
  replayHomeState: defaultHomeState(),
  startedAt: 0,
  pausedAt: 0,
  playing: false,
  raf: null,
  speed: 2,
  mode: "replay",
};

const fileInput = document.querySelector("#file-input");
const fileStatus = document.querySelector("#file-status");
const eventLabel = document.querySelector("#event-label");
const summaryEl = document.querySelector("#summary");
const speedInput = document.querySelector("#speed");
const speedValue = document.querySelector("#speed-value");
const themeToggle = document.querySelector("#theme-toggle");
const liveForm = document.querySelector("#live-form");
const liveCommandInput = document.querySelector("#live-command");
const liveStatus = document.querySelector("#live-status");
const resetDefaultsButton = document.querySelector("#reset-defaults");

applyTheme(localStorage.getItem("smartHomeTheme") || "light");

fileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    validateRunPayload(payload);
    loadRun(payload);
    fileStatus.textContent = loadedFileMessage(file.name, payload.records);
    fileStatus.className = "file-status success";
  } catch (error) {
    fileStatus.textContent = `Could not load ${file.name}: ${error.message}`;
    fileStatus.className = "file-status error";
  }
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

document.querySelector("#prev").addEventListener("click", () => stepPlayback(-1));
document.querySelector("#play").addEventListener("click", togglePlay);
document.querySelector("#next").addEventListener("click", () => stepPlayback(1));
document.querySelector("#reset").addEventListener("click", resetPlayback);
themeToggle.addEventListener("click", toggleTheme);
liveForm.addEventListener("submit", runLiveCommand);
resetDefaultsButton.addEventListener("click", resetToDefaults);
speedInput.addEventListener("input", () => {
  const elapsed = playbackElapsedMs();
  state.speed = Number(speedInput.value);
  speedValue.textContent = `${state.speed}x`;
  state.startedAt = performance.now() - elapsed / state.speed;
});

function loadRun(payload) {
  stopPlayback();
  state.mode = payload.mode || "replay";
  state.pausedAt = 0;
  state.recordsBySystem = { A: [], B: [] };
  for (const record of payload.records || []) {
    if (record.system === "A" || record.system === "B") {
      state.recordsBySystem[record.system].push(record);
    }
  }
  state.replayHomeState = homeStateFromFirstEvent(payload.records || []);
  state.baselineHomeState = structuredClone(state.replayHomeState);
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
  summaryEl.innerHTML = formatSummary(payload.summary || {}, state.mode === "live", payload.records || []);
  renderAt(0);
}

function validateRunPayload(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("file must contain a JSON object");
  }
  if (!Array.isArray(payload.records)) {
    throw new Error("missing records array");
  }
  if (!payload.records.length) {
    throw new Error("records array is empty");
  }
  for (const [index, record] of payload.records.entries()) {
    if (!record || typeof record !== "object") {
      throw new Error(`record ${index + 1} is not an object`);
    }
    if (record.system !== "A" && record.system !== "B") {
      throw new Error(`record ${index + 1} has invalid system`);
    }
    if (!record.event || typeof record.event.id === "undefined" || !record.event.text) {
      throw new Error(`record ${index + 1} is missing event id/text`);
    }
    if (!record.latency_cost?.decision_layer || !record.latency_cost?.fallback_layer || !record.latency_cost?.tool_layer) {
      throw new Error(`record ${index + 1} is missing latency/cost layers`);
    }
  }
}

function loadedFileMessage(filename, records) {
  const events = new Set(records.map((record) => record.event.id));
  const systems = [...new Set(records.map((record) => displaySystem(record.system)))].sort();
  return `Loaded ${filename} -- ${events.size} events, ${systems.join(" vs ")}`;
}

function loadLiveRun(payload) {
  payload.mode = "live";
  loadRun(payload);
  const elapsed = totalDurationMs();
  state.pausedAt = elapsed;
  renderAt(elapsed);
  state.baselineHomeState = finalHomeState();
  summaryEl.innerHTML = formatSummary(payload.summary || {}, true, payload.records || []);
  liveStatus.innerHTML = `<strong class="comparison-sentence">${escapeHtml(liveComparisonSentence(payload.records || []))}</strong>`;
}

async function runLiveCommand(event) {
  event.preventDefault();
  const command = liveCommandInput.value.trim();
  if (!command) return;
  liveStatus.textContent = "Running both systems...";
  try {
    const response = await fetch("/api/run-command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command,
        initial_state: state.baselineHomeState,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Live command failed");
    }
    loadLiveRun(payload);
  } catch (error) {
    liveStatus.textContent = `Live command failed: ${error.message}`;
  }
}

function resetToDefaults() {
  stopPlayback();
  state.mode = "live";
  state.recordsBySystem = { A: [], B: [] };
  state.currentIndex = { A: -1, B: -1 };
  state.baselineHomeState = defaultHomeState();
  state.replayHomeState = defaultHomeState();
  state.pausedAt = 0;
  summaryEl.textContent = "Live state reset to defaults.";
  liveStatus.textContent = "Live state reset to defaults.";
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

function stepPlayback(delta) {
  if (!hasRecords()) return;
  stopPlayback();
  const eventIds = sortedEventIds();
  if (!eventIds.length) return;
  const currentPosition = currentPlaybackEventPosition(eventIds);
  const nextPosition = Math.max(0, Math.min(eventIds.length - 1, currentPosition + delta));
  state.pausedAt = elapsedForEventId(eventIds[nextPosition]);
  renderAt(state.pausedAt);
}

function sortedEventIds() {
  return [...new Set([...state.recordsBySystem.A, ...state.recordsBySystem.B].map((record) => record.event.id))]
    .sort((a, b) => a - b);
}

function currentPlaybackEventPosition(eventIds) {
  let position = -1;
  for (let i = 0; i < eventIds.length; i += 1) {
    if (state.pausedAt >= elapsedForEventId(eventIds[i])) {
      position = i;
    }
  }
  return position;
}

function elapsedForEventId(eventId) {
  const matching = [...state.recordsBySystem.A, ...state.recordsBySystem.B]
    .filter((record) => record.event.id === eventId)
    .map((record) => record.playbackEndMs || 0);
  return matching.length ? Math.max(...matching) : 0;
}

function toggleTheme() {
  const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(nextTheme);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("smartHomeTheme", theme);
  themeToggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
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
  if (state.mode === "replay") {
    state.baselineHomeState = currentlyRenderedHomeState();
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
  const fallback = domainFallbackBadge(record, roomId, domain);
  if (domain === "lighting") {
    const brightness = homeState.lighting[roomId] ?? 50;
    const stateText = brightness === 0 ? "off" : `${brightness}%`;
    return `
      <div class="agent agent-lighting ${active ? "active changed" : ""}" title="Lighting brightness ${stateText}">
        ${icon("lightbulb", { level: brightness })}
        <span class="agent-label">Lighting</span>
        <span class="agent-value">${stateText}</span>
        ${fallback}
      </div>
    `;
  }
  if (domain === "climate") {
    const temperature = homeState.climate[roomId] ?? 70;
    return `
      <div class="agent agent-climate ${active ? "active changed" : ""}" title="Climate target ${temperature}F">
        ${icon("thermostat", { temperature })}
        <span class="agent-label">Climate</span>
        <span class="agent-value temperature" style="color: ${temperatureColor(temperature)}">${temperature}F</span>
        ${fallback}
      </div>
    `;
  }
  if (domain === "security") {
    const stateText = homeState.security[roomId] || "locked";
    return `
      <div class="agent agent-security ${active ? "active changed" : ""}" title="Security ${stateText}">
        ${icon(stateText === "unlocked" ? "unlock" : "lock")}
        <span class="agent-label">Security</span>
        <span class="agent-value">${stateText}</span>
        ${fallback}
      </div>
    `;
  }
  const applianceState = homeState.appliances[roomId] || { appliance: "appliance", action: "idle" };
  const hasAppliance = applianceState.appliance && applianceState.appliance !== "appliance";
  const appliance = hasAppliance ? displayValue(applianceState.appliance) : "No appliance selected";
  const action = hasAppliance ? displayValue(applianceState.action) : "";
  const applianceValue = hasAppliance ? `${appliance} ${action}` : appliance;
  return `
    <div class="agent agent-appliance ${active ? "active changed" : ""}" title="Appliance ${applianceValue}">
      ${icon("plug")}
      <span class="agent-label">Appliance</span>
      <span class="agent-value">${applianceValue}</span>
      ${fallback}
    </div>
  `;
}

function icon(name, options = {}) {
  if (name === "lightbulb") {
    const level = Number(options.level || 0);
    const opacity = Math.max(0.18, level / 100);
    const glow = Math.round(level / 8);
    return `
      <svg class="agent-icon bulb-icon" style="--bulb-opacity: ${opacity}; --bulb-glow: ${glow}px" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M9 21h6" />
        <path d="M10 17h4" />
        <path class="bulb-fill" d="M8 10a4 4 0 1 1 8 0c0 1.4-.7 2.3-1.5 3.2-.6.7-1 1.3-1.1 2.3h-2.8c-.1-1-.5-1.6-1.1-2.3C8.7 12.3 8 11.4 8 10Z" />
      </svg>
    `;
  }
  if (name === "thermostat") {
    const temperature = Number(options.temperature || 70);
    return `
      <svg class="agent-icon" viewBox="0 0 24 24" aria-hidden="true" style="color: ${temperatureColor(temperature)}">
        <path d="M14 14.8V5a3 3 0 0 0-6 0v9.8a5 5 0 1 0 6 0Z" />
        <path d="M11 6v9" />
      </svg>
    `;
  }
  if (name === "unlock") {
    return `
      <svg class="agent-icon" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="11" width="14" height="10" rx="2" />
        <path d="M8 11V7a4 4 0 0 1 7.4-2.1" />
      </svg>
    `;
  }
  if (name === "lock") {
    return `
      <svg class="agent-icon" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="11" width="14" height="10" rx="2" />
        <path d="M8 11V7a4 4 0 0 1 8 0v4" />
      </svg>
    `;
  }
  return `
    <svg class="agent-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 22v-5" />
      <path d="M9 8V2" />
      <path d="M15 8V2" />
      <path d="M7 8h10v4a5 5 0 0 1-10 0V8Z" />
    </svg>
  `;
}

function temperatureColor(temperature) {
  const min = 65;
  const max = 78;
  const ratio = Math.max(0, Math.min(1, (Number(temperature) - min) / (max - min)));
  const hue = 210 - ratio * 200;
  return `hsl(${hue}, 78%, 42%)`;
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
  const homeState = structuredClone(state.replayHomeState);
  for (let i = 0; i <= currentIndex; i += 1) {
    applyToolOutput(homeState, records[i]?.tool?.output);
  }
  return homeState;
}

function currentlyRenderedHomeState() {
  if (state.recordsBySystem.B.length && state.currentIndex.B >= 0) {
    return homeStateFor(state.recordsBySystem.B, state.currentIndex.B);
  }
  if (state.recordsBySystem.A.length && state.currentIndex.A >= 0) {
    return homeStateFor(state.recordsBySystem.A, state.currentIndex.A);
  }
  return structuredClone(state.replayHomeState);
}

function finalHomeState() {
  const records = state.recordsBySystem.B.length ? state.recordsBySystem.B : state.recordsBySystem.A;
  return homeStateFor(records, records.length - 1);
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

function domainFallbackBadge(record, roomId, domain) {
  if (!record || record.domain !== domain) return "";
  if (!outputTargetsRoom(record.tool?.output, roomId)) return "";
  const supervisorFallback = record.supervisor?.target_domain?.used_llm_fallback;
  const domainFallback = Object.values(record.domain_decision || {}).some((field) => field.used_llm_fallback);
  return supervisorFallback || domainFallback ? `<span class="fallback">LLM fallback</span>` : "";
}

function formatRecord(record) {
  const domainDecision = record.domain_decision || {};
  const fields = Object.entries(domainDecision)
    .map(([key, field]) => `${displayField(key)}=${displayValue(field.value)}`)
    .join(", ") || "none";
  return [
    `<strong>Domain:</strong> ${displayDomain(record.domain)}`,
    `<strong>Decision:</strong> ${fields}`,
    `<strong>Tool:</strong> ${displayTool(record.tool.tool)}`,
    `<strong>Event latency:</strong> ${formatMs(eventLatencyMs(record))}`,
    `<strong>Decision cost:</strong> ${formatUsd(record.latency_cost?.decision_layer?.cost_usd || 0)}`,
    `<strong>Confirmation:</strong> ${escapeHtml(record.final_confirmation)}`,
  ].join("<br>");
}

function displayDomain(domain) {
  return {
    climate: "Climate",
    lighting: "Lighting",
    security: "Security",
    appliance: "Appliance",
    none: "None",
  }[domain] || displayValue(domain);
}

function displayTool(tool) {
  return {
    adjust_thermostat: "Adjust Thermostat",
    set_light: "Set Light",
    set_door_lock: "Set Door Lock",
    control_appliance: "Control Appliance",
    none: "None",
  }[tool] || displayValue(tool);
}

function displayField(field) {
  return {
    target_room: "Target room",
    target_temperature: "Target temperature",
    brightness: "Brightness",
    door: "Door",
    state: "Lock state",
    appliance: "Appliance",
    action: "Action",
  }[field] || displayValue(field);
}

function displayValue(value) {
  return String(value)
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatSummary(summary, hideEvaluation = false, records = []) {
  if (!Object.keys(summary).length) return "Load a benchmark JSON file to begin.";
  const lines = [];
  if (!hideEvaluation) {
    const sentence = aggregateComparisonSentence(summary, records);
    if (sentence) {
      lines.push(`<div class="comparison-sentence"><strong>${sentence}</strong></div>`);
    }
  }
  lines.push(...Object.entries(summary)
    .filter(([key]) => key !== "evaluation")
    .map(([system, value]) => {
      const fallbackRate = Number(value.fallback_rate || 0) * 100;
      return `<strong>${displaySystem(system)}</strong>: events=${value.events}, fallback rate=${fallbackRate.toFixed(1)}%, decision latency=${formatMs(value.decision_latency_ms || 0)}, decision cost=${formatUsd(value.decision_cost_usd || 0)}`;
    }));
  const evaluation = summary.evaluation;
  if (evaluation && !hideEvaluation) {
    lines.push("<strong>Accuracy</strong>");
    for (const [system, value] of Object.entries(evaluation.accuracy || {})) {
      if (Object.prototype.hasOwnProperty.call(value, "categorical")) {
        lines.push(`${displaySystem(system)}: categorical=${value.categorical.toFixed(3)}, magnitude=${value.magnitude_directional.toFixed(3)}`);
      } else {
        lines.push(`${displaySystem(system)}: domain=${value.target_domain.toFixed(3)}, fields=${value.domain_fields.toFixed(3)}`);
      }
    }
    lines.push("<strong>Agreement</strong>");
    for (const [key, value] of Object.entries(evaluation.inter_system_agreement || {})) {
      lines.push(`${key}: ${(value * 100).toFixed(1)}%`);
    }
  }
  return lines.join("<br>");
}

function aggregateComparisonSentence(summary, records) {
  const a = summary.A;
  const b = summary.B;
  if (!a || !b) return "";
  const decisionSpeedPart = comparisonPart(
    Number(a.decision_latency_ms || 0),
    Number(b.decision_latency_ms || 0),
    "faster",
    "slower"
  );
  const decisionCostPart = comparisonPart(
    Number(a.decision_cost_usd || 0),
    Number(b.decision_cost_usd || 0),
    "cheaper",
    "more expensive"
  );
  const e2eTotals = endToEndTotals(records);
  const endToEndSpeedPart = comparisonPart(e2eTotals.A.latencyMs, e2eTotals.B.latencyMs, "faster", "slower");
  const endToEndCostPart = comparisonPart(e2eTotals.A.costUsd, e2eTotals.B.costUsd, "cheaper", "more expensive");
  const decisionSentence = `System B's decision layer was ${decisionSpeedPart} and ${decisionCostPart} than System A's.`;
  if (!fallbackOccurred(records)) return decisionSentence;
  return `${decisionSentence} Including fallback and tool overhead, System B was ${endToEndSpeedPart} and ${endToEndCostPart} end-to-end.`;
}

function liveComparisonSentence(records) {
  const bySystem = Object.fromEntries(records.map((record) => [record.system, record]));
  const a = bySystem.A?.latency_cost?.decision_layer;
  const b = bySystem.B?.latency_cost?.decision_layer;
  if (!a || !b) return "Live command complete. Results are shown below.";
  const latencyA = Number(a.latency_ms || 0);
  const latencyB = Number(b.latency_ms || 0);
  const costA = Number(a.cost_usd || 0);
  const costB = Number(b.cost_usd || 0);
  const decisionSpeedPart = comparisonPart(latencyA, latencyB, "faster", "slower");
  const decisionCostPart = comparisonPart(costA, costB, "cheaper", "more expensive");
  const e2eTotals = endToEndTotals(records);
  const endToEndSpeedPart = comparisonPart(e2eTotals.A.latencyMs, e2eTotals.B.latencyMs, "faster", "slower");
  const endToEndCostPart = comparisonPart(e2eTotals.A.costUsd, e2eTotals.B.costUsd, "cheaper", "more expensive");
  const bFallback = fallbackOccurred([bySystem.B].filter(Boolean));
  const reason = latencyB > latencyA && bFallback ? ", due to a low-confidence fallback" : "";
  const decisionSentence = `For this command, System B's decision layer was ${decisionSpeedPart} and ${decisionCostPart} than System A's${reason}.`;
  if (!fallbackOccurred(records)) return decisionSentence;
  return `${decisionSentence} Including fallback and tool overhead, System B was ${endToEndSpeedPart} and ${endToEndCostPart} end-to-end.`;
}

function fallbackOccurred(records) {
  return records.some((record) => {
    const fallback = record?.latency_cost?.fallback_layer || {};
    return Number(fallback.latency_ms || 0) > 0 || Number(fallback.cost_usd || 0) > 0;
  });
}

function endToEndTotals(records) {
  return records.reduce((totals, record) => {
    if (record.system !== "A" && record.system !== "B") return totals;
    for (const layer of ["decision_layer", "fallback_layer", "tool_layer"]) {
      const cost = record.latency_cost?.[layer] || {};
      totals[record.system].latencyMs += Number(cost.latency_ms || 0);
      totals[record.system].costUsd += Number(cost.cost_usd || 0);
    }
    return totals;
  }, {
    A: { latencyMs: 0, costUsd: 0 },
    B: { latencyMs: 0, costUsd: 0 },
  });
}

function displaySystem(system) {
  return {
    A: "System A - LLM decision",
    B: "System B - Jev decision",
  }[system] || `System ${system}`;
}

function comparisonPart(aValue, bValue, betterWord, worseWord) {
  if (aValue === 0 && bValue === 0) return `1.0x ${betterWord}`;
  if (bValue <= aValue) {
    const ratio = aValue === 0 ? 1 : aValue / Math.max(bValue, Number.EPSILON);
    return `${ratio.toFixed(1)}x ${betterWord}`;
  }
  const ratio = bValue / Math.max(aValue, Number.EPSILON);
  return `${ratio.toFixed(1)}x ${worseWord}`;
}

function formatMs(ms) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

function formatUsd(value) {
  return `$${Number(value || 0).toFixed(6)}`;
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
