/**
 * Stage Scaling — Phase 1 baseline HTTP service.
 * Zero external dependencies: uses Node.js stdlib `http` module.
 *
 * Architecture:
 *   - Core router dispatches by method + pathname
 *   - Built-in JSON body parser for POST/PUT/PATCH
 *   - Health endpoint at /health
 *   - Route modules register via `registerRoute(router)`
 */

const http = require("http");
const { URL } = require("url");

// ── Router ──────────────────────────────────────────────────────────
function createRouter() {
  const routes = [];

  function add(method, pattern, handler) {
    // Convert Express-like "/api/:param" patterns to named regex
    const paramNames = [];
    const regexStr = pattern.replace(/:([a-zA-Z_]\w*)/g, (_, name) => {
      paramNames.push(name);
      return "([^/]+)";
    });
    const regex = new RegExp(`^${regexStr}$`);
    routes.push({ method, pattern, regex, paramNames, handler });
  }

  function dispatch(req, res) {
    const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
    const pathname = url.pathname;
    const method = req.method.toUpperCase();

    for (const route of routes) {
      if (route.method !== method) continue;
      const match = pathname.match(route.regex);
      if (!match) continue;
      req.params = {};
      route.paramNames.forEach((name, i) => { req.params[name] = match[i + 1]; });
      req.query = Object.fromEntries(url.searchParams.entries());
      return route.handler(req, res);
    }

    sendJSON(res, 404, { error: "Not found", path: pathname });
  }

  return { add, dispatch };
}

// ── Helpers ─────────────────────────────────────────────────────────
function sendJSON(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
  res.end(body);
}

function parseBody(req) {
  return new Promise((resolve) => {
    if (req.method === "GET" || req.method === "HEAD") return resolve({});
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString();
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); } catch { resolve({}); }
    });
  });
}

// ── Route registration helpers ─────────────────────────────────────
const Route = {
  GET:    (router, pattern, handler) => router.add("GET", pattern, handler),
  POST:   (router, pattern, handler) => router.add("POST", pattern, handler),
  PUT:    (router, pattern, handler) => router.add("PUT", pattern, handler),
  PATCH:  (router, pattern, handler) => router.add("PATCH", pattern, handler),
  DELETE: (router, pattern, handler) => router.add("DELETE", pattern, handler),
};

// ── Health endpoint ────────────────────────────────────────────────
function registerHealth(router, startedAt) {
  Route.GET(router, "/health", (_req, res) => {
    sendJSON(res, 200, {
      status: "ok",
      timestamp: new Date().toISOString(),
      uptime: Math.floor((Date.now() - startedAt) / 1000),
    });
  });
}

// ── Create server ───────────────────────────────────────────────────
function createServer(options = {}) {
  const router = createRouter();
  const startedAt = options.startedAt || Date.now();
  const requestCount = { count: 0 }; // mutable reference for metrics

  // Built-in routes
  registerHealth(router, startedAt);

  // External route registration
  const register = (fn, ctx) => fn(router, Route, ctx || context);

  // Domain route registration context
  const context = { startedAt, requestCount: requestCount };

  const server = http.createServer(async (req, res) => {
    requestCount.count++;
    try {
      req.body = await parseBody(req);
      router.dispatch(req, res);
    } catch (err) {
      sendJSON(res, 500, { error: "Internal server error" });
    }
  });

  return { server, register, router, context };
}

module.exports = { createServer, sendJSON, Route };