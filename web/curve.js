export const JUMP_LIMIT = 1;
export const INTERPOLATION = "pchip";
const HOLD_LIMIT = 7200;
const SAME = 0.005;

export function knotsOf(run) {
  const knots = [];
  for (const [time, value] of run) {
    const last = knots[knots.length - 1];
    if (last === undefined || Math.abs(value - last[1]) >= SAME) knots.push([time, value]);
  }
  return knots;
}

export function readingKnots(readings, from, to) {
  const knots = [];
  let anchor = null;
  for (const reading of readings) {
    if (reading[0] <= from) anchor = reading;
    else if (reading[0] <= to) knots.push(reading);
  }
  if (anchor !== null && from - anchor[0] <= HOLD_LIMIT) knots.unshift(anchor);
  return knots;
}

export function pieces(knots, limit = JUMP_LIMIT) {
  const parts = [];
  let part = null;
  knots.forEach((knot, index) => {
    if (part === null || Math.abs(knot[1] - knots[index - 1][1]) > limit) {
      part = [];
      parts.push(part);
    }
    part.push(knot);
  });
  return parts;
}

function sign(value) {
  return value > 0 ? 1 : value < 0 ? -1 : 0;
}

function endSlope(h0, h1, d0, d1) {
  const slope = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1);
  if (sign(slope) !== sign(d0)) return 0;
  if (sign(d0) !== sign(d1) && Math.abs(slope) > 3 * Math.abs(d0)) return 3 * d0;
  return slope;
}

export function slopes(knots) {
  const count = knots.length;
  if (count < 2) return knots.map(() => 0);
  const h = [];
  const delta = [];
  for (let index = 0; index < count - 1; index += 1) {
    h.push(knots[index + 1][0] - knots[index][0]);
    delta.push((knots[index + 1][1] - knots[index][1]) / h[index]);
  }
  if (count === 2) return [delta[0], delta[0]];
  const result = new Array(count);
  for (let index = 1; index < count - 1; index += 1) {
    if (delta[index - 1] * delta[index] <= 0) {
      result[index] = 0;
    } else {
      const w1 = 2 * h[index] + h[index - 1];
      const w2 = h[index] + 2 * h[index - 1];
      result[index] = (w1 + w2) / (w1 / delta[index - 1] + w2 / delta[index]);
    }
  }
  result[0] = endSlope(h[0], h[1], delta[0], delta[1]);
  result[count - 1] = endSlope(h[count - 2], h[count - 3], delta[count - 2], delta[count - 3]);
  return result;
}

export function hermiteAt(knots, d, time) {
  let index = 0;
  while (index < knots.length - 2 && time > knots[index + 1][0]) index += 1;
  const [x0, y0] = knots[index];
  const [x1, y1] = knots[index + 1];
  const h = x1 - x0;
  const t = (time - x0) / h;
  const t2 = t * t;
  const t3 = t2 * t;
  return (2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * d[index]
    + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * d[index + 1];
}

export function beziers(knots, mode = INTERPOLATION) {
  const d = slopes(knots);
  const result = [];
  for (let index = 0; index < knots.length - 1; index += 1) {
    const [x0, y0] = knots[index];
    const [x1, y1] = knots[index + 1];
    const third = (x1 - x0) / 3;
    const secant = (y1 - y0) / (x1 - x0);
    const start = mode === "linear" ? secant : d[index];
    const finish = mode === "linear" ? secant : d[index + 1];
    result.push([x0 + third, y0 + start * third, x1 - third, y1 - finish * third, x1, y1]);
  }
  return result;
}

export function curveModel(runs, edge, reachesEnd, readings = [], slack = 0, mode = INTERPOLATION) {
  const model = { curves: [], flats: [], holds: [], knots: [] };
  runs.forEach((run, index) => {
    const runEnd = run[run.length - 1][0];
    const final = reachesEnd && index === runs.length - 1;
    const reported = readingKnots(readings, run[0][0], final ? Infinity : runEnd + slack);
    const knots = reported.length > 0 ? reported : knotsOf(run);
    const stop = final ? edge : runEnd;
    model.knots.push(...knots);
    if (knots.length < 2) {
      model.flats.push({ from: run[0][0], to: runEnd, value: knots[0][1] });
      if (final && edge > runEnd) model.holds.push({ from: runEnd, to: edge, value: knots[0][1] });
      return;
    }
    const parts = pieces(knots);
    parts.forEach((part, position) => {
      if (part.length > 1) model.curves.push({ knots: part, beziers: beziers(part, mode) });
      const last = part[part.length - 1];
      if (position === parts.length - 1 && stop > last[0]) model.holds.push({ from: last[0], to: stop, value: last[1] });
    });
  });
  model.knots.sort((a, b) => a[0] - b[0]);
  model.knots = model.knots.filter((knot, index) => index === 0 || knot[0] !== model.knots[index - 1][0]);
  return model;
}
