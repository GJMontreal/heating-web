export const LEGACY_PID = { kp: 1, ki: 0.01, kd: 0.5, integral_cap: 1 };

const PID_LABELS = [["kp", "Kp"], ["ki", "Ki"], ["kd", "Kd"], ["integral_cap", "cap"]];

function isActive(services, name) {
  return services.some((unit) => unit.name === name && unit.state === "active");
}

export function liveController(services) {
  if (services === null) return { label: "Live", v2: false, known: false };
  if (isActive(services, "boiler_relay_v2")) return { label: "Live (v2)", v2: true, known: true };
  if (isActive(services, "boiler_relay")) return { label: "Legacy", v2: false, known: true };
  return { label: "Live", v2: false, known: false };
}

export function pidText(pid) {
  if (pid === null || pid === undefined) return "not published";
  return PID_LABELS.map(([key, text]) => `${text} ${pid[key]}`).join(", ");
}

export function samePid(a, b) {
  return PID_LABELS.every(([key]) => a[key] === b[key]);
}

export function livePid(controller, active) {
  if (!controller.v2) return LEGACY_PID;
  return active && active.pid ? active.pid : null;
}

const MARKER_LABELS = { legacy: "Legacy", v2: "Live (v2)" };

export function markerLabel(marker) {
  return MARKER_LABELS[marker] || "no record";
}

function recorded(zone) {
  return zone.live.filter((change) => change.controller !== null);
}

export function liveChanged(zone) {
  const seen = new Set(recorded(zone).map((change) => JSON.stringify([change.controller, change.pid])));
  return seen.size > 1;
}

export function rangeController(zones, today) {
  const markers = new Set(zones.flatMap((zone) => recorded(zone).map((change) => change.controller)));
  if (markers.size === 0) return { label: today.label, mixed: false };
  if (markers.size === 1) return { label: markerLabel([...markers][0]), mixed: false };
  return { label: "Live", mixed: true };
}
