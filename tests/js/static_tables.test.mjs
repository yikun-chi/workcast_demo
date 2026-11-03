import {test} from "node:test";
import assert from "node:assert/strict";
import {tableReader} from "../../ui/data/query.js";

function fixture() {
  const chunks = [[["p1", 3, false], ["p2", null, true]], [["p3", 1, false], ["p4", 3, true]], [["p5", -2, false]]];
  const loaded = [];
  const query = tableReader({name: "people", columns: ["id", "score", "flag"], total: 5, chunk_size: 2, chunks: ["a", "b", "c"]},
    async i => { loaded.push(i); return chunks[i]; });
  return {query, loaded};
}

test("pagination reads only required chunks, including boundary and final pages", async () => {
  const {query, loaded} = fixture();
  assert.equal((await query({limit: 1})).rows[0].id, "p1");
  assert.deepEqual(loaded, [0]);
  assert.deepEqual((await query({offset: 1, limit: 2})).rows.map(r => r.id), ["p2", "p3"]);
  assert.deepEqual(loaded, [0, 1]);
  assert.deepEqual((await query({offset: 4, limit: 50})).rows, [{id: "p5", score: -2, flag: false}]);
  assert.deepEqual((await query({offset: 20})).rows, []);
});

test("search includes records beyond the initial chunk and reports the filtered count", async () => {
  const {query, loaded} = fixture();
  const result = await query({q: "P5"});
  assert.equal(result.total, 1);
  assert.equal(result.rows[0].id, "p5");
  assert.deepEqual(loaded, [0, 1, 2]);
  assert.equal((await query({q: "false"})).total, 3);
  assert.equal((await query({q: "no match"})).total, 0);
});

test("global numeric sort keeps nulls last and ties stable in both directions", async () => {
  const {query} = fixture();
  assert.deepEqual((await query({sort: "score"})).rows.map(r => r.id), ["p5", "p3", "p1", "p4", "p2"]);
  assert.deepEqual((await query({sort: "score", desc: 1})).rows.map(r => r.id), ["p1", "p4", "p3", "p5", "p2"]);
  const page = await query({q: "true", sort: "score", offset: 1, limit: 1});
  assert.equal(page.total, 2);
  assert.equal(page.rows[0].id, "p2");
});

test("empty tables retain schema and failed chunks can be retried", async () => {
  const empty = tableReader({name: "empty", columns: ["id"], total: 0, chunk_size: 2, chunks: []}, () => assert.fail());
  assert.deepEqual((await empty({q: "x"})).rows, []);
  assert.deepEqual((await empty()).columns, ["id"]);
  let attempt = 0;
  const retry = tableReader({name: "retry", columns: ["id"], total: 1, chunk_size: 2, chunks: ["a"]}, async () => {
    if (++attempt === 1) throw new Error("unavailable");
    return [["restored"]];
  });
  await assert.rejects(retry(), /unavailable/);
  assert.equal((await retry()).rows[0].id, "restored");
});
