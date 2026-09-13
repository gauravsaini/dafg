const { Router } = require("express");
const store = require("../data/store");
const { asyncHandler } = require("../middleware/error");

const router = Router();

router.get("/", asyncHandler((_req, res) => {
  res.json({ orders: store.getOrders() });
}));

router.get("/:id", asyncHandler((req, res) => {
  const order = store.getOrderById(Number(req.params.id));
  if (!order) {
    return res.status(404).json({ error: { message: "Order not found", status: 404 } });
  }
  res.json({ order });
}));

router.post("/", asyncHandler((req, res) => {
  const { userId, items } = req.body;
  try {
    const order = store.createOrder({ userId, items });
    res.status(201).json({ order });
  } catch (err) {
    res.status(err.status || 500).json({ error: { message: err.message, status: err.status || 500 } });
  }
}));

module.exports = router;