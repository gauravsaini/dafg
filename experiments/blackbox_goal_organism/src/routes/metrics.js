/**
 * Service Metrics API — /api/metrics
 * Returns request count, uptime, memory usage, and timestamp.
 */
function registerMetricsRoutes(router, Route, context) {
  Route.GET(router, "/api/metrics", (_req, res) => {
    const { sendJSON } = require("../server");
    const uptime = Math.floor((Date.now() - context.startedAt) / 1000);
    const mem = process.memoryUsage();
    sendJSON(res, 200, {
      requestCount: context.requestCount.count,
      uptime,
      memoryUsage: {
        heapUsed: mem.heapUsed,
        heapTotal: mem.heapTotal,
        rss: mem.rss,
      },
      timestamp: new Date().toISOString(),
    });
  });
}

module.exports = { registerMetricsRoutes };