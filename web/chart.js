import { el, svg } from "./dom.js";
import { clock } from "./format.js";

const WIDTH = 600;
const LEFT = 40;
const RIGHT = 16;
const TOP = 12;
const BOTTOM = 28;
const RAW_INTERVAL = 10;
const GAP_FACTOR = 3;
const TICK_STEPS = [600, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400, 2 * 86400];
const MAX_TICKS = 7;

export function niceTicks(min, max, count) {
  const span = max - min;
  if (!(span > 0)) return [min];
  const raw = span / count;
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map((multiple) => multiple * power).find((candidate) => candidate >= raw);
  const ticks = [];
  for (let value = Math.ceil(min / step) * step; value <= max + 1e-9; value += step) ticks.push(+value.toFixed(6));
  return ticks;
}

export function segments(times, values, bucket) {
  const gap = GAP_FACTOR * Math.max(bucket, RAW_INTERVAL);
  const runs = [];
  let run = null;
  let previous = null;
  times.forEach((time, index) => {
    const value = values[index];
    if (value === null || value === undefined) {
      run = null;
      previous = null;
      return;
    }
    if (run === null || time - previous > gap) {
      run = [];
      runs.push(run);
    }
    run.push([time, value]);
    previous = time;
  });
  return runs;
}

export function nearest(times, target) {
  let low = 0;
  let high = times.length - 1;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (times[middle] < target) low = middle;
    else high = middle;
  }
  return Math.abs(times[low] - target) <= Math.abs(times[high] - target) ? low : high;
}

function timeScale(start, end) {
  const span = Math.max(1, end - start);
  return (time) => LEFT + ((time - start) / span) * (WIDTH - LEFT - RIGHT);
}

function tickLabel(seconds, span) {
  const date = new Date(seconds * 1000);
  if (span > 2 * 86400) return date.toLocaleDateString([], { weekday: "short" });
  return clock(date).slice(0, 5);
}

function dayTicks(start, end, days) {
  const first = new Date(start * 1000);
  const ticks = [];
  for (let day = new Date(first.getFullYear(), first.getMonth(), first.getDate() + 1);
    day.getTime() / 1000 <= end; day = new Date(day.getFullYear(), day.getMonth(), day.getDate() + days)) {
    ticks.push(day.getTime() / 1000);
  }
  return ticks;
}

function timeTicks(start, end) {
  const span = end - start;
  const step = TICK_STEPS.find((candidate) => span / candidate <= MAX_TICKS) || TICK_STEPS[TICK_STEPS.length - 1];
  if (step >= 86400) return dayTicks(start, end, step / 86400);
  const offset = new Date(start * 1000).getTimezoneOffset() * 60;
  const ticks = [];
  for (let time = Math.ceil((start - offset) / step) * step + offset; time <= end; time += step) ticks.push(time);
  return ticks;
}

function tooltipBox(box) {
  const tip = el("div", { className: "tip" });
  tip.hidden = true;
  box.append(tip);
  return tip;
}

function placeTip(box, tip, event) {
  const rect = box.getBoundingClientRect();
  let left = event.clientX - rect.left + 14;
  if (left + tip.offsetWidth > rect.width) left = event.clientX - rect.left - tip.offsetWidth - 14;
  tip.style.left = `${Math.max(0, left)}px`;
  tip.style.top = `${Math.max(0, event.clientY - rect.top - 20)}px`;
}

function tipRow(color, name, value) {
  const swatch = el("i", { className: "sw" });
  swatch.style.background = color;
  return el("div", { className: "r" }, [swatch, name, el("b", { text: value })]);
}

export function legend(items) {
  return el("div", { className: "legend" }, items.map(([color, name]) => {
    const swatch = el("i", { className: "sw" });
    swatch.style.background = color;
    return el("span", {}, [swatch, name]);
  }));
}

function pathOf(run, x, y, step) {
  return run.map(([time, value], index) => {
    if (index === 0) return `M${x(time)} ${y(value)}`;
    return step ? `H${x(time)} V${y(value)}` : `L${x(time)} ${y(value)}`;
  }).join(" ");
}

export function lineChart(box, options) {
  const { times, series, yMin, yMax, label, bucket, start, end } = options;
  const height = options.height || 220;
  const x = timeScale(start, end);
  const y = (value) => TOP + (1 - (value - yMin) / (yMax - yMin)) * (height - TOP - BOTTOM);
  const nodes = [];
  for (const tick of niceTicks(yMin, yMax, 5)) {
    nodes.push(svg("line", { class: "grid-line", x1: LEFT, x2: WIDTH - RIGHT, y1: y(tick), y2: y(tick) }));
    const text = svg("text", { x: LEFT - 8, y: y(tick) + 4, "text-anchor": "end" });
    text.textContent = options.tickFmt ? options.tickFmt(tick) : String(tick);
    nodes.push(text);
  }
  nodes.push(svg("line", { class: "axis-line", x1: LEFT, x2: WIDTH - RIGHT, y1: y(yMin), y2: y(yMin) }));
  for (const tick of timeTicks(start, end)) {
    const text = svg("text", { x: x(tick), y: height - 8, "text-anchor": "middle" });
    text.textContent = tickLabel(tick, end - start);
    nodes.push(text);
  }
  for (const entry of series) {
    for (const run of segments(times, entry.values, bucket)) {
      if (run.length === 1) {
        nodes.push(svg("circle", { cx: x(run[0][0]), cy: y(run[0][1]), r: 2.5, fill: entry.color }));
      } else {
        nodes.push(svg("path", { d: pathOf(run, x, y, entry.step), fill: "none", stroke: entry.color, "stroke-width": 2,
          "stroke-linejoin": "round", "stroke-linecap": "round" }));
      }
    }
  }
  const cross = svg("line", { class: "cross", y1: TOP, y2: height - BOTTOM, display: "none" });
  const dots = series.map((entry) => svg("circle", { r: 4, fill: entry.color, stroke: "var(--surface)",
    "stroke-width": 2, display: "none" }));
  const overlay = svg("rect", { x: LEFT, y: TOP, width: WIDTH - LEFT - RIGHT, height: height - TOP - BOTTOM, fill: "transparent" });
  const chart = svg("svg", { viewBox: `0 0 ${WIDTH} ${height}`, role: "img", "aria-label": label }, [...nodes, cross, ...dots, overlay]);
  box.replaceChildren(chart);
  const tip = tooltipBox(box);
  overlay.addEventListener("mouseleave", () => {
    tip.hidden = true;
    cross.setAttribute("display", "none");
    dots.forEach((dot) => dot.setAttribute("display", "none"));
  });
  overlay.addEventListener("mousemove", (event) => {
    const rect = chart.getBoundingClientRect();
    const time = start + ((event.clientX - rect.left) * (WIDTH / rect.width) - LEFT) / (WIDTH - LEFT - RIGHT) * (end - start);
    const index = nearest(times, time);
    cross.setAttribute("x1", x(times[index]));
    cross.setAttribute("x2", x(times[index]));
    cross.setAttribute("display", "block");
    series.forEach((entry, position) => {
      const value = entry.values[index];
      if (value === null || value === undefined) {
        dots[position].setAttribute("display", "none");
        return;
      }
      dots[position].setAttribute("cx", x(times[index]));
      dots[position].setAttribute("cy", y(value));
      dots[position].setAttribute("display", "block");
    });
    const rows = series.map((entry) => tipRow(entry.color, entry.name, entry.fmt(entry.values[index])));
    tip.replaceChildren(el("div", { className: "t", text: new Date(times[index] * 1000).toLocaleString() }), ...rows);
    tip.hidden = false;
    placeTip(box, tip, event);
  });
}

export function stateStrips(box, options) {
  const { times, rows, bucket, label, start, end } = options;
  const x = timeScale(start, end);
  const labelHeight = 14;
  const barHeight = 12;
  const gap = 8;
  const rowHeight = labelHeight + barHeight + gap;
  const span = Math.max(bucket, RAW_INTERVAL);
  const nodes = [];
  rows.forEach((row, index) => {
    const top = index * rowHeight + 2;
    const text = svg("text", { x: LEFT, y: top + 10 });
    text.textContent = row.name;
    nodes.push(text);
    nodes.push(svg("rect", { x: LEFT, y: top + labelHeight, width: WIDTH - LEFT - RIGHT, height: barHeight, rx: 2, fill: "var(--grid)" }));
    times.forEach((time, position) => {
      const value = row.values[position];
      if (value === null || value === undefined || value <= 0.005) return;
      const width = Math.max(0.6, (x(time + span) - x(time)) * Math.min(1, value));
      nodes.push(svg("rect", { x: x(time), y: top + labelHeight, width, height: barHeight, fill: row.color }));
    });
  });
  const height = rows.length * rowHeight + 4;
  const cross = svg("line", { class: "cross", y1: 0, y2: height, display: "none" });
  const overlay = svg("rect", { x: LEFT, y: 0, width: WIDTH - LEFT - RIGHT, height, fill: "transparent" });
  const chart = svg("svg", { viewBox: `0 0 ${WIDTH} ${height}`, role: "img", "aria-label": label }, [...nodes, cross, overlay]);
  box.replaceChildren(chart);
  const tip = tooltipBox(box);
  overlay.addEventListener("mouseleave", () => {
    tip.hidden = true;
    cross.setAttribute("display", "none");
  });
  overlay.addEventListener("mousemove", (event) => {
    const rect = chart.getBoundingClientRect();
    const time = start + ((event.clientX - rect.left) * (WIDTH / rect.width) - LEFT) / (WIDTH - LEFT - RIGHT) * (end - start);
    const index = nearest(times, time);
    cross.setAttribute("x1", x(times[index]));
    cross.setAttribute("x2", x(times[index]));
    cross.setAttribute("display", "block");
    const lines = rows.map((row) => {
      const value = row.values[index];
      return tipRow(row.color, row.name, value === null || value === undefined ? "no data" : `${Math.round(value * 100)}% on`);
    });
    tip.replaceChildren(el("div", { className: "t", text: new Date(times[index] * 1000).toLocaleString() }), ...lines);
    tip.hidden = false;
    placeTip(box, tip, event);
  });
}

export function sparkline(values, times, bucket, start, end, color) {
  const width = 160;
  const height = 36;
  const present = values.filter((value) => value !== null && value !== undefined);
  if (present.length === 0) return null;
  const low = Math.min(...present);
  const high = Math.max(...present);
  const x = (time) => 2 + ((time - start) / Math.max(1, end - start)) * (width - 8);
  const y = (value) => height - 6 - ((value - low) / (high - low || 1)) * (height - 12);
  const nodes = [];
  for (const run of segments(times, values, bucket)) {
    if (run.length > 1) nodes.push(svg("path", { d: pathOf(run, x, y, false), fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  }
  const last = present.length - 1;
  const lastTime = times[values.lastIndexOf(present[last])];
  nodes.push(svg("circle", { cx: x(lastTime), cy: y(present[last]), r: 4, fill: color, stroke: "var(--surface)", "stroke-width": 2 }));
  return svg("svg", { viewBox: `0 0 ${width} ${height}`, class: "spark", "aria-hidden": "true" }, nodes);
}
