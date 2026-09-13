/**
 * Blackbox Goal Organism — Node.js REST API server.
 * Zero external dependencies: uses Node.js stdlib `http` module.
 *
 * Architecture:
 *   - Core router dispatches by method + pathname with Express-like param patterns
 *   - Built-in JSON body parser for POST/PUT/PATCH
 *   - Health endpoint at /health
 *   - Route modules register via `register(registerFn, context?)`
 */

const http = require("http");
const { URL } = require("url");

// ── Router ──────────────────────────────────────────────────────────
function createRouter() {
  const routes = [];

  function add(method, pattern, handler) {
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
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });
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
  const requestCount = { count: 0 };

  // Built-in health route
  registerHealth(router, startedAt);

  const context = { startedAt, requestCount };

  // External route registration
  const register = (fn, ctx) => fn(router, Route, ctx || context);

  // Wrap dispatch with request counting
  function handler(req, res) {
    requestCount.count++;
    parseBody(req).then((body) => {
      req.body = body;
      router.dispatch(req, res);
    }).catch(() => {
      sendJSON(res, 500, { error: "Internal Server Error" });
    });
  }

  const server = http.createServer(handler);

  return { server, register, context, router };
}

// ── Standalone launch ──────────────────────────────────────────────
if (require.main === module) {
  const { server, register } = createServer();
  const { registerRoutes } = require("./routes/index");
  register(registerRoutes);

  const PORT = process.env.PORT || 0;
  server.listen(PORT, () => {
    const addr = server.address();
    console.log(`Server listening on port ${addr.port}`);
  });
}

module.exports = { createServer, sendJSON, Route };