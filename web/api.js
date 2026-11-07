const TIMEOUT_MS = 8000;

export class ApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.status = status;
  }
}

export async function get(path, params = {}) {
  const url = new URL(path, location.origin);
  for (const [name, value] of Object.entries(params)) url.searchParams.set(name, value);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response;
  try {
    response = await fetch(url, { method: "GET", cache: "no-store", signal: controller.signal });
  } catch (error) {
    throw new ApiError(error.name === "AbortError" ? `${path} timed out` : `${path} did not answer`);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    let detail = "";
    try {
      detail = (await response.json()).detail || "";
    } catch (error) {
      detail = "";
    }
    throw new ApiError(detail || `${path} answered ${response.status}`, response.status);
  }
  return response.json();
}
