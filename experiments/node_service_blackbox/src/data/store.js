/**
 * In-memory data store for users, products, and orders.
 */

const users = [
  { id: 1, name: "Alice Johnson", email: "alice@example.com", role: "admin" },
  { id: 2, name: "Bob Smith", email: "bob@example.com", role: "user" },
  { id: 3, name: "Charlie Brown", email: "charlie@example.com", role: "user" },
];

const products = [
  { id: 1, name: "Wireless Mouse", price: 29.99, category: "Electronics", inStock: true },
  { id: 2, name: "Mechanical Keyboard", price: 89.99, category: "Electronics", inStock: true },
  { id: 3, name: "USB-C Hub", price: 34.99, category: "Accessories", inStock: true },
  { id: 4, name: "Notebook (Pack of 5)", price: 12.49, category: "Stationery", inStock: false },
];

const orders = [];
let nextUserId = 4;
let nextProductId = 5;
let nextOrderId = 1;

function getUsers() {
  return users;
}

function getUserById(id) {
  return users.find(u => u.id === id) || null;
}

function createUser({ name, email, role }) {
  const user = { id: nextUserId++, name, email, role: role || "user" };
  users.push(user);
  return user;
}

function getProducts() {
  return products;
}

function getProductById(id) {
  return products.find(p => p.id === id) || null;
}

function createProduct({ name, price, category }) {
  const product = { id: nextProductId++, name, price, category, inStock: true };
  products.push(product);
  return product;
}

function getOrders() {
  return orders;
}

function getOrderById(id) {
  return orders.find(o => o.id === id) || null;
}

function createOrder({ userId, items }) {
  if (!userId || !items || !Array.isArray(items) || items.length === 0) {
    const err = new Error("userId and non-empty items array required");
    err.status = 400;
    throw err;
  }
  const user = getUserById(userId);
  if (!user) {
    const err = new Error(`User ${userId} not found`);
    err.status = 404;
    throw err;
  }
  const orderItems = items.map(item => {
    const product = getProductById(item.productId);
    if (!product) {
      const err = new Error(`Product ${item.productId} not found`);
      err.status = 404;
      throw err;
    }
    if (!product.inStock) {
      const err = new Error(`Product ${product.name} is out of stock`);
      err.status = 400;
      throw err;
    }
    return { productId: product.id, name: product.name, price: product.price, quantity: item.quantity || 1 };
  });
  const total = orderItems.reduce((sum, item) => sum + item.price * item.quantity, 0);
  const order = {
    id: nextOrderId++,
    userId,
    userName: user.name,
    items: orderItems,
    total: Math.round(total * 100) / 100,
    status: "pending",
    createdAt: new Date().toISOString(),
  };
  orders.push(order);
  return order;
}

module.exports = { getUsers, getUserById, createUser, getProducts, getProductById, createProduct, getOrders, getOrderById, createOrder };