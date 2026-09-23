// MyHealth SG BFF / API gateway.
// App (Kotlin/Compose) -> [ this BFF: JWT auth ] -> OpenMRS core.
// Local eval TARGET only. No TLS, deliberately simple creds.

import express from "express";
import { config } from "./config.js";
import { discoverCitizens } from "./citizens.js";
import { loginRouter } from "./routes/login.js";
import { meRouter } from "./routes/me.js";
import { patientsRouter } from "./routes/patients.js";
import { appointmentsRouter } from "./routes/appointments.js";
import { seedAppointments } from "./appointments.js";

const app = express();
app.use(express.json());

// Permissive CORS — this is a local eval target consumed by an Android
// client and by curl; not a production posture.
app.use((req, res, next) => {
  res.set("Access-Control-Allow-Origin", "*");
  res.set("Access-Control-Allow-Headers", "Authorization, Content-Type");
  res.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

// Liveness.
app.get("/health", (req, res) => res.json({ status: "ok" }));

// Routes.
app.use(loginRouter); // POST /login
app.use(meRouter); // GET /me, /me/records, /me/children
app.use(patientsRouter); // GET /patients/:id/records  (seam for ticket 09)
app.use(appointmentsRouter); // GET/POST /me/appointments*  (ticket 07)

app.use((req, res) => res.status(404).json({ error: "not_found" }));

async function main() {
  console.log(`[bff] discovering seeded citizens via ${config.openmrs.baseUrl} ...`);
  try {
    const found = await discoverCitizens();
    console.log(
      `[bff] resolved ${found.length} citizens:`,
      found.map((c) => `${c.legacyId}=${c.uuid.slice(0, 8)}`).join(" ")
    );
    // Ticket 07: seed each citizen's appointments (idempotent) and cache the
    // bookable services from OpenMRS. See appointments.js for why the BFF holds
    // the authoritative appointment store.
    const appt = await seedAppointments(found);
    console.log(
      `[bff] appointments: ${appt.services} services, seeded ${appt.seededCitizens} citizens`
    );
  } catch (err) {
    console.error(
      `[bff] WARNING: citizen discovery failed (${err.message}). ` +
        `Is OpenMRS up at ${config.openmrs.baseUrl}? Starting anyway; ` +
        `/login will 401 until discovery succeeds. Restart once OpenMRS is ready.`
    );
  }

  app.listen(config.port, config.host, () => {
    console.log(`[bff] listening on http://${config.host}:${config.port}`);
  });
}

main();
