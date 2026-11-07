import { get } from "./api.js";
import { report } from "./alert.js";
import { barChart, legend, niceTicks } from "./chart.js";
import { el, status } from "./dom.js";
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
  if (!zone.legacy_available) return status("", "○", "No legacy");
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
    note: zone.legacy_available ? "" : "no legacy",
    values: [zone.legacy_available ? zone.summary[legacyKey] : null, zone.summary[shadowKey]],
  }));
  const present = groups.flatMap((group) => group.values).filter((value) => value !== null);
  const yMax = scaleTop(Math.max(0, ...present));
  const box = el("div", { className: "chart" });
  const chartCard = el("div", { className: "card" }, [
    el("h2", { text: `${label} per zone, legacy against shadow` }),
    legend([[BLUE, "Legacy"], [ORANGE, "Shadow"]]),
    box,
  ]);
  const head = el("tr", {}, ["Zone", "Legacy", "Shadow", "Difference", "Verdict"].map((text, index) =>
    el("th", { className: index > 0 && index < 4 ? "num" : "", text })));
  const table = el("div", { className: "card" }, [
    el("table", { className: "history-table" }, [el("thead", {}, [head]),
      el("tbody", {}, data.zones.map((zone) => rowFor(zone, legacyKey, shadowKey)))]),
    el("div", { className: "small-label", text: `A zone diverges when the window means differ by more than ${DIVERGES_ABOVE}. A zone with no legacy values shows no legacy side. Gaps in history are not counted as zero.` }),
  ]);
  root.replaceChildren(toolbar, chartCard, table);
  barChart(box, {
    label: `${label} per zone, legacy against shadow`, groups, series: [{ name: "Legacy", color: BLUE }, { name: "Shadow", color: ORANGE }],
    yMax, tickFmt: (tick) => tick.toFixed(1), fmt: (value) => value.toFixed(3),
  });
}

async function load() {
  if (loading) return;
  loading = true;
  try {
    data = await get("/api/compare", { hours: state.hours });
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
