// In-memory citizen registry, populated at startup by discovering the
// seeded citizens' OpenMRS UUIDs via their STABLE Legacy IDs.
// No UUID is ever hardcoded here.

import {
  findPatientByLegacyId,
  getRelationships,
} from "./openmrs.js";
import { SEEDED_LEGACY_IDS, LOGIN_LEGACY_IDS } from "./config.js";

// legacyId -> profile ; and a secondary index by uuid and by ssn.
const byLegacyId = new Map();
const byUuid = new Map();
const bySsn = new Map();

/** Discover all seeded patients up front. Call once at boot. */
export async function discoverCitizens() {
  byLegacyId.clear();
  byUuid.clear();
  bySsn.clear();

  const found = [];
  for (const legacyId of SEEDED_LEGACY_IDS) {
    const p = await findPatientByLegacyId(legacyId);
    if (!p) {
      console.warn(`[bff] could not resolve seeded citizen ${legacyId}`);
      continue;
    }
    const profile = {
      legacyId: p.legacyId,
      uuid: p.uuid,
      ssn: p.ssn,
      name: p.name,
      gender: p.gender,
      birthdate: p.birthdate,
      canLogin: LOGIN_LEGACY_IDS.includes(p.legacyId),
    };
    byLegacyId.set(profile.legacyId, profile);
    byUuid.set(profile.uuid, profile);
    if (profile.ssn) bySsn.set(profile.ssn, profile);
    found.push(profile);
  }
  return found;
}

/** Resolve a login username (Legacy ID OR NRIC-like SSN) to a profile. */
export function resolveLogin(username) {
  if (!username) return null;
  const u = String(username).trim();
  const profile = byLegacyId.get(u) || bySsn.get(u);
  if (!profile || !profile.canLogin) return null;
  return profile;
}

export function getByUuid(uuid) {
  return byUuid.get(uuid) || null;
}

export function getByLegacyId(legacyId) {
  return byLegacyId.get(legacyId) || null;
}

/**
 * Linked-profile helper — the seam ticket 09 (BOLA) will exploit.
 *
 * Returns the patient UUIDs a citizen is authorised to view: their OWN
 * record plus every child linked via an OpenMRS "Parent/Child"
 * relationship where the citizen is the parent (personA).
 *
 * Ticket 09 plants BOLA by having /patients/{id}/records SKIP the check
 * that consults this set. For THIS ticket the check is enforced.
 */
export async function getLinkedPatientUuids(citizenUuid) {
  const linked = new Set([citizenUuid]);
  const rels = await getRelationships(citizenUuid);
  for (const r of rels) {
    const type = r?.relationshipType?.display || "";
    if (!/parent\/child/i.test(type)) continue;
    // personA = Parent, personB = Child (per seed script).
    if (r?.personA?.uuid === citizenUuid && r?.personB?.uuid) {
      linked.add(r.personB.uuid);
    }
  }
  return linked;
}

/** True if `citizenUuid` may view `targetPatientUuid` (self or linked child). */
export async function canAccessPatient(citizenUuid, targetPatientUuid) {
  if (citizenUuid === targetPatientUuid) return true;
  const linked = await getLinkedPatientUuids(citizenUuid);
  return linked.has(targetPatientUuid);
}
