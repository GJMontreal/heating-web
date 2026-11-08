import { el, status } from "./dom.js";
import { ageText } from "./format.js";

const MISMATCH_AFTER_S = 15;
const mismatchSince = new Map();

function seconds(text) {
  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? parsed / 1000 : null;
}

function power(value) {
  if (value === 1) return "On";
  if (value === 0) return "Off";
  return null;
}

export function hasConfirmation(zone) {
  return zone.system === "electric" && zone.active !== null && typeof zone.active === "object" && "confirmed" in zone.active;
}

function nowOf(zone, io) {
  return seconds(io === null ? zone.active.time : io.time) || seconds(zone.active.time);
}

function verdict(zone, commanded, confirmed, now, silent) {
  if (silent) {
    mismatchSince.delete(zone.name);
    return status("crit", "✖", "no report from the relay");
  }
  if (confirmed === null) {
    mismatchSince.delete(zone.name);
    return status("", "?", "no report");
  }
  if (commanded === null || commanded === confirmed) {
    mismatchSince.delete(zone.name);
    return status("good", "✓", "Confirmed");
  }
  if (!mismatchSince.has(zone.name)) mismatchSince.set(zone.name, now);
  const lasted = now === null ? 0 : now - mismatchSince.get(zone.name);
  if (lasted > MISMATCH_AFTER_S) return status("crit", "✖", "Relay differs from the command");
  return status("warn", "⚠", "Waiting for the relay");
}

export function confirmationRows(zone, io) {
  const active = zone.active;
  const now = nowOf(zone, io);
  const commanded = typeof active.state === "number" ? active.state : null;
  const confirmed = typeof active.confirmed === "number" ? active.confirmed : null;
  const reported = seconds(active.confirmed_time);
  const age = reported === null || now === null ? null : Math.max(0, now - reported);
  const text = [
    `Commanded ${power(commanded) || "no command yet"}`,
    `reported ${power(confirmed) || "no report"}`,
  ];
  if (age !== null) text.push(ageText(age));
  return [
    el("dt", { text: "Relay" }),
    el("dd", {}, [el("span", { text: text.join(", ") }), verdict(zone, commanded, confirmed, now, active.confirmed_silent === true)]),
  ];
}
