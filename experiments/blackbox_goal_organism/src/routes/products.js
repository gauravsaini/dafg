/**
 * Product Catalog API — /api/products
 * Operations: create, list, get by ID.
 */
const { Repository } = require("../data/repository");

class ProductRepository extends Repository {
  _validate(data, isUpdate) {
    if (!isUpdate) {
      if (!data.name || typeof data.name !== "string") throw new Error("name is required (string)");
      if (data.price === undefined || typeof data.price !== "number") throw new Error("price is required (number)");
    }
  }
}

function registerProductRoutes(router, Route, repo) {
  // Create product
  Route.POST(router, "/api/products", (req, res) => {
    const { sendJSON } = require("../server");
    try {
      const product = repo.create(req.body);
      sendJSON(res, 201, { product });
    } catch (err) {
      sendJSON(res, 400, { error: err.message });
    }
  });

  // List products
  Route.GET(router, "/api/products", (_req, res) => {
    const { sendJSON } = require("../server");
    const products = repo.list();
    sendJSON(res, 200, { products });
  });

  // Get product by ID
  Route.GET(router, "/api/products/:id", (req, res) => {
    const { sendJSON } = require("../server");
    const product = repo.get(req.params.id);
    if (!product) return sendJSON(res, 404, { error: "Product not found" });
    sendJSON(res, 200, { product });
  });
}

module.exports = { registerProductRoutes, ProductRepository };