/**
 * In-memory data store with CRUD operations.
 * Domain-agnostic — each instance manages one entity type.
 * Uses UUID strings for IDs. Easily swappable for a database-backed implementation.
 */
class DataStore {
  constructor() {
    this._items = new Map();
  }

  /** Create an item. Returns the created record with id and createdAt. */
  create(item) {
    const id = require("crypto").randomUUID();
    const record = { id, ...item, createdAt: new Date().toISOString() };
    this._items.set(id, record);
    return { ...record };
  }

  /** Retrieve an item by id, or null if not found. */
  get(id) {
    const record = this._items.get(id);
    return record ? { ...record } : null;
  }

  /** List all items. Returns a shallow copy array. */
  list() {
    return Array.from(this._items.values()).map((r) => ({ ...r }));
  }

  /** Update an item by id. Returns the updated item, or null if not found. */
  update(id, updates) {
    const existing = this._items.get(id);
    if (!existing) return null;
    const updated = {
      ...existing,
      ...updates,
      id: existing.id,
      createdAt: existing.createdAt,
      updatedAt: new Date().toISOString(),
    };
    this._items.set(id, updated);
    return { ...updated };
  }

  /** Delete an item by id. Returns true if deleted, false if not found. */
  delete(id) {
    return this._items.delete(id);
  }

  /** Number of items in the store. */
  get size() {
    return this._items.size;
  }

  /** Remove all items. */
  clear() {
    this._items.clear();
  }
}

module.exports = { DataStore };