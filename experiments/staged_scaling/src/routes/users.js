/**
 * User Management API — /api/users
 * CRUD operations: create, list, get by ID, delete.
 */
const { Repository } = require("../data/repository");

class UserRepository extends Repository {
  _validate(data, isUpdate) {
    if (!isUpdate) {
      if (!data.name || typeof data.name !== "string") throw new Error("name is required (string)");
      if (!data.email || typeof data.email !== "string") throw new Error("email is required (string)");
    }
  }
}

function registerUserRoutes(router, Route, repo) {
  // Create user
  Route.POST(router, "/api/users", (req, res) => {
    const { sendJSON } = require("../server");
    try {
      const user = repo.create(req.body);
      sendJSON(res, 201, { user });
    } catch (err) {
      sendJSON(res, 400, { error: err.message });
    }
  });

  // List users
  Route.GET(router, "/api/users", (_req, res) => {
    const { sendJSON } = require("../server");
    const users = repo.list();
    sendJSON(res, 200, { users });
  });

  // Get user by ID
  Route.GET(router, "/api/users/:id", (req, res) => {
    const { sendJSON } = require("../server");
    const user = repo.get(req.params.id);
    if (!user) return sendJSON(res, 404, { error: "User not found" });
    sendJSON(res, 200, { user });
  });

  // Delete user by ID
  Route.DELETE(router, "/api/users/:id", (req, res) => {
    const { sendJSON } = require("../server");
    const deleted = repo.delete(req.params.id);
    if (!deleted) return sendJSON(res, 404, { error: "User not found" });
    sendJSON(res, 200, { deleted: true });
  });
}

module.exports = { registerUserRoutes, UserRepository };