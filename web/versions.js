import { get } from "./api.js";
import { report } from "./alert.js";
import { el } from "./dom.js";

const REFRESH_MS = 60000;
const DIRTY = "-dirty";
const UNKNOWN = "unknown";
const container = document.getElementById("versions");

function version(value) {
  return value === UNKNOWN ? el("b", { className: "muted", text: value }) : el("b", { text: value });
}

function commit(value) {
  const node = el("i", { className: "commit" });
  if (value === UNKNOWN) {
    node.className = "commit muted";
    node.textContent = value;
  } else if (value.endsWith(DIRTY)) {
    node.append(value.slice(0, -DIRTY.length), el("span", { className: "muted", text: DIRTY }));
  } else {
    node.textContent = value;
  }
  return node;
}

function started(time) {
  const date = new Date(time);
  return Number.isNaN(date.getTime()) ? `started ${time}` : `started ${date.toLocaleString()}`;
}

function entry(item) {
  return el("span", { className: "entry", title: started(item.time) },
    [item.service, version(item.version), commit(item.commit)]);
}

async function load() {
  try {
    const items = await get("/api/versions");
    container.replaceChildren(...items.map(entry));
    report("versions", null);
  } catch (error) {
    report("versions", error);
  }
}

export function startVersions() {
  load();
  setInterval(load, REFRESH_MS);
}
