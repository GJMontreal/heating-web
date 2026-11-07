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

function pinLabel(name, pin) {
  return el("div", {}, [name, el("div", { className: "pin", text: pin })]);
}

function levelText(entry) {
  return entry.exported ? String(entry.level) : "–";
}

function heldFor(now, entry) {
  const elapsed = entry.since === null ? null : seconds(entry.since, now);
  return elapsed === null ? "" : `for ${duration(elapsed)}`;
}

function reading(label, entry, now) {
  const parts = [el("span", { text: label })];
  const held = heldFor(now, entry);
  if (held) parts.push(el("span", { className: "muted", text: ` ${held}` }));
  return el("td", {}, parts);
}

function valveCell(state, elapsed) {
  if (state === null) return el("td", {}, [status("", "?", "Unknown")]);
  const [kind, glyph, label] = VALVE_STATES[state];
  if (TRANSITIONS.includes(state) && elapsed !== null && elapsed > STUCK_AFTER_SECONDS) {
    return el("td", {}, [status("warn", "⚠", `${label} for ${duration(elapsed)}, over ${STUCK_AFTER_MINUTES} min`)]);
  }
  const text = TRANSITIONS.includes(state) && elapsed !== null ? `${label} for ${duration(elapsed)}` : label;
  return el("td", {}, [status(kind, glyph, text)]);
}

function boilerRow(boiler) {
  const state = boiler.on === null ? el("td", { className: "muted", text: "Not readable" })
    : el("td", {}, [boiler.on ? status("good", "●", "On") : status("", "○", "Off")]);
  return el("tr", {}, [el("td", {}, [pinLabel("Boiler", boiler.pin)]), el("td", { text: levelText(boiler) }), state, el("td")]);
}

function zoneRows(zone, now) {
  const rows = [];
  const many = zone.outputs.length > 1;
  zone.outputs.forEach((output, index) => {
    const suffix = many ? ` ${index + 1}` : "";
    const end = zone.end_switches.find((entry) => entry.pin === output.end_switch);
    const commanded = output.active === null ? el("td", { className: "muted", text: "Not readable" })
      : reading(output.active ? "Driven open" : "Driven closed", output, now);
    const state = valveState(output, end);
    const elapsed = state === null || end === undefined ? null : changedAgo(now, output.since, end.since);
    rows.push(el("tr", {}, [
      el("td", {}, [pinLabel(`${zone.name} valve${suffix}`, output.pin)]),
      el("td", { text: levelText(output) }),
      commanded,
      valveCell(state, elapsed),
    ]));
    if (end !== undefined) {
      const text = end.high === null ? null : end.high ? "High, valve open" : "Low, valve not open";
      rows.push(el("tr", {}, [
        el("td", {}, [pinLabel(`${zone.name} end switch${suffix}`, end.pin)]),
        el("td", { text: levelText(end) }),
        text === null ? el("td", { className: "muted", text: "Not readable" }) : reading(text, end, now),
        el("td"),
      ]));
    }
  });
  return rows;
}

export function ioCard(io) {
  const rows = [];
  if (io.boiler !== null) rows.push(boilerRow(io.boiler));
  for (const zone of io.zones) {
    if (zone.system === HYDRONIC && zone.outputs !== null && zone.end_switches !== null) rows.push(...zoneRows(zone, io.time));
  }
  const head = el("tr", {}, ["Signal", "Level", "Reading", "Valve"].map((text) => el("th", { text })));
  return el("div", { className: "card io" }, [
    el("h3", { text: "Hydronic I/O" }),
    el("div", { className: "muted note", text: "Physical pin levels read from the BeagleBone. The pin, not the control value, says what the valve and the boiler are doing." }),
    el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]),
  ]);
}

export function relayRow(io, name) {
  const zone = io === null ? undefined : io.zones.find((entry) => entry.name === name);
  if (zone === undefined || zone.outputs === null || !zone.outputs.some((output) => output.type === "mqtt")) return [];
  return [el("dt", { text: "Relay" }), el("dd", {}, [status("warn", "?", "Relay state not confirmed")])];
}
