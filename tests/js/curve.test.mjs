import assert from "node:assert/strict";
import test from "node:test";

import { INTERPOLATION, JUMP_LIMIT, beziers, curveModel, hermiteAt, knotsOf, pieces, readingKnots, slopes } from "../../web/curve.js";

function generator(seed) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

function randomKnots(random, count) {
  const knots = [];
  let time = 0;
  let value = 20;
  for (let index = 0; index < count; index += 1) {
    time += 60 + random() * 7200;
    value += (random() - 0.5) * (random() < 0.3 ? 0.04 : 0.8);
    knots.push([time, value]);
  }
  return knots;
}

test("a repeated value is not a knot and a change is", () => {
  const run = [[0, 19], [10, 19], [20, 19.5], [30, 19.5], [40, 19], [50, 19.001]];

  assert.deepEqual(knotsOf(run), [[0, 19], [20, 19.5], [40, 19]]);
});

test("the curve passes through every knot", () => {
  const knots = randomKnots(generator(7), 40);
  const d = slopes(knots);

  for (const [time, value] of knots) assert.ok(Math.abs(hermiteAt(knots, d, time) - value) < 1e-9);
});

test("the curve never leaves the range of the two knots around it", () => {
  for (let seed = 1; seed <= 50; seed += 1) {
    const knots = randomKnots(generator(seed), 25);
    const d = slopes(knots);
    for (let index = 0; index < knots.length - 1; index += 1) {
      const low = Math.min(knots[index][1], knots[index + 1][1]);
      const high = Math.max(knots[index][1], knots[index + 1][1]);
      for (let step = 0; step <= 100; step += 1) {
        const time = knots[index][0] + ((knots[index + 1][0] - knots[index][0]) * step) / 100;
        const value = hermiteAt(knots, d, time);
        assert.ok(value >= low - 1e-9 && value <= high + 1e-9, `seed ${seed} segment ${index} step ${step}: ${value}`);
      }
    }
  }
});

test("a step in the data does not ring on either side", () => {
  const knots = [[0, 19], [3600, 19], [7200, 21], [10800, 21], [14400, 21.04]];
  const d = slopes(knots);

  for (let time = 0; time <= 14400; time += 60) {
    const value = hermiteAt(knots, d, time);
    assert.ok(value >= 19 - 1e-9 && value <= 21.04 + 1e-9);
  }
  assert.equal(d[1], 0);
  assert.equal(d[3], 0);
});

test("a local extreme has a flat slope", () => {
  const d = slopes([[0, 19], [100, 20], [200, 19.5]]);

  assert.equal(d[1], 0);
});

test("a monotone run has a slope that never changes sign", () => {
  const d = slopes([[0, 19], [300, 19.1], [4000, 19.5], [4300, 19.6], [9000, 20.4]]);

  assert.ok(d.every((slope) => slope >= 0));
});

test("the bezier segments start and end on the knots and keep their control points inside the range", () => {
  const knots = [[0, 19], [3600, 19.3], [9000, 19.4], [12000, 19.9]];

  const segments = beziers(knots);

  assert.equal(segments.length, 3);
  segments.forEach((segment, index) => {
    assert.deepEqual([segment[4], segment[5]], knots[index + 1]);
    const low = Math.min(knots[index][1], knots[index + 1][1]);
    const high = Math.max(knots[index][1], knots[index + 1][1]);
    for (const y of [segment[1], segment[3]]) assert.ok(y >= low - 1e-9 && y <= high + 1e-9);
  });
});

test("a jump over the limit splits the knots and a smaller step does not", () => {
  const stale = [[0, 12], [100, 12.1], [200, 23.7], [300, 23.8]];
  const normal = [[0, 20], [100, 20.5], [200, 21.4]];

  assert.deepEqual(pieces(stale).map((part) => part.length), [2, 2]);
  assert.equal(pieces(normal).length, 1);
});

test("a jump of exactly the limit is not a break", () => {
  assert.equal(pieces([[0, 20], [100, 20 + JUMP_LIMIT]]).length, 1);
});

test("the last value is held flat to the edge and never extrapolated", () => {
  const run = [[0, 19], [100, 19], [200, 19.2], [300, 19.2], [400, 19.4], [500, 19.4]];

  const model = curveModel([run], 600, true);

  assert.deepEqual(model.holds, [{ from: 400, to: 600, value: 19.4 }]);
  assert.equal(model.curves.length, 1);
  assert.deepEqual(model.curves[0].knots.map((knot) => knot[0]), [0, 200, 400]);
});

test("a run that ends before the edge is not held to the edge", () => {
  const run = [[0, 19], [100, 19.2], [200, 19.4]];

  const model = curveModel([run], 600, false);

  assert.deepEqual(model.holds, []);
});

test("a null gap breaks the curve into separate runs", () => {
  const first = [[0, 19], [100, 19.2], [200, 19.4]];
  const second = [[1000, 19.5], [1100, 19.6], [1200, 19.8]];

  const model = curveModel([first, second], 1300, true);

  assert.equal(model.curves.length, 2);
  assert.ok(model.curves[0].knots.every((knot) => knot[0] <= 200));
  assert.ok(model.curves[1].knots.every((knot) => knot[0] >= 1000));
});

test("a stale to fresh jump is not ramped across", () => {
  const run = [[0, 12], [100, 12], [200, 23.7], [300, 23.7], [400, 23.8]];

  const model = curveModel([run], 500, true);

  assert.equal(model.curves.length, 1);
  assert.deepEqual(model.curves[0].knots.map((knot) => knot[1]), [23.7, 23.8]);
  assert.deepEqual(model.knots.map((knot) => knot[1]), [12, 23.7, 23.8]);
  assert.deepEqual(model.holds, [{ from: 400, to: 500, value: 23.8 }]);
});

test("a range with no change draws a flat line with one marker and a hold to the edge", () => {
  const run = [[0, 19], [10, 19], [20, 19]];

  const model = curveModel([run], 100, true);

  assert.equal(model.curves.length, 0);
  assert.deepEqual(model.flats, [{ from: 0, to: 20, value: 19 }]);
  assert.deepEqual(model.knots, [[0, 19]]);
  assert.deepEqual(model.holds, [{ from: 20, to: 100, value: 19 }]);
});

test("a range with one change has two knots and a curve between them", () => {
  const run = [[0, 19], [10, 19], [20, 19.1], [30, 19.1]];

  const model = curveModel([run], 40, true);

  assert.equal(model.curves.length, 1);
  assert.deepEqual(model.knots, [[0, 19], [20, 19.1]]);
});

test("no data gives an empty model", () => {
  assert.deepEqual(curveModel([], 100, false), { curves: [], flats: [], holds: [], knots: [] });
});

test("pchip is the default interpolation", () => {
  assert.equal(INTERPOLATION, "pchip");
});

test("the linear mode draws straight segments through the knots", () => {
  const knots = [[0, 19], [3600, 19.3], [9000, 19.4]];

  const segments = beziers(knots, "linear");

  segments.forEach((segment, index) => {
    const [x0, y0] = knots[index];
    const [x1, y1] = knots[index + 1];
    const slope = (y1 - y0) / (x1 - x0);
    assert.ok(Math.abs(segment[1] - (y0 + slope * (segment[0] - x0))) < 1e-9);
    assert.ok(Math.abs(segment[3] - (y1 - slope * (x1 - segment[2]))) < 1e-9);
    assert.deepEqual([segment[4], segment[5]], [x1, y1]);
  });
});

test("the default mode matches pchip and differs from linear on uneven data", () => {
  const knots = [[0, 19], [3600, 19], [7200, 20], [7300, 20.1]];

  assert.deepEqual(beziers(knots), beziers(knots, "pchip"));
  assert.notDeepEqual(beziers(knots), beziers(knots, "linear"));
});

test("reading knots hold the last reading before the run as the anchor", () => {
  const readings = [[-3000, 18.9], [-100, 19], [500, 19.2], [900, 19.2], [2000, 19.5]];

  assert.deepEqual(readingKnots(readings, 0, 1000), [[-100, 19], [500, 19.2], [900, 19.2]]);
});

test("a reading older than the hold limit is not an anchor", () => {
  assert.deepEqual(readingKnots([[-8000, 18.9], [500, 19]], 0, 1000), [[500, 19]]);
});

test("a reading with an unchanged value is a knot and the curve holds flat through it", () => {
  const run = [[0, 19], [100, 19], [200, 19], [300, 19]];
  const readings = [[-50, 19], [100, 19], [250, 19]];

  const model = curveModel([run], 400, true, readings, 10);

  assert.deepEqual(model.knots, [[-50, 19], [100, 19], [250, 19]]);
  assert.equal(model.curves.length, 1);
  for (const segment of model.curves[0].beziers) assert.ok(segment.filter((_, index) => index % 2 === 1).every((y) => y === 19));
  assert.deepEqual(model.holds, [{ from: 250, to: 400, value: 19 }]);
});

test("a bucket that averages two readings adds no knot", () => {
  const run = [[0, 23.12], [22, 23.12], [44, 22.87], [66, 22.61], [88, 22.61]];
  const readings = [[-600, 23.12], [50, 22.61]];

  const model = curveModel([run], 100, true, readings, 22);

  assert.deepEqual(model.knots, [[-600, 23.12], [50, 22.61]]);
  assert.ok(!model.knots.some((knot) => Math.abs(knot[1] - 22.87) < 1e-9));
});

test("a run with no readings falls back to the knots found from value changes", () => {
  const run = [[0, 19], [10, 19], [20, 19.2]];

  const model = curveModel([run], 40, true, [], 10);

  assert.deepEqual(model.knots, [[0, 19], [20, 19.2]]);
});

test("readings only belong to the run they fall in", () => {
  const first = [[0, 19], [100, 19]];
  const second = [[5000, 20], [5100, 20]];
  const readings = [[-10, 19], [4990, 20], [5050, 20.1]];

  const model = curveModel([first, second], 5200, true, readings, 10);

  assert.equal(model.curves.length, 1);
  assert.deepEqual(model.curves[0].knots, [[4990, 20], [5050, 20.1]]);
  assert.deepEqual(model.knots.map((knot) => knot[0]), [-10, 4990, 5050]);
});

test("a jump between two readings still breaks the curve", () => {
  const run = [[0, 12], [100, 23.7]];
  const readings = [[-10, 12], [90, 23.7], [95, 23.8]];

  const model = curveModel([run], 200, true, readings, 10);

  assert.deepEqual(model.curves.map((curve) => curve.knots.map((knot) => knot[1])), [[23.7, 23.8]]);
});

test("the knots of the model are sorted and unique", () => {
  const first = [[0, 19], [100, 19]];
  const second = [[300, 19], [400, 19]];
  const readings = [[90, 19], [350, 19]];

  const model = curveModel([first, second], 500, true, readings, 10);

  const times = model.knots.map((knot) => knot[0]);
  assert.deepEqual(times, [...new Set(times)].sort((a, b) => a - b));
});
