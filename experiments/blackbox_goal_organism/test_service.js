#!/usr/bin/env node
/**
 * Blackbox integration test for the Node.js REST API.
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
        let json;
        try { json = JSON.parse(raw); } catch { json = null; }
        resolve({ status: res.statusCode, headers: res.headers, body: json, raw });
      });
    });
    req.on("error", reject);
    if (body !== undefined) req.write(JSON.stringify(body));
    req.end();
  });
}

async function run() {
  const { server, register, context } = createServer();
  const { registerRoutes } = require("./src/routes/index");
  register(registerRoutes);

  const host = await new Promise((resolve) => {
    server.listen(0, () => resolve(`127.0.0.1:${server.address().port}`));
  });

  let allPassed = true;
  let output = [];
  const filterPrefix = process.argv[2] || "";

  const request = (method, path, body) => httpRequest(method, path, body, host);

  async function check(name, fn) {
    if (!name.startsWith(filterPrefix)) return;
    try {
      await fn();
      output.push(`PASSED:${name}`);
    } catch (err) {
      allPassed = false;
      output.push(`FAILED:${name} — ${err.message}`);
    }
  }

  // ── G1: Health endpoint ────────────────────────────────
  await check("HEALTH", async () => {
    const res = await request("GET", "/health");
    if (res.status !== 200) throw new Error(`Expected 200, got ${res.status}`);
    if (res.body.status !== "ok") throw new Error(`Expected status ok, got ${JSON.stringify(res.body)}`);
    if (!res.body.timestamp) throw new Error("Missing timestamp");
  });

  // ── G2: Users CRUD ─────────────────────────────────────
  await check("USERS", async () => {
    // Create user
    const created = await request("POST", "/api/users", { name: "Test User", email: "test@example.com", role: "admin" });
    if (created.status !== 201) throw new Error(`POST /api/users expected 201, got ${created.status}`);
    if (!created.body.user || !created.body.user.id) throw new Error("Created user missing id");
    const userId = created.body.user.id;

    // List users
    const listed = await request("GET", "/api/users");
    if (listed.status !== 200) throw new Error(`GET /api/users expected 200, got ${listed.status}`);
    if (!Array.isArray(listed.body.users)) throw new Error("Expected users array");

    // Get by ID
    const got = await request("GET", `/api/users/${userId}`);
    if (got.status !== 200) throw new Error(`GET /api/users/:id expected 200, got ${got.status}`);
    if (got.body.user.email !== "test@example.com") throw new Error("User email mismatch");

    // Delete
    const deleted = await request("DELETE", `/api/users/${userId}`);
    if (deleted.status !== 200) throw new Error(`DELETE /api/users/:id expected 200, got ${deleted.status}`);

    // Confirm gone
    const gone = await request("GET", `/api/users/${userId}`);
    if (gone.status !== 404) throw new Error(`GET deleted user expected 404, got ${gone.status}`);

    // 404 on unknown user
    const notFound = await request("GET", "/api/users/nonexistent");
    if (notFound.status !== 404) throw new Error(`Expected 404, got ${notFound.status}`);
  });

  // ── G3: Products catalog ──────────────────────────────
  await check("PRODUCTS", async () => {
    // Create product
    const created = await request("POST", "/api/products", { name: "Widget", price: 9.99, category: "Gadgets" });
    if (created.status !== 201) throw new Error(`POST /api/products expected 201, got ${created.status}`);
    if (!created.body.product || !created.body.product.id) throw new Error("Created product missing id");
    const productId = created.body.product.id;

    // List products
    const listed = await request("GET", "/api/products");
    if (listed.status !== 200) throw new Error(`GET /api/products expected 200, got ${listed.status}`);
    if (!Array.isArray(listed.body.products)) throw new Error("Expected products array");

    // Get by ID
    const got = await request("GET", `/api/products/${productId}`);
    if (got.status !== 200) throw new Error(`GET /api/products/:id expected 200, got ${got.status}`);
    if (got.body.product.price !== 9.99) throw new Error("Product price mismatch");

    // 404 on unknown product
    const notFound = await request("GET", "/api/products/nonexistent");
    if (notFound.status !== 404) throw new Error(`Expected 404, got ${notFound.status}`);

    // Validation: missing name
    const noName = await request("POST", "/api/products", { price: 5 });
    if (noName.status !== 400) throw new Error(`Expected 400, got ${noName.status}`);

    // Validation: missing price
    const noPrice = await request("POST", "/api/products", { name: "X" });
    if (noPrice.status !== 400) throw new Error(`Expected 400, got ${noPrice.status}`);
  });

  // ── G4: Orders processing ─────────────────────────────
  await check("ORDERS", async () => {
    // Need a user and product first
    const user = await request("POST", "/api/users", { name: "Order User", email: "order@test.com" });
    if (user.status !== 201) throw new Error(`Setup: create user failed, got ${user.status}`);
    const userId = user.body.user.id;

    const prod = await request("POST", "/api/products", { name: "OrderItem", price: 19.99 });
    if (prod.status !== 201) throw new Error(`Setup: create product failed, got ${prod.status}`);
    const productId = prod.body.product.id;

    // Create order
    const created = await request("POST", "/api/orders", { userId, items: [{ productId, quantity: 2 }] });
    if (created.status !== 201) throw new Error(`POST /api/orders expected 201, got ${created.status}`);
    if (!created.body.order || !created.body.order.id) throw new Error("Created order missing id");
    if (created.body.order.total !== 39.98) throw new Error(`Expected total 39.98, got ${created.body.order.total}`);

    // List orders
    const listed = await request("GET", "/api/orders");
    if (listed.status !== 200) throw new Error(`GET /api/orders expected 200, got ${listed.status}`);

    // Get by ID
    const got = await request("GET", `/api/orders/${created.body.order.id}`);
    if (got.status !== 200) throw new Error(`GET /api/orders/:id expected 200, got ${got.status}`);

    // 404 on unknown order
    const notFound = await request("GET", "/api/orders/nonexistent");
    if (notFound.status !== 404) throw new Error(`Expected 404, got ${notFound.status}`);

    // Validation: missing userId
    const noUser = await request("POST", "/api/orders", { items: [{ productId, quantity: 1 }] });
    if (noUser.status !== 400) throw new Error(`Expected 400, got ${noUser.status}`);

    // Validation: missing items
    const noItems = await request("POST", "/api/orders", { userId });
    if (noItems.status !== 400) throw new Error(`Expected 400, got ${noItems.status}`);
  });

  // ── G5: Metrics ──────────────────────────────────────
  await check("METRICS", async () => {
    const res = await request("GET", "/api/metrics");
    if (res.status !== 200) throw new Error(`Expected 200, got ${res.status}`);
    if (typeof res.body.requestCount !== "number") throw new Error("Missing requestCount");
    if (typeof res.body.uptime !== "number") throw new Error("Missing uptime");
    if (!res.body.memoryUsage || typeof res.body.memoryUsage.heapUsed !== "number") throw new Error("Missing memoryUsage");
    if (!res.body.timestamp) throw new Error("Missing timestamp");
  });

  // ── G6: Error handling ──────────────────────────────
  await check("ERRORS", async () => {
    // 404 for unknown routes
    const unknown = await request("GET", "/api/unknown");
    if (unknown.status !== 404) throw new Error(`Expected 404, got ${unknown.status}`);

    // 400 for bad POST body on users
    const badUser = await request("POST", "/api/users", {});
    if (badUser.status !== 400) throw new Error(`Expected 400, got ${badUser.status}`);
  });

  server.close();
  console.log(output.join("\n"));
  process.exit(allPassed ? 0 : 1);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});