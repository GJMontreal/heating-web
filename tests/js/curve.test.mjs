import assert from "node:assert/strict";
import test from "node:test";

import { JUMP_LIMIT, beziers, curveModel, hermiteAt, knotsOf, pieces, slopes } from "../../web/curve.js";

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
