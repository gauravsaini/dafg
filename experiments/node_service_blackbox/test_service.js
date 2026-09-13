#!/usr/bin/env node
/**
 * Blackbox integration test for Node.js REST service.
 * Designed to be called from DAFG gates. Each gate extracts its marker.
 * Uses port 0 (OS-assigned) to avoid port conflicts between concurrent gate runs.
 * Exits 0 only if all tests pass.
 */

const http = require("http");
const app = require("./src/server");

function httpRequest(method, path, body, host) {
  const [hostname, port] = host.split(":");
  return new Promise((resolve, reject) => {
    const opts = { hostname, port: parseInt(port, 10), path, method,
      headers: { "Content-Type": "application/json" } };
    const req = http.request(opts, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    });
    req.on("error", reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

async function run() {
  const server = app.listen(0); // OS-assigned port - no conflicts
  const host = await new Promise((r) => server.on("listening", () =>
    r(`127.0.0.1:${server.address().port}`)
  ));

  let allPassed = true;
  let output = [];

  // Filter: if argv[2] is provided, only run checks whose name starts with that prefix
  const filterPrefix = process.argv[2] || "";
  const request = (method, path, body) => httpRequest(method, path, body, host);

  async function check(name, fn) {
    if (filterPrefix && !name.startsWith(filterPrefix)) return;
    try {
      await fn();
      output.push(`${name}_PASS`);
    } catch (e) {
      output.push(`${name}_FAIL: ${e.message}`);
      allPassed = false;
    }
  }

  // --- G1: Health check ---
  await check("HEALTH", async () => {
    const res = await request("GET", "/health");
    if (res.status !== 200) throw new Error(`Expected 200 got ${res.status}`);
    if (res.body.status !== "ok") throw new Error(`Expected status ok got ${res.body.status}`);
    if (!res.body.timestamp) throw new Error("Missing timestamp");
  });

  // --- G2: Users resource ---
  await check("USERS", async () => {
    const list = await request("GET", "/api/users");
    if (list.status !== 200) throw new Error(`GET /api/users expected 200 got ${list.status}`);
    if (!Array.isArray(list.body.users)) throw new Error("Expected users array");
    if (list.body.users.length < 1) throw new Error("Expected at least 1 user");

    const one = await request("GET", "/api/users/1");
    if (one.status !== 200) throw new Error(`GET /api/users/1 expected 200 got ${one.status}`);
    if (one.body.user.id !== 1) throw new Error("Expected user id 1");

    const created = await request("POST", "/api/users", { name: "Test User", email: "test@example.com" });
    if (created.status !== 201) throw new Error(`POST /api/users expected 201 got ${created.status}`);
    if (created.body.user.name !== "Test User") throw new Error("Expected Test User");

    const missing = await request("GET", "/api/users/99999");
    if (missing.status !== 404) throw new Error(`Expected 404 got ${missing.status}`);
  });

  // --- G3: Products catalog ---
  await check("PRODUCTS", async () => {
    const list = await request("GET", "/api/products");
    if (list.status !== 200) throw new Error(`GET /api/products expected 200 got ${list.status}`);
    if (!Array.isArray(list.body.products)) throw new Error("Expected products array");

    const one = await request("GET", "/api/products/1");
    if (one.status !== 200) throw new Error(`GET /api/products/1 expected 200 got ${one.status}`);
    if (one.body.product.id !== 1) throw new Error("Expected product id 1");

    const created = await request("POST", "/api/products", { name: "Test Widget", price: 9.99, category: "Test" });
    if (created.status !== 201) throw new Error(`POST /api/products expected 201 got ${created.status}`);
    if (created.body.product.name !== "Test Widget") throw new Error("Expected Test Widget");

    const missing = await request("GET", "/api/products/99999");
    if (missing.status !== 404) throw new Error(`Expected 404 got ${missing.status}`);
  });

  // --- G4: Orders processing ---
  await check("ORDERS", async () => {
    const list = await request("GET", "/api/orders");
    if (list.status !== 200) throw new Error(`GET /api/orders expected 200 got ${list.status}`);
    if (!Array.isArray(list.body.orders)) throw new Error("Expected orders array");

    const created = await request("POST", "/api/orders", { userId: 1, items: [{ productId: 1, quantity: 2 }] });
    if (created.status !== 201) throw new Error(`POST /api/orders expected 201 got ${created.status}`);
    if (created.body.order.status !== "pending") throw new Error("Expected order status pending");
    if (created.body.order.total !== 59.98) throw new Error(`Expected total 59.98 got ${created.body.order.total}`);

    const one = await request("GET", "/api/orders/1");
    if (one.status !== 200) throw new Error(`GET /api/orders/1 expected 200 got ${one.status}`);
    if (one.body.order.id !== 1) throw new Error("Expected order id 1");

    const missing = await request("GET", "/api/orders/99999");
    if (missing.status !== 404) throw new Error(`Expected 404 got ${missing.status}`);
  });

  // --- G5: Error handling ---
  await check("ERRORS", async () => {
    const badUser = await request("POST", "/api/users", {});
    if (badUser.status !== 400) throw new Error(`Expected 400 got ${badUser.status}`);

    const badOrder = await request("POST", "/api/orders", {});
    if (badOrder.status !== 400) throw new Error(`Expected 400 got ${badOrder.status}`);

    const oos = await request("POST", "/api/orders", { userId: 1, items: [{ productId: 4 }] });
    if (oos.status !== 400) throw new Error(`Expected 400 got ${oos.status}`);

    const noUser = await request("POST", "/api/orders", { userId: 999, items: [{ productId: 1 }] });
    if (noUser.status !== 404) throw new Error(`Expected 404 got ${noUser.status}`);

    const noProd = await request("POST", "/api/orders", { userId: 1, items: [{ productId: 999 }] });
    if (noProd.status !== 404) throw new Error(`Expected 404 got ${noProd.status}`);
  });

  // --- G6: End-to-end happy path ---
  await check("E2E", async () => {
    const user = await request("POST", "/api/users", { name: "E2E User", email: "e2e@test.com" });
    if (user.status !== 201) throw new Error("E2E: Failed to create user");
    const userId = user.body.user.id;

    const product = await request("POST", "/api/products", { name: "E2E Widget", price: 19.99, category: "E2E" });
    if (product.status !== 201) throw new Error("E2E: Failed to create product");
    const productId = product.body.product.id;

    const order = await request("POST", "/api/orders", { userId, items: [{ productId, quantity: 3 }] });
    if (order.status !== 201) throw new Error("E2E: Failed to create order");
    if (order.body.order.total !== 59.97) throw new Error(`E2E: Expected total 59.97 got ${order.body.order.total}`);
    if (order.body.order.userName !== "E2E User") throw new Error("E2E: Wrong userName in order");

    const fetched = await request("GET", `/api/orders/${order.body.order.id}`);
    if (fetched.status !== 200) throw new Error("E2E: Failed to fetch order");
    if (fetched.body.order.total !== 59.97) throw new Error("E2E: Order total mismatch after fetch");
  });

  server.close();
  console.log(output.join("\n"));
  process.exit(allPassed ? 0 : 1);
}

run().catch((err) => {
  console.error(`FATAL: ${err.message}`);
  process.exit(1);
});