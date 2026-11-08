import { get } from "./api.js";
import { report } from "./alert.js";
import { el, meter, status } from "./dom.js";
import { ageText, clock, temperature } from "./format.js";
import { liveController } from "./controller.js";
import { ioCard, relayRow } from "./hydronic_io.js";

const REFRESH_MS = 10000;
const SHADOW_UNIT = "boiler_relay_v2_shadow";
const SYSTEMS = {
  hydronic: ["Hydronic system", "Boiler, pump and zone valves on the BeagleBone GPIO."],
  electric: ["Electric system", "Radiators on Zigbee relays, switched over MQTT. The relay state is never confirmed."],
};
const UNIT_STATES = {
  active: ["good", "●", "Running"],
  inactive: ["", "○", "Stopped"],
  failed: ["crit", "✖", "Failed"],
};

let root = null;
let timer = null;
let loading = false;
let zones = null;
let services = null;
let io = null;
let onUpdated = null;

function unitStatus(state) {
  const [kind, glyph, label] = UNIT_STATES[state] || ["warn", "?", state];
  return status(kind, glyph, label);
}

function servicesCard() {
  const stats = services.map((unit) =>
    el("div", { className: "stat" }, [
      el("div", { className: "label", text: unit.name }),
      el("div", { className: "value" }, [unitStatus(unit.state)]),
    ]));
  return el("div", { className: "card" }, [el("div", { className: "stats" }, stats)]);
}

function stateLabel(state) {
  if (state === null || state === undefined) return "no state yet";
  return state === 1 ? "Heat" : "Off";
}

function targetMode(state) {
  if (state === null || state === undefined) return "unknown";
  if (state === 0) return "Off";
  if (state === 1) return "Heat";
  return `Off (value ${state})`;
}

function zoneStatus(zone) {
  if (zone.sensor_stale) return status("warn", "⚠", "No heat: reading is stale");
  if (zone.boost === true) return status("good", "▲", "Boost");
  if (zone.heating_cooling_state === 1) return status("good", "●", "Heating");
  if (zone.heating_cooling_state === 0) return status("", "○", "Idle");
  return status("", "?", "No state yet");
}

function readingAge(zone) {
  const reading = zone.current_temperature;
  return ageText(reading === null ? null : reading.age_seconds);
}

function staleNote(zone) {
  return zone.current_temperature === null ? "no reading received" : `last reading ${readingAge(zone)}`;
}

function controlCell(text, value, extraClass = "") {
  return el("dd", { className: "value-with-meter" }, [el("span", { text }), meter(value, extraClass)]);
}

function liveCell(zone) {
  if (zone.control_value === null) return el("dd", { className: "muted", text: "no value" });
  return controlCell(zone.control_value.toFixed(2), zone.control_value);
}

function shadowCell(zone) {
  const shadow = zone.shadow;
  if (shadow === null) return el("dd", { className: "muted", text: "no shadow data" });
  const text = `${stateLabel(shadow.state)}, control ${shadow.control_value.toFixed(2)}`;
  const cell = controlCell(text, shadow.control_value, "shadow");
  const unit = services && services.find((item) => item.name === SHADOW_UNIT);
  if (unit && unit.state !== "active") {
    cell.append(el("span", { className: "muted", text: `last decision, shadow service: ${unit.state}` }));
  }
  return cell;
}

function flag(value) {
  if (value === null || value === undefined) return el("dd", { className: "muted", text: "unknown" });
  return el("dd", { text: value ? "On" : "Off" });
}

function zoneCard(zone) {
  const reading = zone.current_temperature;
  const side = el("div", { className: "side" }, [zoneStatus(zone)]);
  if (zone.sensor_stale) side.append(el("span", { className: "muted", text: staleNote(zone) }));
  const head = el("div", { className: "head" }, [
    el("div", {}, [
      el("div", { className: "name", text: zone.name }),
      el("div", { className: "muted", text: zone.sensor_path }),
    ]),
    side,
  ]);
  const temp = el("div", { className: "big" }, [
    reading === null || zone.sensor_stale ? "–" : temperature(reading.value),
    el("span", { className: "unit", text: "°C" }),
  ]);
  const target = zone.target_temperature === null ? "Target not set" : `Target ${temperature(zone.target_temperature)} °C`;
  const summary = el("div", { className: "summary" }, [temp, el("div", { className: "sec", text: target })]);
  const details = el("dl", { className: "kv" }, [
    el("dt", { text: "Last reading" }), el("dd", { text: readingAge(zone) }),
    el("dt", { text: "Target mode" }), el("dd", { text: targetMode(zone.target_state) }),
    el("dt", { text: "Boost" }), flag(zone.boost),
    el("dt", { text: `${liveController(services).label} control value` }), liveCell(zone),
    el("dt", { text: "Shadow decision" }), shadowCell(zone),
    ...relayRow(io, zone.name),
  ]);
  return el("div", { className: "card zone" }, [head, summary, details]);
}

function sections() {
  const systems = [];
  for (const zone of zones) if (!systems.includes(zone.system)) systems.push(zone.system);
  systems.sort((a, b) => Object.keys(SYSTEMS).indexOf(a) - Object.keys(SYSTEMS).indexOf(b));
  const nodes = [];
  for (const system of systems) {
    const [title, note] = SYSTEMS[system] || [system, ""];
    nodes.push(el("div", { className: "section-title" }, [el("h2", { text: title }), el("span", { className: "muted", text: note })]));
    const cards = zones.filter((zone) => zone.system === system).map(zoneCard);
    if (system === "hydronic" && io !== null) cards.unshift(ioCard(io));
    nodes.push(el("div", { className: "grid" }, cards));
  }
  return nodes;
}

function render() {
  const nodes = [];
  if (services !== null) nodes.push(servicesCard());
  if (zones !== null && zones.length === 0) nodes.push(el("div", { className: "empty", text: "The API returned no zones." }));
  if (zones !== null) nodes.push(...sections());
  root.replaceChildren(...nodes);
}

async function load(onUpdated) {
  if (loading) return;
  loading = true;
  const [liveResult, servicesResult, ioResult] = await Promise.all([
    get("/api/live").then((data) => ({ data }), (error) => ({ error })),
    get("/api/services").then((data) => ({ data }), (error) => ({ error })),
    get("/api/io").then((data) => ({ data }), (error) => ({ error })),
  ]);
  loading = false;
  if (root === null) return;
  report("live", liveResult.error || null);
  report("services", servicesResult.error || null);
  report("io", ioResult.error || null);
  if (liveResult.data) zones = liveResult.data;
  if (servicesResult.data) services = servicesResult.data;
  if (ioResult.data) io = ioResult.data;
  if (liveResult.data || servicesResult.data || ioResult.data) onUpdated(clock(new Date()));
  render();
}

function refreshIfVisible() {
  if (!document.hidden) load(onUpdated);
}

export function startLive(container, updated) {
  root = container;
  onUpdated = updated;
  load(onUpdated);
  timer = setInterval(refreshIfVisible, REFRESH_MS);
  document.addEventListener("visibilitychange", refreshIfVisible);
}

export function stopLive() {
  clearInterval(timer);
  document.removeEventListener("visibilitychange", refreshIfVisible);
  root = null;
}
