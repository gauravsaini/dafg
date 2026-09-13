const { Router } = require("express");

const router = Router();

router.get("/", (_req, res) => {
  res.json({ status: "ok", timestamp: new Date().toISOString(), uptime: process.uptime() });
});

module.exports = router;