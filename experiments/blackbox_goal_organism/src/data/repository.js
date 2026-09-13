/**
 * Domain-agnostic repository base class.
 * Wraps DataStore with validation hooks and a clean CRUD interface.
 * Subclass and override `_validate()` for domain-specific rules.
 */
const { DataStore } = require("./store");

class Repository {
  constructor() {
    this._store = new DataStore();
  }

  create(data) {
    this._validate(data);
    return this._store.create(this._sanitize(data));
  }

  get(id) {
    return this._store.get(id);
  }

  list() {
    return this._store.list();
  }

  update(id, data) {
    this._validate(data, true);
    return this._store.update(id, this._sanitize(data));
  }

  delete(id) {
    return this._store.delete(id);
  }

  clear() {
    this._store.clear();
  }

  get size() {
    return this._store.size;
  }

  /** Override in subclasses to enforce shape/required fields. */
  _validate(data, isUpdate = false) {
    // Subclasses implement validation
  }

  /** Override to strip unknown fields. Default identity. */
  _sanitize(data) {
    return { ...data };
  }
}

module.exports = { Repository };