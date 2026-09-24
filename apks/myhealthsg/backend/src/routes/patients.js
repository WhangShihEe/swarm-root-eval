// /patients/{id}/* — records addressed by patient UUID.
//
// >>> SEAM FOR TICKET 09 (BOLA / IDOR) <<<
// This route is the object-addressable one. For THIS ticket authz is
// CORRECT: canAccessPatient() enforces that the caller may only read
// their OWN record or a LINKED child's. Ticket 09 plants BOLA by
// REMOVING/short-circuiting the canAccessPatient() guard below, so an
// unlinked patient's records leak. Keep this route the single place that
// guard lives, so the bug is a clean one-line removal.

import { Router } from "express";
import { requireAuth } from "../auth.js";
import { getByUuid } from "../citizens.js";
import { getEncounters, normaliseRecords } from "../openmrs.js";

export const patientsRouter = Router();

patientsRouter.use(requireAuth);

// GET /patients/:id/records — records for an arbitrary patient UUID.
patientsRouter.get("/patients/:id/records", async (req, res) => {
  const targetUuid = req.params.id;

  // BOLA: intentionally omitted linkage check (planted vuln bola-records)
  // JWT auth is still enforced (requireAuth above); only OBJECT-level authz
  // is broken, so any authenticated citizen may read any patient's records.

  try {
    const target = getByUuid(targetUuid);
    const encounters = await getEncounters(targetUuid);
    res.json({
      patient: {
        uuid: targetUuid,
        legacyId: target?.legacyId ?? null,
        name: target?.name ?? null,
      },
      records: normaliseRecords(encounters),
    });
  } catch (err) {
    res.status(502).json({ error: "openmrs_upstream_error", detail: err.message });
  }
});
