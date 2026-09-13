/**
 * Route index — wires all domain routes into the router.
 */
const { registerUserRoutes, UserRepository } = require("./users");
const { registerProductRoutes, ProductRepository } = require("./products");
const { registerOrderRoutes, OrderRepository } = require("./orders");
const { registerMetricsRoutes } = require("./metrics");

function registerRoutes(router, Route, context = {}) {
  const userRepo = new UserRepository();
  const productRepo = new ProductRepository();
  const orderRepo = new OrderRepository();

  registerUserRoutes(router, Route, userRepo);
  registerProductRoutes(router, Route, productRepo);
  registerOrderRoutes(router, Route, orderRepo);
  registerMetricsRoutes(router, Route, context);
}

module.exports = { registerRoutes };