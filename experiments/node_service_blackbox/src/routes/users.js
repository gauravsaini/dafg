const { Router } = require("express");
const store = require("../data/store");
const { asyncHandler } = require("../middleware/error");

const router = Router();

router.get("/", asyncHandler((_req, res) => {
  res.json({ users: store.getUsers() });
}));

router.get("/:id", asyncHandler((req, res) => {
  const user = store.getUserById(Number(req.params.id));
  if (!user) {
    return res.status(404).json({ error: { message: "User not found", status: 404 } });
  }
  res.json({ user });
}));

router.post("/", asyncHandler((req, res) => {
  const { name, email, role } = req.body;
  if (!name || !email) {
    return res.status(400).json({ error: { message: "name and email are required", status: 400 } });
  }
  const user = store.createUser({ name, email, role });
  res.status(201).json({ user });
}));

module.exports = router;