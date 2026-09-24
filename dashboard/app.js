const rooms = [
  "Porch",
  "Living Room",
  "Kitchen",
  "Bedroom",
  "Hallway",
  "Garage",
  "Back Door",
  "Utility",
  "Whole Home",
];

const state = {
  recordsByEvent: new Map(),
  eventIds: [],
  index: 0,
  timer: null,
  summary: null,
};

const fileInput = document.querySelector("#file-input");
const eventLabel = document.querySelector("#event-label");
const summaryEl = document.querySelector("#summary");

fileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const payload = JSON.parse(await file.text());
  loadRun(payload);
});

document.querySelector("#prev").addEventListener("click", () => move(-1));
document.querySelector("#next").addEventListener("click", () => move(1));
document.querySelector("#play").addEventListener("click", togglePlay);

function loadRun(payload) {
  state.recordsByEvent.clear();
  for (const record of payload.records || []) {
    const id = record.event.id;
    if (!state.recordsByEvent.has(id)) state.recordsByEvent.set(id, {});
    state.recordsByEvent.get(id)[record.system] = record;
  }
  state.eventIds = [...state.recordsByEvent.keys()].sort((a, b) => a - b);
  state.index = 0;
  state.summary = payload.summary || {};
  summaryEl.textContent = JSON.stringify(state.summary, null, 2);
  render();
}

function move(delta) {
  if (!state.eventIds.length) return;
  state.index = (state.index + delta + state.eventIds.length) % state.eventIds.length;
  render();
}

function togglePlay() {
  const button = document.querySelector("#play");
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
    button.textContent = "Play";
    return;
  }
  state.timer = setInterval(() => move(1), 1600);
  button.textContent = "Pause";
}

function render() {
  if (!state.eventIds.length) {
    renderPlan("A", null);
    renderPlan("B", null);
    return;
  }
  const id = state.eventIds[state.index];
  const pair = state.recordsByEvent.get(id);
  const text = pair.A?.event.text || pair.B?.event.text || "";
  eventLabel.textContent = `Event ${id}: ${text}`;
  renderPlan("A", pair.A);
  renderPlan("B", pair.B);
}

function renderPlan(system, record) {
  const plan = document.querySelector(`#plan-${system}`);
  const details = document.querySelector(`#details-${system}`);
  plan.innerHTML = "";
  const activeAgents = record ? activeAgentNames(record) : [];
  const fallbackAgents = record ? fallbackAgentNames(record) : [];
  for (const room of rooms) {
    const roomEl = document.createElement("div");
    roomEl.className = "room";
    if (room === "Whole Home" && record?.overall_home_state?.value === "alert") {
      roomEl.classList.add("alert");
    }
    if (isRoomActive(room, record, activeAgents)) roomEl.classList.add("active");
    roomEl.innerHTML = `
      <div class="room-name">${room}</div>
      <div class="icons">${iconsForRoom(room, record, activeAgents)}</div>
      ${fallbackBadge(room, fallbackAgents)}
    `;
    plan.appendChild(roomEl);
  }
  details.textContent = record
    ? JSON.stringify(compactDetails(record), null, 2)
    : "No record loaded.";
}

function activeAgentNames(record) {
  return Object.entries(record.agents)
    .filter(([, run]) => run.decision.relevant.value === "relevant")
    .map(([agent]) => agent);
}

function fallbackAgentNames(record) {
  const names = [];
  for (const [agent, run] of Object.entries(record.agents)) {
    const used = Object.values(run.decision).some((field) => field.used_llm_fallback);
    if (used) names.push(agent);
  }
  if (record.overall_home_state.used_llm_fallback) names.push("overall");
  return names;
}

function isRoomActive(room, record, agents) {
  if (!record) return false;
  const text = record.event.text.toLowerCase();
  if (room === "Living Room" && text.includes("living room")) return true;
  if (room === "Kitchen" && text.includes("kitchen")) return true;
  if (room === "Bedroom" && text.includes("bedroom")) return true;
  if (room === "Porch" && text.includes("porch")) return true;
  if (room === "Hallway" && text.includes("hallway")) return true;
  if (room === "Garage" && text.includes("garage")) return true;
  if (room === "Back Door" && text.includes("back door")) return true;
  if (room === "Utility" && agents.includes("appliances")) return true;
  return room === "Whole Home" && agents.length > 1;
}

function iconsForRoom(room, record, agents) {
  const icons = [];
  if (room === "Living Room" || room === "Kitchen" || room === "Porch" || room === "Hallway" || room === "Whole Home") {
    icons.push(`<span class="icon ${agents.includes("lighting") ? "on" : ""}" title="Lighting">L</span>`);
  }
  if (room === "Bedroom" || room === "Whole Home") {
    icons.push(`<span class="icon ${agents.includes("climate") ? "cool" : ""}" title="Thermostat">T</span>`);
  }
  if (room === "Garage" || room === "Back Door" || room === "Whole Home") {
    icons.push(`<span class="icon ${agents.includes("security") ? "locked" : ""}" title="Lock">K</span>`);
  }
  if (room === "Kitchen" || room === "Utility") {
    icons.push(`<span class="icon ${agents.includes("appliances") ? "on" : ""}" title="Appliance">A</span>`);
  }
  return icons.join("");
}

function fallbackBadge(room, fallbackAgents) {
  if (!fallbackAgents.length) return "";
  const roomMatches =
    (room === "Whole Home" && fallbackAgents.includes("overall")) ||
    (room === "Utility" && fallbackAgents.includes("appliances")) ||
    (["Garage", "Back Door"].includes(room) && fallbackAgents.includes("security")) ||
    (["Bedroom", "Whole Home"].includes(room) && fallbackAgents.includes("climate")) ||
    (["Living Room", "Kitchen", "Porch", "Hallway", "Whole Home"].includes(room) && fallbackAgents.includes("lighting"));
  return roomMatches ? `<span class="fallback">LLM fallback</span>` : "";
}

function compactDetails(record) {
  const agents = {};
  for (const [agent, run] of Object.entries(record.agents)) {
    agents[agent] = {
      relevant: run.decision.relevant.value,
      tool: run.tool.tool,
      log: run.decision.needs_written_log.value,
      fallback: Object.values(run.decision).some((field) => field.used_llm_fallback),
    };
  }
  return {
    home_state: record.overall_home_state.value,
    final_confirmation: record.final_confirmation,
    agents,
  };
}

render();
