export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.title) node.title = options.title;
  for (const [name, value] of Object.entries(options.attrs || {})) node.setAttribute(name, value);
  for (const child of children) node.append(child);
  return node;
}

export function status(kind, glyph, label) {
  const mark = el("span", { className: "glyph", text: glyph, attrs: { "aria-hidden": "true" } });
  return el("span", { className: `status ${kind}` }, [mark, label]);
}

export function meter(value, extraClass = "") {
  const fill = document.createElement("i");
  fill.style.width = `${Math.max(0, Math.min(1, value)) * 100}%`;
  return el("div", { className: `meter ${extraClass}`.trim() }, [fill]);
}
