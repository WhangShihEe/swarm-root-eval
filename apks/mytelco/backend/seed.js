'use strict';

const fs = require('fs');
const path = require('path');

/**
 * Loads the synthetic seed store from seed.json into memory.
 *
 * All data here is FAKE / SYNTHETIC. It backs the "MyTelco SG" showcase app.
 * The store is read once at startup and kept in memory; the process never
 * writes back to disk, so restarting the server resets any runtime state.
 */
function loadSeed() {
  const seedPath = path.join(__dirname, 'seed.json');
  const raw = fs.readFileSync(seedPath, 'utf8');
  const data = JSON.parse(raw);

  const subscribers = data.subscribers || [];

  // Build fast lookup indexes for auth + account fetch.
  const byId = new Map();
  const byLoginId = new Map(); // OnePass id (email) OR mobile -> subscriber
  const byAccountNo = new Map(); // accountNo -> subscriber

  for (const sub of subscribers) {
    byId.set(sub.id, sub);
    if (sub.accountNo) byAccountNo.set(String(sub.accountNo).trim(), sub);

    const creds = sub.credentials || {};
    if (creds.onePassId) byLoginId.set(normalizeLoginId(creds.onePassId), sub);
    if (creds.loginMobile) byLoginId.set(normalizeLoginId(creds.loginMobile), sub);
  }

  return {
    subscribers,
    shopAddons: data.shopAddons || [],
    getById(id) {
      return byId.get(id) || null;
    },
    /** Look up a subscriber by their account number. */
    getByAccountNo(accountNo) {
      if (!accountNo) return null;
      return byAccountNo.get(String(accountNo).trim()) || null;
    },
    /** Validate a login id + password. Returns the subscriber or null. */
    authenticate(id, password) {
      if (!id || !password) return null;
      const sub = byLoginId.get(normalizeLoginId(id));
      if (!sub) return null;
      if (sub.credentials.password !== password) return null;
      return sub;
    },
  };
}

/** Normalize a login id so "+65 9123 4567", "6591234567" and emails match. */
function normalizeLoginId(value) {
  const v = String(value).trim().toLowerCase();
  // If it looks like a phone number (mostly digits), strip spaces/+.
  if (/[0-9]/.test(v) && !v.includes('@')) {
    return v.replace(/[\s+()-]/g, '');
  }
  return v;
}

/**
 * Strip login credentials before returning a subscriber to a client.
 * Everything else (PII, SIM ids, bills) is part of the account payload.
 */
function toAccountView(sub) {
  if (!sub) return null;
  const { credentials, ...safe } = sub;
  return safe;
}

module.exports = { loadSeed, toAccountView, normalizeLoginId };
