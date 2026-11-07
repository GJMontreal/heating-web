import { get } from "./api.js";
import { report } from "./alert.js";
import { el, status } from "./dom.js";
import { LEVELS, atLeast, clock, levelOf } from "./format.js";

const REFRESH_MS = 10000;
const UNITS = ["boiler_relay", "boiler_relay_v2", "boiler_relay_v2_shadow", "mqtt_bridge"];
const LINE_COUNTS = [50, 100, 200, 500];
const DEFAULT_LINES = 100;
const LEVEL_CHOICES = [
  ["all", "All levels"],
  ["error", "Error"],
  ["warning", "Warning and above"],
  ["info", "Info and above"],
];
const LEVEL_MARKS = {
  error: ["crit", "✖", "ERROR"],
  warning: ["warn", "⚠", "WARNING"],
  info: ["", "○", "INFO"],
  debug: ["", "·", "DEBUG"],
};

let root = null;
let timer = null;
let loading = false;
let onUpdated = null;
let controls = null;
let output = null;
let entries = [];
let failure = null;

function select(choices, value) {
  const node = el("select", {}, choices.map(([key, label]) => el("option", { text: label, attrs: { value: key } })));
  node.value = value;
  return node;
}

function labelled(text, control) {
  return el("label", {}, [text, control]);
}

function buildControls() {
  const unit = select([["", "All units"], ...UNITS.map((name) => [name, name])], "");
  const level = select(LEVEL_CHOICES, "all");
  const lines = select(LINE_COUNTS.map((count) => [String(count), `${count} lines`]), String(DEFAULT_LINES));
  const refresh = el("button", { className: "chip", text: "Refresh", attrs: { type: "button" } });
  const auto = el("input", { attrs: { type: "checkbox" } });
  unit.addEventListener("change", () => load());
  lines.addEventListener("change", () => load());
  level.addEventListener("change", render);
  refresh.addEventListener("click", () => load());
  auto.addEventListener("change", schedule);
  return { unit, level, lines, refresh, auto };
}

function schedule() {
  clearInterval(timer);
  timer = controls.auto.checked ? setInterval(() => load(), REFRESH_MS) : null;
}

function line(entry) {
  const level = levelOf(entry.priority);
  const mark = level === null ? status("", "?", "-") : status(...LEVEL_MARKS[level]);
  const time = new Date(entry.time);
  return el("div", { className: "line" }, [
    el("span", { className: "muted", text: Number.isNaN(time.getTime()) ? entry.time : clock(time) }),
    el("span", { className: "sec", text: entry.unit === null ? "-" : entry.unit }),
    el("span", { className: level === null ? "" : `level-${level}` }, [mark]),
    el("span", { className: "message", text: entry.message }),
  ]);
}

function render() {
  if (failure !== null) {
    output.replaceChildren(el("div", { className: "empty", text: failure }));
    return;
  }
  const shown = entries.filter((entry) => atLeast(levelOf(entry.priority), controls.level.value));
  if (shown.length === 0) {
    output.replaceChildren(el("div", { className: "empty", text: "No lines match." }));
    return;
  }
  output.replaceChildren(el("div", { className: "card log" }, shown.map(line)));
}

async function load() {
  if (loading) return;
  loading = true;
  const params = { lines: controls.lines.value };
  if (controls.unit.value) params.unit = controls.unit.value;
  try {
    entries = (await get("/api/logs", params)).reverse();
    failure = null;
    report("logs", null);
    onUpdated(clock(new Date()));
  } catch (error) {
    if (error.status === null) {
      report("logs", error);
    } else {
      report("logs", null);
      entries = [];
      failure = error.message;
    }
  } finally {
    loading = false;
  }
  if (root !== null) render();
}

export function startLogs(container, updated) {
  root = container;
  onUpdated = updated;
  controls = buildControls();
  output = el("div");
  const toolbar = el("div", { className: "toolbar" }, [
    labelled("Unit", controls.unit),
    labelled("Level", controls.level),
    labelled("Lines", controls.lines),
    controls.refresh,
    labelled("Auto refresh", controls.auto),
  ]);
  root.replaceChildren(toolbar, output);
  load();
}

export function stopLogs() {
  clearInterval(timer);
  timer = null;
  root = null;
}
