// Thin OpenMRS REST client. Server-to-server basic auth.
// Uses the global fetch shipped with Node 18+ (no extra deps).

import { config } from "./config.js";

function authHeader() {
  const token = Buffer.from(
    `${config.openmrs.user}:${config.openmrs.pass}`
  ).toString("base64");
  return `Basic ${token}`;
}

async function omrsGet(path) {
  const url = `${config.openmrs.baseUrl}${path}`;
  const res = await fetch(url, {
    headers: { Authorization: authHeader(), Accept: "application/json" },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(
      `OpenMRS GET ${path} -> ${res.status} ${res.statusText} ${body.slice(0, 200)}`
    );
  }
  return res.json();
}

/**
 * Resolve a patient by their STABLE Legacy ID (e.g. MHSG-CIT-01).
 * Never hardcode UUIDs — they regenerate if the DB is wiped.
 * Returns null if not found.
 */
export async function findPatientByLegacyId(legacyId) {
  const data = await omrsGet(
    `/patient?identifier=${encodeURIComponent(legacyId)}&v=default`
  );
  const p = data?.results?.[0];
  if (!p) return null;

  const idents = p.identifiers || [];
  const legacy = idents.find((i) => /Legacy ID/i.test(i.display || ""));
  const ssn = idents.find((i) => /SSN/i.test(i.display || ""));

  return {
    // In OpenMRS the Person UUID == Patient UUID.
    uuid: p.uuid,
    legacyId: legacy ? String(legacy.display).split("=").pop().trim() : legacyId,
    ssn: ssn ? String(ssn.display).split("=").pop().trim() : null,
    name: p?.person?.display || p.display,
    gender: p?.person?.gender ?? null,
    birthdate: p?.person?.birthdate ?? null,
  };
}

/** Raw encounters (with obs) for a patient UUID. */
export async function getEncounters(patientUuid) {
  const data = await omrsGet(
    `/encounter?patient=${encodeURIComponent(patientUuid)}&v=full`
  );
  return data?.results || [];
}

/** Raw relationships for a person UUID. */
export async function getRelationships(personUuid) {
  const data = await omrsGet(
    `/relationship?person=${encodeURIComponent(personUuid)}&v=full`
  );
  return data?.results || [];
}

/** Normalise OpenMRS encounters into a compact record list for the app. */
export function normaliseRecords(encounters) {
  return (encounters || []).map((e) => ({
    id: e.uuid,
    type: e?.encounterType?.display || e?.encounterType?.name || "Encounter",
    date: e.encounterDatetime,
    observations: (e.obs || []).map((o) => o.display).filter(Boolean),
  }));
}
