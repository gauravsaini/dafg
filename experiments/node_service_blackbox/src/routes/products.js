const { Router } = require("express");
const store = require("../data/store");
const { asyncHandler } = require("../middleware/error");

const router = Router();

router.get("/", asyncHandler((_req, res) => {
  res.json({ products: store.getProducts() });
}));

router.get("/:id", asyncHandler((req, res) => {
  const product = store.getProductById(Number(req.params.id));
  if (!product) {
    return res.status(404).json({ error: { message: "Product not found", status: 404 } });
  }
  res.json({ product });
}));

router.post("/", asyncHandler((req, res) => {
  const { name, price, category } = req.body;
  if (!name || price === undefined) {
    return res.status(400).json({ error: { message: "name and price are required", status: 400 } });
  }
  const product = store.createProduct({ name, price, category: category || "General" });
  res.status(201).json({ product });
}));

module.exports = router;