// Appointments data layer for the BFF (ticket 07).
//
// WHY A BFF-SIDE STORE (not OpenMRS as source of truth):
// The Bahmni "Bahmni Appointment Scheduling" module IS installed and its
// write + metadata paths work — POST /appointment creates a real appointment
// and GET /appointmentService/all/default lists the seeded services. BUT every
// appointment READ path on this box (GET /appointment?uuid=, GET
// /appointments?patient=, POST /appointments/search, GET /appointment/all)
// fails with:
//     SQLGrammarException: Table 'openmrs.patient_appointment_occurrence'
//                          doesn't exist
// i.e. the module's recurring-appointments Liquibase changeset never ran on
// this image, so appointments cannot be listed back reliably. We are not
// allowed to alter the OpenMRS image/schema, so we cannot fix that migration.
//
// Therefore the BFF keeps its OWN authoritative in-memory appointment store,
// seeded per citizen at startup (idempotent). To still honour "prefer OpenMRS"
// we (a) pull the bookable SERVICES from OpenMRS at startup (that read works),
// and (b) BEST-EFFORT mirror every created appointment into OpenMRS via POST
// /appointment (non-fatal if it errors). See backend/bff/README.md.

import { config } from "./config.js";

// -------------------------------------------------------------------------
// OpenMRS helpers (only the paths that actually work on this box).
// -------------------------------------------------------------------------

function omrsAuthHeader() {
  const token = Buffer.from(
    `${config.openmrs.user}:${config.openmrs.pass}`
  ).toString("base64");
  return `Basic ${token}`;
}

/** Bookable services, from OpenMRS (GET /appointmentService/all/default). */
async function fetchOpenmrsServices() {
  const url = `${config.openmrs.baseUrl}/appointmentService/all/default`;
  const res = await fetch(url, {
    headers: { Authorization: omrsAuthHeader(), Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`OpenMRS services -> ${res.status}`);
  const arr = await res.json();
  return (Array.isArray(arr) ? arr : [])
    .filter((s) => s && s.uuid && s.name)
    .map((s) => ({ uuid: s.uuid, name: s.name, color: s.color ?? null }));
}

/** Best-effort mirror of a created appointment into OpenMRS (non-fatal). */
async function mirrorCreateToOpenmrs(appt) {
  if (!appt.serviceUuid || !appt.startDateTime || !appt.endDateTime) return null;
  try {
    const url = `${config.openmrs.baseUrl}/appointment`;
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: omrsAuthHeader(),
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        patientUuid: appt.citizenUuid,
        serviceUuid: appt.serviceUuid,
        startDateTime: appt.startDateTime,
        endDateTime: appt.endDateTime,
        appointmentKind: "Scheduled",
      }),
    });
    if (!res.ok) return null;
    const body = await res.json().catch(() => ({}));
    return body?.uuid || null;
  } catch {
    return null; // OpenMRS mirror is best-effort only.
  }
}

// -------------------------------------------------------------------------
// In-memory store.  Map<citizenUuid, Appointment[]>
// -------------------------------------------------------------------------

/** @typedef {"Scheduled"|"Missed"|"Requested"|"Cancelled"} ApptStatus */

const byCitizen = new Map();
let SERVICES = []; // populated at startup (OpenMRS, with fallback)
let seq = 1000;

// Static SG institutions for the picker (OpenMRS services carry no location).
export const INSTITUTIONS = [
  "National University Hospital",
  "Singapore General Hospital",
  "Tan Tock Seng Hospital",
  "Outram Polyclinic",
  "Bedok Polyclinic",
];

// Fallback service list if the OpenMRS read is unavailable at boot.
const FALLBACK_SERVICES = [
  { uuid: "svc-general-medicine", name: "General Medicine service", color: null },
  { uuid: "svc-outpatient", name: "Outpatient Department", color: null },
  { uuid: "svc-rehab", name: "Rehabilitation service", color: null },
];

function nextId() {
  seq += 1;
  return `appt-${seq}`;
}

function dateChip(iso) {
  if (!iso) return "TBC";
  const d = new Date(iso);
  return d.toLocaleDateString("en-SG", { day: "2-digit", month: "short" });
}

function dateTimeLabel(iso) {
  if (!iso) return "To be scheduled";
  const d = new Date(iso);
  return d.toLocaleString("en-SG", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

/** Public view of an appointment (adds derived labels). */
export function toView(a) {
  return {
    id: a.id,
    serviceUuid: a.serviceUuid,
    serviceName: a.serviceName,
    institution: a.institution,
    startDateTime: a.startDateTime,
    endDateTime: a.endDateTime,
    status: a.status,
    dateChip: dateChip(a.startDateTime),
    dateTimeLabel: dateTimeLabel(a.startDateTime),
    openmrsUuid: a.openmrsUuid ?? null,
  };
}

function isoInDays(days, hour = 9, minute = 0) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

function plusMinutes(iso, mins) {
  if (!iso) return null;
  return new Date(new Date(iso).getTime() + mins * 60000).toISOString();
}

function serviceName(uuid) {
  return SERVICES.find((s) => s.uuid === uuid)?.name || SERVICES[0]?.name || "Appointment";
}

// -------------------------------------------------------------------------
// Seeding — idempotent per citizen.
// -------------------------------------------------------------------------

/**
 * Seed a spread of appointments for each seeded citizen: two upcoming, one
 * missed (past), one open (Requested, not yet scheduled). Idempotent: skips a
 * citizen who already has appointments.
 */
export async function seedAppointments(citizens) {
  // Resolve bookable services from OpenMRS (falls back to a static list).
  try {
    SERVICES = await fetchOpenmrsServices();
    if (!SERVICES.length) SERVICES = FALLBACK_SERVICES;
  } catch {
    SERVICES = FALLBACK_SERVICES;
  }

  const s0 = SERVICES[0];
  const s1 = SERVICES[1] || SERVICES[0];
  const s2 = SERVICES[2] || SERVICES[0];

  for (const c of citizens || []) {
    if (!c?.uuid || !c?.canLogin) continue; // only adult, loginable citizens
    if (byCitizen.has(c.uuid) && byCitizen.get(c.uuid).length) continue;

    const list = [
      mk(c.uuid, s0, INSTITUTIONS[0], isoInDays(7, 9, 30), "Scheduled"),
      mk(c.uuid, s1, INSTITUTIONS[1], isoInDays(21, 14, 0), "Scheduled"),
      mk(c.uuid, s0, INSTITUTIONS[2], isoInDays(-14, 10, 0), "Missed"),
      mk(c.uuid, s2, INSTITUTIONS[3], null, "Requested"), // open referral
    ];
    byCitizen.set(c.uuid, list);
  }
  return { services: SERVICES.length, seededCitizens: byCitizen.size };
}

function mk(citizenUuid, svc, institution, startIso, status) {
  return {
    id: nextId(),
    citizenUuid,
    serviceUuid: svc?.uuid ?? null,
    serviceName: svc?.name ?? "Appointment",
    institution,
    startDateTime: startIso,
    endDateTime: startIso ? plusMinutes(startIso, 30) : null,
    status,
    openmrsUuid: null,
  };
}

// -------------------------------------------------------------------------
// Query + mutation API (all keyed by the caller's own citizenUuid).
// -------------------------------------------------------------------------

export function listServices() {
  return SERVICES.length ? SERVICES : FALLBACK_SERVICES;
}

function all(citizenUuid) {
  return byCitizen.get(citizenUuid) || [];
}

/** Appointments for a citizen filtered by tab: upcoming | missed | open. */
export function listForCitizen(citizenUuid, tab) {
  const now = Date.now();
  const items = all(citizenUuid).filter((a) => {
    if (a.status === "Cancelled") return false;
    const t = a.startDateTime ? new Date(a.startDateTime).getTime() : null;
    switch (tab) {
      case "upcoming":
        return a.status === "Scheduled" && t !== null && t >= now;
      case "missed":
        return a.status === "Missed" || (a.status === "Scheduled" && t !== null && t < now);
      case "open":
        return a.status === "Requested";
      default:
        return true;
    }
  });
  // Upcoming ascending, missed descending, open as-is.
  items.sort((x, y) => {
    const tx = x.startDateTime ? new Date(x.startDateTime).getTime() : 0;
    const ty = y.startDateTime ? new Date(y.startDateTime).getTime() : 0;
    return tab === "missed" ? ty - tx : tx - ty;
  });
  return items.map(toView);
}

/** The citizen's upcoming appointments — feeds the HOME dashboard card. */
export function upcomingForCitizen(citizenUuid) {
  return listForCitizen(citizenUuid, "upcoming");
}

/** Create a new appointment for the caller. Mirrors to OpenMRS best-effort. */
export async function createForCitizen(citizenUuid, { serviceUuid, institution, startDateTime, durationMins }) {
  const start = startDateTime || null;
  const appt = {
    id: nextId(),
    citizenUuid,
    serviceUuid: serviceUuid || SERVICES[0]?.uuid || null,
    serviceName: serviceName(serviceUuid),
    institution: institution || INSTITUTIONS[0],
    startDateTime: start,
    endDateTime: start ? plusMinutes(start, durationMins || 30) : null,
    status: start ? "Scheduled" : "Requested",
    openmrsUuid: null,
  };
  const list = byCitizen.get(citizenUuid) || [];
  list.push(appt);
  byCitizen.set(citizenUuid, list);

  appt.openmrsUuid = await mirrorCreateToOpenmrs(appt);
  return toView(appt);
}

function find(citizenUuid, id) {
  return all(citizenUuid).find((a) => a.id === id) || null;
}

/** Cancel one of the caller's appointments. Returns null if not owned/found. */
export function cancelForCitizen(citizenUuid, id) {
  const a = find(citizenUuid, id);
  if (!a) return null;
  a.status = "Cancelled";
  return toView(a);
}

/** Reschedule one of the caller's appointments to a new datetime. */
export function rescheduleForCitizen(citizenUuid, id, startDateTime, durationMins) {
  const a = find(citizenUuid, id);
  if (!a) return null;
  a.startDateTime = startDateTime;
  a.endDateTime = startDateTime ? plusMinutes(startDateTime, durationMins || 30) : null;
  a.status = "Scheduled";
  return toView(a);
}
