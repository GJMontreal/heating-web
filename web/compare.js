import { get } from "./api.js";
import { report } from "./alert.js";
import { barChart, legend, niceTicks } from "./chart.js";
import { el, status } from "./dom.js";
import { LEGACY_PID, liveChanged, liveController, livePid, markerLabel, pidText, rangeController, samePid } from "./controller.js";
import { clock } from "./format.js";

const REFRESH_MS = 60000;
const RANGES = [["24 hours", 24], ["7 days", 168], ["14 days", 336]];
const METRICS = [["control", "Mean control value", "ctl", "sh_ctl"], ["fraction", "On-fraction", "on_fraction", "sh_on_fraction"]];
const DIVERGES_ABOVE = 0.05;
const MIN_SCALE = 0.2;
const BLUE = "var(--s1)";
const ORANGE = "var(--s2)";

let root = null;
let timer = null;
let loading = false;
let data = null;
let services = null;
let live = null;
let failure = null;
let onUpdated = null;
const state = { metric: "control", hours: 24 };

function chip(text, pressed, onClick) {
  const node = el("button", { className: "chip", text, attrs: { type: "button", "aria-pressed": String(pressed) } });
  node.addEventListener("click", onClick);
  return node;
}

function number(value) {
  return value === null ? "–" : value.toFixed(3);
}

function signed(value) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}`;
}

function verdict(zone, legacy, shadow) {
  if (!zone.legacy_available) return status("", "○", `No ${rangeController(data.zones, liveController(services)).label.toLowerCase()}`);
  if (legacy === null || shadow === null) return status("", "?", "No data");
  if (Math.abs(shadow - legacy) > DIVERGES_ABOVE) return status("warn", "⚠", "Diverges");
  return status("good", "✓", "Matches");
}

function rowFor(zone, legacyKey, shadowKey) {
  const legacy = zone.legacy_available ? zone.summary[legacyKey] : null;
  const shadow = zone.summary[shadowKey];
  const difference = legacy === null || shadow === null ? "–" : signed(shadow - legacy);
  return el("tr", {}, [
    el("td", { text: zone.name }),
    el("td", { className: "num", text: number(legacy) }),
    el("td", { className: "num", text: number(shadow) }),
    el("td", { className: "num", text: difference }),
    el("td", {}, [verdict(zone, legacy, shadow)]),
  ]);
}

function liveZone(zone) {
  return live === null ? null : live.find((item) => item.name === zone.name) || null;
}

function profileRow(zone, controller) {
  const entry = liveZone(zone);
  const shadow = entry && entry.shadow && entry.shadow.pid ? entry.shadow.pid : null;
  const side = livePid(controller, entry && entry.active);
  const known = shadow !== null && side !== null;
  const different = known && !samePid(shadow, side);
  let mark = status("", "?", "Unknown");
  if (known) mark = different ? status("warn", "⚠", "Different") : status("good", "✓", "Same");
  const row = el("tr", {}, [
    el("td", { text: zone.name }),
    el("td", { text: pidText(side) }),
    el("td", { text: pidText(shadow) }),
    el("td", {}, [mark]),
  ]);
  return { row, different };
}

function profilesCard(controller) {
  const head = el("tr", {}, ["Zone", `${controller.label} gains`, "Shadow gains", "Profiles"].map((text) => el("th", { text })));
  const entries = data.zones.map((zone) => profileRow(zone, controller));
  const notes = [];
  if (entries.some((entry) => entry.different)) {
    notes.push(el("div", { className: "small-label", text: "The shadow runs a different profile from the live controller, so a difference in the control values is expected." }));
  }
  const source = controller.v2 ? "the active service's published gains" : `the legacy defaults, ${pidText(LEGACY_PID)}`;
  notes.push(el("div", { className: "small-label", text: `The ${controller.label} gains come from ${source}. The shadow gains come from the shadow service now.` }));
  return el("div", { className: "card" }, [
    el("h2", { text: "PID profiles now" }),
    el("table", { className: "history-table" }, [el("thead", {}, [head]), el("tbody", {}, entries.map((entry) => entry.row))]),
    ...notes,
  ]);
}

function whenText(start) {
  return new Date(start * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function historyLine(zone) {
  const changes = zone.profiles;
  if (changes.length === 0) return el("li", { text: `${zone.name}: no windows in this range` });
  if (changes.length === 1) return el("li", { text: `${zone.name}: ${changes[0].pid === null ? "no profile recorded" : pidText(changes[0].pid)} for the whole range` });
  const parts = changes.map((change, index) => `${index === 0 ? "from the start" : `changed ${whenText(change.start)} to`}: ${change.pid === null ? "no profile recorded" : pidText(change.pid)}`);
  return el("li", { text: `${zone.name}, profile changed ${changes.length - 1} ${changes.length === 2 ? "time" : "times"}. ${parts.join(". ")}` });
}

function liveText(change) {
  if (change.controller === null) return "no record";
  return `${markerLabel(change.controller)}, ${change.pid === null ? "gains not published" : pidText(change.pid)}`;
}

function liveLine(zone) {
  const changes = zone.live;
  if (changes.length === 0) return el("li", { text: `${zone.name}: no windows in this range` });
  if (changes.length === 1) return el("li", { text: `${zone.name}: ${liveText(changes[0])} for the whole range` });
  const parts = changes.map((change, index) => `${index === 0 ? "from the start" : `from ${whenText(change.start)}`}: ${liveText(change)}`);
  return el("li", { text: `${zone.name}. ${parts.join(". ")}` });
}

function liveCard(controller) {
  const notes = [el("div", { className: "small-label", text: "The controller and gains are stored per ten-minute window. Windows from before 0.8.0 have no record." })];
  if (data.zones.some(liveChanged)) {
    notes.unshift(el("div", { className: "small-label warn-text", text: `The live controller or its gains changed inside this range. The means above mix windows that ran different gains${controller.mixed ? " and different controllers" : ""}. Pick a range after the change to compare like with like.` }));
  }
  return el("div", { className: "card" }, [
    el("h2", { text: "Live side in this range" }),
    el("ul", { className: "profile-history" }, data.zones.map(liveLine)),
    ...notes,
  ]);
}

function historyCard() {
  return el("div", { className: "card" }, [
    el("h2", { text: "Shadow profile in this range" }),
    el("ul", { className: "profile-history" }, data.zones.map(historyLine)),
    el("div", { className: "small-label", text: "The profile is stored per ten-minute window. Windows from before 0.7.0 have no profile recorded. Means across a change mix both profiles." }),
  ]);
}

function scaleTop(max) {
  const ticks = niceTicks(0, Math.max(max, MIN_SCALE), 4);
  const step = ticks.length > 1 ? ticks[1] - ticks[0] : MIN_SCALE;
  let top = ticks[ticks.length - 1];
  while (top < max) top += step;
  return Math.max(MIN_SCALE, +top.toFixed(6));
}

function render() {
  if (root === null) return;
  if (failure !== null) {
    root.replaceChildren(el("div", { className: "empty", text: failure }));
    return;
  }
  if (data === null) return;
  const controller = liveController(services);
  const range = rangeController(data.zones, controller);
  const side = range.label;
  const [, label, legacyKey, shadowKey] = METRICS.find(([key]) => key === state.metric);
  const windows = Math.max(0, ...data.zones.map((zone) => zone.summary.windows));
  const toolbar = el("div", { className: "toolbar" }, [
    el("span", { className: "label", text: "Metric" }),
    ...METRICS.map(([key, text]) => chip(text, key === state.metric, () => { state.metric = key; render(); })),
    el("span", { className: "sep" }),
    el("span", { className: "label", text: "Range" }),
    ...RANGES.map(([text, hours]) => chip(text, hours === state.hours, () => { state.hours = hours; load(); })),
    el("span", { className: "sep" }),
    el("span", { className: "sec", text: `${windows} ten-minute windows at most per zone` }),
  ]);
  const groups = data.zones.map((zone) => ({
    name: zone.name,
    note: zone.legacy_available ? "" : `no ${side.toLowerCase()}`,
    values: [zone.legacy_available ? zone.summary[legacyKey] : null, zone.summary[shadowKey]],
  }));
  const present = groups.flatMap((group) => group.values).filter((value) => value !== null);
  const yMax = scaleTop(Math.max(0, ...present));
  const box = el("div", { className: "chart" });
  const chartCard = el("div", { className: "card" }, [
    el("h2", { text: `${label} per zone, ${side} against shadow` }),
    legend([[BLUE, side], [ORANGE, "Shadow"]]),
    box,
  ]);
  const head = el("tr", {}, ["Zone", side, "Shadow", "Difference", "Verdict"].map((text, index) =>
    el("th", { className: index > 0 && index < 4 ? "num" : "", text })));
  const table = el("div", { className: "card" }, [
    el("table", { className: "history-table" }, [el("thead", {}, [head]),
      el("tbody", {}, data.zones.map((zone) => rowFor(zone, legacyKey, shadowKey)))]),
    el("div", { className: "small-label", text: `A zone diverges when the window means differ by more than ${DIVERGES_ABOVE}. A zone with no values from the live controller shows no live side. Gaps in history are not counted as zero.` }),
  ]);
  root.replaceChildren(toolbar, chartCard, table, profilesCard(controller), liveCard(range), historyCard());
  barChart(box, {
    label: `${label} per zone, ${side} against shadow`, groups, series: [{ name: side, color: BLUE }, { name: "Shadow", color: ORANGE }],
    yMax, tickFmt: (tick) => tick.toFixed(1), fmt: (value) => value.toFixed(3),
  });
}

async function load() {
  if (loading) return;
  loading = true;
  try {
    const [compared, serviceResult, liveResult] = await Promise.all([
      get("/api/compare", { hours: state.hours }),
      get("/api/services").catch(() => null),
      get("/api/live").catch(() => null),
    ]);
    data = compared;
    services = serviceResult;
    live = liveResult;
    failure = null;
    report("compare", null);
    onUpdated(clock(new Date()));
  } catch (error) {
    if (error.status === null) {
      report("compare", error);
    } else {
      report("compare", null);
      data = null;
      failure = error.message;
    }
  } finally {
    loading = false;
  }
  render();
}

export function startCompare(container, updated) {
  root = container;
  onUpdated = updated;
  load();
  timer = setInterval(() => {
    if (!document.hidden) load();
  }, REFRESH_MS);
}

export function stopCompare() {
  clearInterval(timer);
  timer = null;
  root = null;
}
