import { el, status } from "./dom.js";

const STUCK_AFTER_SECONDS = 360;
const STUCK_AFTER_MINUTES = STUCK_AFTER_SECONDS / 60;
const HYDRONIC = "hydronic";
const VALVE_STATES = {
  open: ["good", "●", "Open"],
  opening: ["", "◐", "Opening"],
  closing: ["", "◑", "Closing"],
  closed: ["", "○", "Closed"],
};
const TRANSITIONS = ["opening", "closing"];

export function seconds(from, to) {
  const start = Date.parse(from);
  const end = Date.parse(to);
  return Number.isNaN(start) || Number.isNaN(end) ? null : Math.max(0, (end - start) / 1000);
}

export function duration(value) {
  if (value < 90) return `${Math.round(value)} s`;
  if (value < 5400) return `${Math.round(value / 60)} min`;
  return `${Math.round(value / 3600)} h`;
}

export function valveState(output, end) {
  if (output.active === null || end === undefined || end.high === null) return null;
  if (output.active) return end.high ? "open" : "opening";
  return end.high ? "closing" : "closed";
}

export function changedAgo(now, ...sinces) {
  const times = sinces.filter((since) => since !== null && Number.isFinite(Date.parse(since)));
  if (times.length === 0) return null;
  const latest = times.reduce((a, b) => (Date.parse(a) >= Date.parse(b) ? a : b));
  return seconds(latest, now);
}

function levelText(entry) {
  return entry.exported ? String(entry.level) : "–";
}

function heldFor(now, entry) {
  const elapsed = entry.since === null ? null : seconds(entry.since, now);
  return elapsed === null ? "" : ` for ${duration(elapsed)}`;
}

function hover(entry, text, now) {
  return `level ${levelText(entry)}, ${text}${heldFor(now, entry)}`;
}

function signalCells(name, pin) {
  return [el("td", { text: name }), el("td", { className: "pin", text: pin })];
}

function notReadable() {
  return el("td", { className: "muted", text: "Not readable", title: "pin not exported or not readable" });
}

function stateCell(kind, glyph, label, title) {
  return el("td", { title }, [status(kind, glyph, label)]);
}

function valveStateCell(state, elapsed, title) {
  if (state === null) return stateCell("", "?", "Unknown", title);
  const [kind, glyph, label] = VALVE_STATES[state];
  if (TRANSITIONS.includes(state) && elapsed !== null && elapsed > STUCK_AFTER_SECONDS) {
    return stateCell("warn", "⚠", `${label} for ${duration(elapsed)}, over ${STUCK_AFTER_MINUTES} min`, title);
  }
  const text = TRANSITIONS.includes(state) && elapsed !== null ? `${label} for ${duration(elapsed)}` : label;
  return stateCell(kind, glyph, text, title);
}

function boilerRow(boiler) {
  const state = boiler.on === null ? notReadable()
    : stateCell(boiler.on ? "good" : "", boiler.on ? "●" : "○", boiler.on ? "On" : "Off", `level ${levelText(boiler)}`);
  return el("tr", {}, [...signalCells("Boiler", boiler.pin), state]);
}

function valveRow(zone, output, end, suffix, now) {
  const driven = output.active === null ? "not readable" : output.active ? "driven open" : "driven closed";
  const title = hover(output, driven, now);
  const state = valveState(output, end);
  const elapsed = state === null || end === undefined ? null : changedAgo(now, output.since, end.since);
  const cell = output.active === null ? notReadable() : valveStateCell(state, elapsed, title);
  return el("tr", {}, [...signalCells(`${zone.name} valve${suffix}`, output.pin), cell]);
}

function endSwitchRow(zone, end, suffix, now) {
  let cell = notReadable();
  if (end.high !== null) {
    const title = hover(end, end.high ? "high, valve open" : "low, valve not open", now);
    cell = end.high ? stateCell("good", "●", "Open", title) : stateCell("", "○", "Closed", title);
  }
  return el("tr", {}, [...signalCells(`${zone.name} end switch${suffix}`, end.pin), cell]);
}

function zoneRows(zone, now) {
  const rows = [];
  const many = zone.outputs.length > 1;
  zone.outputs.forEach((output, index) => {
    const suffix = many ? ` ${index + 1}` : "";
    const end = zone.end_switches.find((entry) => entry.pin === output.end_switch);
    rows.push(valveRow(zone, output, end, suffix, now));
    if (end !== undefined) rows.push(endSwitchRow(zone, end, suffix, now));
  });
  return rows;
}

export function ioCard(io) {
  const rows = [];
  if (io.boiler !== null) rows.push(boilerRow(io.boiler));
  for (const zone of io.zones) {
    if (zone.system === HYDRONIC && zone.outputs !== null && zone.end_switches !== null) rows.push(...zoneRows(zone, io.time));
  }
  const head = el("tr", {}, ["Signal", "Pin", "State"].map((text) => el("th", { text })));
  return el("div", { className: "card io" }, [
    el("h3", { text: "Hydronic I/O" }),
    el("div", { className: "muted note", text: "Physical pin levels read from the BeagleBone. The pin, not the control value, says what the valve and the boiler are doing. Hover a state for the pin level." }),
    el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]),
  ]);
}

export function relayRow(io, name) {
  const zone = io === null ? undefined : io.zones.find((entry) => entry.name === name);
  if (zone === undefined || zone.outputs === null || !zone.outputs.some((output) => output.type === "mqtt")) return [];
  return [el("dt", { text: "Relay" }), el("dd", {}, [status("warn", "?", "Relay state not confirmed")])];
}
