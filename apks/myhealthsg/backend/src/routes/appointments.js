// /me/appointments/* — the authenticated citizen's OWN appointments (ticket 07).
//
// Authz is trivially CORRECT here (like /me/*): every handler keys off
// req.citizen.uuid from the verified JWT, never an id from the request body or
// path. A caller can only ever list/create/cancel/reschedule their OWN
// appointments; :id operations resolve within the caller's own set, so an id
// belonging to another citizen simply 404s.
//
// Data source: the BFF-side appointments store (see ../appointments.js and the
// README for why OpenMRS is not the read source on this box). Services are
// pulled from OpenMRS; creates are mirrored to OpenMRS best-effort.

import { Router } from "express";
import { requireAuth } from "../auth.js";
import {
  listForCitizen,
  listServices,
  createForCitizen,
  cancelForCitizen,
  rescheduleForCitizen,
  INSTITUTIONS,
} from "../appointments.js";

export const appointmentsRouter = Router();

appointmentsRouter.use(requireAuth);

// GET /me/appointments?status=upcoming|missed|open  (default: upcoming)
appointmentsRouter.get("/me/appointments", (req, res) => {
  const status = String(req.query.status || "upcoming").toLowerCase();
  if (!["upcoming", "missed", "open"].includes(status)) {
    return res.status(400).json({ error: "invalid_status" });
  }
  res.json({ status, appointments: listForCitizen(req.citizen.uuid, status) });
});

// GET /me/appointments/services — bookable services (OpenMRS) + institutions.
appointmentsRouter.get("/me/appointments/services", (req, res) => {
  res.json({ services: listServices(), institutions: INSTITUTIONS });
});

// POST /me/appointments — create for the caller.
// body: { serviceUuid, institution, startDateTime (ISO, omit for open), durationMins? }
appointmentsRouter.post("/me/appointments", async (req, res) => {
  const { serviceUuid, institution, startDateTime, durationMins } = req.body || {};
  try {
    const appt = await createForCitizen(req.citizen.uuid, {
      serviceUuid,
      institution,
      startDateTime,
      durationMins,
    });
    res.status(201).json({ appointment: appt });
  } catch (err) {
    res.status(500).json({ error: "create_failed", detail: err.message });
  }
});

// POST /me/appointments/:id/cancel — cancel one of the caller's appointments.
appointmentsRouter.post("/me/appointments/:id/cancel", (req, res) => {
  const appt = cancelForCitizen(req.citizen.uuid, req.params.id);
  if (!appt) return res.status(404).json({ error: "appointment_not_found" });
  res.json({ appointment: appt });
});

// POST /me/appointments/:id/reschedule — move to a new datetime.
// body: { startDateTime (ISO), durationMins? }
appointmentsRouter.post("/me/appointments/:id/reschedule", (req, res) => {
  const { startDateTime, durationMins } = req.body || {};
  if (!startDateTime) {
    return res.status(400).json({ error: "startDateTime_required" });
  }
  const appt = rescheduleForCitizen(req.citizen.uuid, req.params.id, startDateTime, durationMins);
  if (!appt) return res.status(404).json({ error: "appointment_not_found" });
  res.json({ appointment: appt });
});
