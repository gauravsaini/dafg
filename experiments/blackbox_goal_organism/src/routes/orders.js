/**
 * Order Processing API — /api/orders
 * Operations: create order (with user & product validation, total computation),
 * list orders, get by ID.
 */
const { Repository } = require("../data/repository");
const { UserRepository } = require("./users");
const { ProductRepository } = require("./products");

class OrderRepository extends Repository {
  _validate(data, isUpdate) {
    if (!isUpdate) {
      if (!data.userId || typeof data.userId !== "string") throw new Error("userId is required (string)");
      if (!Array.isArray(data.items) || data.items.length === 0) throw new Error("items is required (non-empty array)");
    }
  }
}

function registerOrderRoutes(router, Route, userRepo, productRepo) {
  const repo = new OrderRepository();

  // Create order — enrich items from product catalog, compute total
  Route.POST(router, "/api/orders", (req, res) => {
    const { sendJSON } = require("../server");
    try {
      const { userId, items } = req.body;

      // Validate user
      if (!userId || typeof userId !== "string")
        return sendJSON(res, 400, { error: "userId is required (string)" });
      const user = userRepo.get(userId);
      if (!user) return sendJSON(res, 404, { error: `User ${userId} not found` });

      // Validate and enrich items
      if (!Array.isArray(items) || items.length === 0)
        return sendJSON(res, 400, { error: "items is required (non-empty array)" });

      const orderItems = items.map((item) => {
        if (!item.productId) throw new Error("Each item must have a productId");
        const product = productRepo.get(item.productId);
        if (!product) throw new Error(`Product ${item.productId} not found`);
        const quantity = item.quantity || 1;
        return {
          productId: product.id,
          name: product.name,
          price: product.price,
          quantity,
        };
      });

      const total = Math.round(orderItems.reduce((sum, it) => sum + it.price * it.quantity, 0) * 100) / 100;

      const order = repo.create({ userId, userName: user.name, items: orderItems, total, status: "pending" });
      sendJSON(res, 201, { order });
    } catch (err) {
      const status = err.message.includes("not found") ? 404 : 400;
      sendJSON(res, status, { error: err.message });
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