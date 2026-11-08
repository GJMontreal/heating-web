import { get } from "./api.js";
import { report } from "./alert.js";
import { legend, lineChart, sparkline, stateStrips } from "./chart.js";
import { liveController } from "./controller.js";
import { el } from "./dom.js";
import { clock, temperature } from "./format.js";

const REFRESH_MS = 60000;
const RANGES = [["6 hours", 6], ["24 hours", 24], ["7 days", 168]];
const POINTS = 360;
const TABLE_ROWS = 24;
const BLUE = "var(--s1)";
const ORANGE = "var(--s2)";
const GRAY = "var(--ink-3)";
const INPUT = "var(--ink-2)";

let root = null;
let timer = null;
let loading = false;
let data = null;
let services = null;
let failure = null;
const state = { zone: null, hours: 24, table: false };

function chip(text, pressed, onClick) {
  const node = el("button", { className: "chip", text, attrs: { type: "button", "aria-pressed": String(pressed) } });
  node.addEventListener("click", onClick);
  return node;
}

function lastValue(values) {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index] !== null) return values[index];
  }
  return null;
}

function side() {
  return liveController(services).label;
}

function control(value) {
  return value === null || value === undefined ? "no value" : value.toFixed(2);
}

function tempText(value) {
  return value === null || value === undefined ? "not set" : `${temperature(value)} °C`;
}

function sparkCard(zone) {
  const latest = lastValue(zone.temp);
  const picture = sparkline(zone.temp, zone.t, data.bucket_seconds, data.start, data.end, BLUE)
    || el("div", { className: "muted spark-empty", text: "No readings in range" });
  const head = el("div", { className: "row" }, [
    el("b", { text: zone.name }),
    el("span", { className: "spacer" }),
    el("span", { className: "sec", text: latest === null ? "–" : `${temperature(latest)} °C` }),
  ]);
  const card = el("button", { className: "spark-card", attrs: { type: "button", "aria-pressed": String(zone.name === state.zone) } }, [head, picture]);
  card.addEventListener("click", () => {
    state.zone = zone.name;
    render();
  });
  return card;
}

function boilerOn(times) {
  const byTime = new Map(data.boiler.t.map((time, index) => [time, data.boiler.on[index]]));
  return times.map((time) => (byTime.has(time) ? byTime.get(time) : null));
}

function everyNth(zone) {
  const step = Math.max(1, Math.round(zone.t.length / TABLE_ROWS));
  return zone.t.map((time, index) => index).filter((index) => index % step === 0);
}

function tableView(zone) {
  const head = el("tr", {}, ["Time", "Temperature °C", "Target °C", `${side()} control`, "Shadow control"].map((text, index) =>
    el("th", { className: index === 0 ? "" : "num", text })));
  const rows = everyNth(zone).map((index) => el("tr", {}, [
    el("td", { text: new Date(zone.t[index] * 1000).toLocaleString() }),
    el("td", { className: "num", text: temperature(zone.temp[index]) }),
    el("td", { className: "num", text: temperature(zone.target[index]) }),
    el("td", { className: "num", text: zone.legacy_available ? control(zone.ctl[index]) : "–" }),
    el("td", { className: "num", text: control(zone.sh_ctl[index]) }),
  ]));
  return el("table", { className: "history-table" }, [el("thead", {}, [head]), el("tbody", {}, rows)]);
}

function temperatureCard(zone) {
  const box = el("div", { className: "chart" });
  const card = el("div", { className: "card" }, [
    el("h2", { text: `${zone.name} temperature` }),
    legend([[BLUE, "Temperature"], [GRAY, "Target"]]),
    box,
  ]);
  return { card, draw: () => {
    const present = zone.temp.concat(zone.target).filter((value) => value !== null);
    if (present.length === 0) {
      box.replaceChildren(el("div", { className: "empty", text: "No temperature readings in this range." }));
      return;
    }
    lineChart(box, {
      label: `${zone.name} temperature and target`, times: zone.t, bucket: data.bucket_seconds, start: data.start, end: data.end,
      yMin: Math.floor(Math.min(...present) - 0.5), yMax: Math.ceil(Math.max(...present) + 0.5),
      series: [
        { name: "Temperature", color: BLUE, values: zone.temp, fmt: tempText },
        { name: "Target", color: GRAY, values: zone.target, step: true, fmt: tempText },
      ],
    });
  } };
}

function heatingCard(zone) {
  const chart = el("div", { className: "chart" });
  const strips = el("div", { className: "chart strips" });
  const notes = zone.legacy_available ? [] : [el("div", { className: "muted note", text: `No ${side().toLowerCase()} values for this zone. Only the shadow side is shown.` })];
  const card = el("div", { className: "card" }, [
    el("h2", { text: `${zone.name} heating` }),
    legend(zone.legacy_available ? [[BLUE, side()], [ORANGE, "Shadow"]] : [[ORANGE, "Shadow"]]),
    ...notes, chart, strips,
  ]);
  return { card, draw: () => {
    const series = [{ name: "Shadow control value", color: ORANGE, values: zone.sh_ctl, fmt: control }];
    if (zone.legacy_available) series.unshift({ name: `${side()} control value`, color: BLUE, values: zone.ctl, fmt: control });
    lineChart(chart, {
      label: `${zone.name} control value`, times: zone.t, bucket: data.bucket_seconds, start: data.start, end: data.end,
      yMin: 0, yMax: 1, tickFmt: (tick) => tick.toFixed(1), series,
    });
    const rows = [
      { name: "Valve output", color: BLUE, values: zone.out, verb: "open" },
      { name: "End switch", color: INPUT, values: zone.sw, verb: "open" },
      { name: "Boiler", color: BLUE, values: zone.system === "hydronic" ? boilerOn(zone.t) : [] },
      { name: `${side()} heating state`, color: BLUE, values: zone.legacy_available ? zone.hc : [] },
      { name: "Shadow heating state", color: BLUE, values: zone.sh_state },
    ].filter((row) => row.values.some((value) => value !== null));
    if (rows.length === 0) {
      strips.replaceChildren();
      return;
    }
    stateStrips(strips, { label: `${zone.name} valve, end switch, boiler and heating state over time`, times: zone.t,
      bucket: data.bucket_seconds, start: data.start, end: data.end, rows });
  } };
}

function render() {
  if (root === null) return;
  if (failure !== null) {
    root.replaceChildren(el("div", { className: "empty", text: failure }));
    return;
  }
  if (data === null) return;
  if (state.zone === null || !data.zones.some((zone) => zone.name === state.zone)) state.zone = data.zones.length ? data.zones[0].name : null;
  const zone = data.zones.find((entry) => entry.name === state.zone);
  const toolbar = el("div", { className: "toolbar" }, [
    el("span", { className: "label", text: "Range" }),
    ...RANGES.map(([text, hours]) => chip(text, hours === state.hours, () => { state.hours = hours; load(); })),
    el("span", { className: "sep" }),
    chip("Table view", state.table, () => { state.table = !state.table; render(); }),
  ]);
  const sparks = el("div", { className: "spark-grid" }, data.zones.map(sparkCard));
  const nodes = [toolbar, sparks];
  if (zone !== undefined) {
    if (state.table) {
      nodes.push(el("div", { className: "card" }, [el("h2", { text: `${zone.name} samples` }), tableView(zone)]));
    } else {
      const temperaturePart = temperatureCard(zone);
      const heatingPart = heatingCard(zone);
      nodes.push(el("div", { className: "grid wide" }, [temperaturePart.card, heatingPart.card]));
      root.replaceChildren(...nodes);
      temperaturePart.draw();
      heatingPart.draw();
      return;
    }
  }
  root.replaceChildren(...nodes);
}

async function load() {
  if (loading) return;
  loading = true;
  try {
    const [history, serviceResult] = await Promise.all([
      get("/api/history", { hours: state.hours, points: POINTS }),
      get("/api/services").catch(() => null),
    ]);
    data = history;
    services = serviceResult;
    failure = null;
    report("history", null);
    onUpdated(clock(new Date()));
  } catch (error) {
    if (error.status === null) {
      report("history", error);
    } else {
      report("history", null);
      data = null;
      failure = error.message;
    }
  } finally {
    loading = false;
  }
  render();
}

let onUpdated = null;

export function startTrends(container, updated) {
  root = container;
  onUpdated = updated;
  load();
  timer = setInterval(() => {
    if (!document.hidden) load();
  }, REFRESH_MS);
}

export function stopTrends() {
  clearInterval(timer);
  timer = null;
  root = null;
}
