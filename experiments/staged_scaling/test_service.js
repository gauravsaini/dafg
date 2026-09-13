#!/usr/bin/env node
/**
 * Phase 1 baseline integration test for staged_scaling Node.js service.
 * Designed for DAFG gate-driven verification. Each gate invokes this
 * with a filter prefix and asserts a marker in the output.
 *
 * Usage: node test_service.js [FILTER_PREFIX]
 */

const http = require("http");
const { createServer } = require("./src/server");

async function httpRequest(method, path, body, host) {
  const [hostname, port] = host.split(":");
  const opts = { hostname, port, path, method, headers: {} };

  if (body !== undefined) {
    const data = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
    opts.headers["Content-Length"] = Buffer.byteLength(data);
  }

  return new Promise((resolve, reject) => {
    const req = http.request(opts, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString();
        let parsed;
        try { parsed = JSON.parse(raw); } catch { parsed = raw; }
        resolve({ status: res.statusCode, headers: res.headers, body: parsed });
      });
    });
    req.on("error", reject);
    if (body !== undefined) req.write(JSON.stringify(body));
    req.end();
  });
}

async function run() {
  const { server, register } = createServer();

  const host = await new Promise((resolve) => {
    server.listen(0, () => {
      resolve(`127.0.0.1:${server.address().port}`);
    });
  });

  let allPassed = true;
  let output = [];
  const filterPrefix = process.argv[2] || "";

  const request = (method, path, body) => httpRequest(method, path, body, host);

  // Register Phase 2 domain routes
  const { registerRoutes } = require("./src/routes/index");
  register(registerRoutes);

  async function check(name, fn) {
    if (filterPrefix && !name.startsWith(filterPrefix)) return;
    try {
      await fn();
      output.push(`${name}_PASS`);
    } catch (err) {
      allPassed = false;
      output.push(`${name}_FAIL: ${err.message}`);
    }
  }

  // ── G1: Server starts and health endpoint ──────────────────────────
  await check("HEALTH", async () => {
    const res = await request("GET", "/health");
    if (res.status !== 200) throw new Error(`Expected 200, got ${res.status}`);
    if (res.body.status !== "ok") throw new Error(`Expected status "ok", got ${JSON.stringify(res.body.status)}`);
    if (typeof res.body.timestamp !== "string") throw new Error(`Missing "timestamp" in health response`);
    if (typeof res.body.uptime !== "number") throw new Error(`Missing "uptime" in health response`);
    if (res.body.uptime < 0) throw new Error(`Invalid uptime: ${res.body.uptime}`);
  });

  // ── G2: 404 for unknown routes ─────────────────────────────────────
  await check("NOTFOUND", async () => {
    const res = await request("GET", "/unknown-route");
    if (res.status !== 404) throw new Error(`Expected 404, got ${res.status}`);
    if (typeof res.body.error !== "string") throw new Error(`Missing "error" in 404 response`);
  });

  // ── G3: DataStore basic CRUD ───────────────────────────────────────
  await check("DATASTORE", async () => {
    const { DataStore } = require("./src/data/store");
    const store = new DataStore();

    // Initially empty
    if (store.size !== 0) throw new Error(`Expected size 0, got ${store.size}`);

    // Create
    const item1 = store.create({ name: "alpha", value: 1 });
    if (!item1.id) throw new Error(`Missing id in created item`);
    if (item1.name !== "alpha") throw new Error(`Expected name "alpha", got ${item1.name}`);

    const item2 = store.create({ name: "beta", value: 2 });
    if (store.size !== 2) throw new Error(`Expected size 2, got ${store.size}`);

    // Get
    const got = store.get(item1.id);
    if (!got || got.name !== "alpha") throw new Error(`Expected "alpha", got ${JSON.stringify(got)}`);

    // List
    const all = store.list();
    if (all.length !== 2) throw new Error(`Expected 2 items, got ${all.length}`);

    // Update
    const updated = store.update(item1.id, { value: 10 });
    if (!updated || updated.value !== 10) throw new Error(`Update failed`);

    // Delete
    const deleted = store.delete(item1.id);
    if (!deleted) throw new Error(`Delete returned false`);
    if (store.size !== 1) throw new Error(`Expected size 1 after delete, got ${store.size}`);

    // Get nonexistent
    const missing = store.get("nonexistent");
    if (missing !== null) throw new Error(`Expected null for nonexistent get`);

    // Clear
    store.clear();
    if (store.size !== 0) throw new Error(`Expected size 0 after clear, got ${store.size}`);
  });

  // ── G4: Repository base class ──────────────────────────────────────
  await check("REPOSITORY", async () => {
    const { Repository } = require("./src/data/repository");
    const repo = new Repository();

    const item = repo.create({ name: "test" });
    if (!item.id) throw new Error(`Missing id in repository create`);

    const list = repo.list();
    if (list.length !== 1) throw new Error(`Expected 1 item, got ${list.length}`);

    const got = repo.get(item.id);
    if (!got || got.name !== "test") throw new Error(`Get returned unexpected: ${JSON.stringify(got)}`);

    const updated = repo.update(item.id, { name: "updated" });
    if (!updated || updated.name !== "updated") throw new Error(`Update failed: ${JSON.stringify(updated)}`);

    const deleted = repo.delete(item.id);
    if (!deleted) throw new Error(`Delete returned false`);

    repo.clear();
    if (repo.size !== 0) throw new Error(`Expected size 0`);
  });

  // ── G5: Server 500 on internal error ───────────────────────────────
  await check("ERROR", async () => {
    // Register a route that throws
    const { Route } = require("./src/server");
    register((router, Route) => {
      Route.GET(router, "/_crash", () => { throw new Error("simulated crash"); });
    });
    const res = await request("GET", "/_crash");
    if (res.status !== 500) throw new Error(`Expected 500, got ${res.status}`);
  });

  // ── G6: Module imports cleanly ─────────────────────────────────────
  await check("IMPORT", async () => {
    // Already imported above — just verify
    const srv = require("./src/server");
    if (typeof srv.createServer !== "function") throw new Error(`createServer not exported`);
    if (typeof srv.sendJSON !== "function") throw new Error(`sendJSON not exported`);
    if (typeof srv.Route !== "object") throw new Error(`Route not exported`);
    const dstore = require("./src/data/store");
    if (typeof dstore.DataStore !== "function") throw new Error(`DataStore not exported`);
    const repo = require("./src/data/repository");
    if (typeof repo.Repository !== "function") throw new Error(`Repository not exported`);
  });

  // ── G7: Users API — CRUD operations ────────────────────────────────
  await check("USERS", async () => {
    // Create user
    const created = await request("POST", "/api/users", { name: "Alice", email: "alice@test.com" });
    if (created.status !== 201) throw new Error(`POST /api/users: Expected 201, got ${created.status}`);
    if (!created.body.user || !created.body.user.id) throw new Error(`Missing user id in create response`);
    const userId = created.body.user.id;
    if (created.body.user.name !== "Alice") throw new Error(`Expected name "Alice", got ${created.body.user.name}`);

    // List users
    const listRes = await request("GET", "/api/users");
    if (listRes.status !== 200) throw new Error(`GET /api/users: Expected 200, got ${listRes.status}`);
    if (!Array.isArray(listRes.body.users)) throw new Error(`Expected users array, got ${JSON.stringify(listRes.body)}`);
    if (listRes.body.users.length < 1) throw new Error(`Expected at least 1 user, got ${listRes.body.users.length}`);

    // Get user by ID
    const getRes = await request("GET", `/api/users/${userId}`);
    if (getRes.status !== 200) throw new Error(`GET /api/users/:id: Expected 200, got ${getRes.status}`);
    if (getRes.body.user.id !== userId) throw new Error(`Expected id ${userId}, got ${getRes.body.user.id}`);

    // Delete user
    const delRes = await request("DELETE", `/api/users/${userId}`);
    if (delRes.status !== 200) throw new Error(`DELETE /api/users/:id: Expected 200, got ${delRes.status}`);
    if (delRes.body.deleted !== true) throw new Error(`Expected deleted: true`);

    // Confirm deleted
    const gone = await request("GET", `/api/users/${userId}`);
    if (gone.status !== 404) throw new Error(`Expected 404 after delete, got ${gone.status}`);

    // 400 on missing name
    const bad = await request("POST", "/api/users", { email: "noid@test.com" });
    if (bad.status !== 400) throw new Error(`Expected 400 for missing name, got ${bad.status}`);
  });

  // ── G8: Products API — catalog operations ──────────────────────────
  await check("PRODUCTS", async () => {
    // Create product
    const created = await request("POST", "/api/products", { name: "Widget", price: 9.99 });
    if (created.status !== 201) throw new Error(`POST /api/products: Expected 201, got ${created.status}`);
    if (!created.body.product || !created.body.product.id) throw new Error(`Missing product id`);
    const prodId = created.body.product.id;
    if (created.body.product.name !== "Widget") throw new Error(`Expected name "Widget", got ${created.body.product.name}`);
    if (created.body.product.price !== 9.99) throw new Error(`Expected price 9.99, got ${created.body.product.price}`);

    // List products
    const listRes = await request("GET", "/api/products");
    if (listRes.status !== 200) throw new Error(`GET /api/products: Expected 200, got ${listRes.status}`);
    if (!Array.isArray(listRes.body.products)) throw new Error(`Expected products array`);
    if (listRes.body.products.length < 1) throw new Error(`Expected at least 1 product`);

    // Get product by ID
    const getRes = await request("GET", `/api/products/${prodId}`);
    if (getRes.status !== 200) throw new Error(`GET /api/products/:id: Expected 200, got ${getRes.status}`);
    if (getRes.body.product.id !== prodId) throw new Error(`Wrong id`);
  });

  // ── G9: Orders API — order operations ─────────────────────────────
  await check("ORDERS", async () => {
    // Create an order
    const created = await request("POST", "/api/orders", { userId: "u1", items: [{ sku: "w1", qty: 2 }] });
    if (created.status !== 201) throw new Error(`POST /api/orders: Expected 201, got ${created.status}`);
    if (!created.body.order || !created.body.order.id) throw new Error(`Missing order id`);
    const orderId = created.body.order.id;
    if (created.body.order.userId !== "u1") throw new Error(`Expected userId "u1", got ${created.body.order.userId}`);

    // List orders
    const listRes = await request("GET", "/api/orders");
    if (listRes.status !== 200) throw new Error(`GET /api/orders: Expected 200, got ${listRes.status}`);
    if (!Array.isArray(listRes.body.orders)) throw new Error(`Expected orders array`);
    if (listRes.body.orders.length < 1) throw new Error(`Expected at least 1 order`);

    // Get order by ID
    const getRes = await request("GET", `/api/orders/${orderId}`);
    if (getRes.status !== 200) throw new Error(`GET /api/orders/:id: Expected 200, got ${getRes.status}`);
    if (getRes.body.order.id !== orderId) throw new Error(`Wrong id`);
  });

  // ── G10: Metrics API — request count, uptime, memory ─────────────
  await check("METRICS", async () => {
    const res = await request("GET", "/api/metrics");
    if (res.status !== 200) throw new Error(`GET /api/metrics: Expected 200, got ${res.status}`);
    if (typeof res.body.requestCount !== "number") throw new Error(`Missing requestCount, got ${JSON.stringify(res.body)}`);
    if (typeof res.body.uptime !== "number") throw new Error(`Missing uptime`);
    if (res.body.uptime < 0) throw new Error(`Invalid uptime: ${res.body.uptime}`);
    if (!res.body.memoryUsage || typeof res.body.memoryUsage.heapUsed !== "number") throw new Error(`Missing memoryUsage.heapUsed`);
    if (typeof res.body.timestamp !== "string") throw new Error(`Missing timestamp`);
  });

  server.close();
  console.log(output.join("\n"));
  process.exit(allPassed ? 0 : 1);
}

run().catch((err) => {
  console.error(err.message);
  process.exit(1);
});