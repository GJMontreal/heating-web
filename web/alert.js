import { el, status } from "./dom.js";

const failures = new Map();
const box = document.getElementById("alert");

function render() {
  if (failures.size === 0) {
    box.hidden = true;
    box.replaceChildren();
    return;
  }
  const reasons = Array.from(failures.values()).join("; ");
  const message = el("span", { text: `Cannot reach the API (${reasons}). The page shows the last data it received.` });
  box.replaceChildren(status("crit", "⚠", message));
  box.hidden = false;
}

export function report(source, error) {
  if (error) failures.set(source, error.message);
  else failures.delete(source);
  render();
}
