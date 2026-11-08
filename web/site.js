import { get } from "./api.js";

const REFRESH_MS = 60000;
const heading = document.getElementById("site");

async function load() {
  try {
    const { site_name: name } = await get("/api/site");
    if (typeof name === "string" && name !== "") {
      document.title = name;
      heading.textContent = name;
    }
  } catch (error) {
    return;
  }
}

export function startSite() {
  load();
  setInterval(load, REFRESH_MS);
}
