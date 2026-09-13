const express = require("express");
const { errorHandler } = require("./middleware/error");
const healthRouter = require("./routes/health");
const usersRouter = require("./routes/users");
const productsRouter = require("./routes/products");
const ordersRouter = require("./routes/orders");

const app = express();
app.use(express.json());

// Routes
app.use("/health", healthRouter);
app.use("/api/users", usersRouter);
app.use("/api/products", productsRouter);
app.use("/api/orders", ordersRouter);

// Error handler (must be last)
app.use(errorHandler);

const PORT = process.env.PORT || 3000;

if (require.main === module) {
  const server = app.listen(PORT, () => {
    console.log(`Service listening on port ${server.address().port}`);
  });
}

module.exports = app;