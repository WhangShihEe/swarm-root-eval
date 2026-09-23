// /me/* — the authenticated citizen's OWN profile + records.
// Authz here is trivially correct: it always uses req.citizen.uuid from
// the verified JWT, never an id from the request.

import { Router } from "express";
import { requireAuth } from "../auth.js";
import {
  getByUuid,
  getLinkedPatientUuids,
} from "../citizens.js";
import {
  getEncounters,
  getRelationships,
  normaliseRecords,
} from "../openmrs.js";

export const meRouter = Router();

meRouter.use(requireAuth);

// GET /me — the caller's profile.
meRouter.get("/me", (req, res) => {
  const profile = getByUuid(req.citizen.uuid) || req.citizen;
  res.json({
    legacyId: profile.legacyId,
    uuid: profile.uuid,
    name: profile.name,
    ssn: profile.ssn ?? null,
    gender: profile.gender ?? null,
    birthdate: profile.birthdate ?? null,
  });
});

// GET /me/records — the caller's OWN records via OpenMRS.
meRouter.get("/me/records", async (req, res) => {
  try {
    const encounters = await getEncounters(req.citizen.uuid);
    res.json({
      patient: {
        legacyId: req.citizen.legacyId,
        uuid: req.citizen.uuid,
        name: req.citizen.name,
      },
      records: normaliseRecords(encounters),
    });
  } catch (err) {
    res.status(502).json({ error: "openmrs_upstream_error", detail: err.message });
  }
});

// GET /me/children — the caller's linked children (dependents).
// Feeds ticket 06 (caregiver view) and documents the linked-profile seam.
meRouter.get("/me/children", async (req, res) => {
  try {
    const rels = await getRelationships(req.citizen.uuid);
    const children = rels
      .filter((r) => /parent\/child/i.test(r?.relationshipType?.display || ""))
      .filter((r) => r?.personA?.uuid === req.citizen.uuid)
      .map((r) => ({ uuid: r.personB.uuid, name: r.personB.display }));
    res.json({ children });
  } catch (err) {
    res.status(502).json({ error: "openmrs_upstream_error", detail: err.message });
  }
});

// Exposed for reuse/tests: the set of patient UUIDs the caller may view.
export { getLinkedPatientUuids };
