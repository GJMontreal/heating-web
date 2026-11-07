import { startLive, stopLive } from "./live.js";

const VIEWS = {
  live: { root: document.getElementById("view-live"), start: startLive, stop: stopLive },
};
const DEFAULT_VIEW = "live";
const updated = document.getElementById("updated");
const theme = document.getElementById("theme");
let current = null;

function showUpdated(time) {
  updated.textContent = `updated ${time}`;
}

function show(name) {
  if (current === name) return;
  if (current !== null) VIEWS[current].stop();
  current = name;
  updated.textContent = "";
  for (const [key, view] of Object.entries(VIEWS)) {
    view.root.hidden = key !== name;
    view.root.replaceChildren();
  }
  for (const link of document.querySelectorAll("nav a")) {
    if (link.dataset.view === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  VIEWS[name].start(VIEWS[name].root, showUpdated);
}

function route() {
  const name = location.hash.slice(1);
  show(Object.keys(VIEWS).includes(name) ? name : DEFAULT_VIEW);
}

function setTheme(dark) {
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  theme.textContent = dark ? "Light" : "Dark";
}

theme.addEventListener("click", () => setTheme(document.documentElement.dataset.theme !== "dark"));
setTheme(matchMedia("(prefers-color-scheme: dark)").matches);
window.addEventListener("hashchange", route);
route();
