/**
 * Order Processing API — /api/orders
 * Order operations: create order, list orders, get by ID.
 */
const { Repository } = require("../data/repository");

class OrderRepository extends Repository {
  _validate(data, isUpdate) {
    if (!isUpdate) {
      if (!data.userId || typeof data.userId !== "string") throw new Error("userId is required (string)");
      if (!Array.isArray(data.items) || data.items.length === 0) throw new Error("items is required (non-empty array)");
    }
  }
}

function registerOrderRoutes(router, Route, repo) {
  // Create order
  Route.POST(router, "/api/orders", (req, res) => {
    const { sendJSON } = require("../server");
    try {
      const order = repo.create(req.body);
      sendJSON(res, 201, { order });
    } catch (err) {
      sendJSON(res, 400, { error: err.message });
    }
  });

  // List orders
  Route.GET(router, "/api/orders", (_req, res) => {
    const { sendJSON } = require("../server");
    const orders = repo.list();
    sendJSON(res, 200, { orders });
  });

  // Get order by ID
  Route.GET(router, "/api/orders/:id", (req, res) => {
    const { sendJSON } = require("../server");
    const order = repo.get(req.params.id);
    if (!order) return sendJSON(res, 404, { error: "Order not found" });
    sendJSON(res, 200, { order });
  });
}

module.exports = { registerOrderRoutes, OrderRepository };