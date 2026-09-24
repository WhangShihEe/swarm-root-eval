# MyHealth SG BFF / API gateway (ticket 03)

A small home-made **BFF** that authenticates citizens with a JWT
("Singpass"-cosmetic), proxies the OpenMRS core, and exposes the logged-in
citizen's profile + records.

```
App (Kotlin/Compose)  ->  [ this BFF: JWT auth ]  ->  OpenMRS core (docker)
```

> Local eval **TARGET** only. Deliberately simple creds, no TLS.
> **Do not expose to a network.** This is where graded authz bugs get
> planted in later tickets (09 = BOLA, 10 = jwt-authbypass). For **this**
> ticket the auth is intentionally CORRECT — no planted bugs.

## Stack

- Node 24 + **Express** + **jsonwebtoken**. No JVM, tiny footprint.
- Uses Node's built-in `fetch` for OpenMRS calls (no HTTP client dep).
- On startup the BFF **discovers** the seeded citizens' OpenMRS UUIDs by
  their stable Legacy IDs (`MHSG-CIT-0x` / `MHSG-CHILD-0x`). **No UUID is
  hardcoded** — they regenerate if the DB is wiped.

## Run

Prereq: the OpenMRS backend (ticket 02) is up and seeded at
`http://localhost:8080/openmrs/ws/rest/v1`.

```bash
cd backend/bff
npm install
npm start          # listens on http://0.0.0.0:3000
```

Config is env-driven (see `.env.example`); all values have sensible local
defaults, so `npm start` works with no `.env`.

| env | default | meaning |
|---|---|---|
| `PORT` | `3000` | BFF listen port |
| `HOST` | `0.0.0.0` | BFF bind address |
| `OPENMRS_BASE_URL` | `http://localhost:8080/openmrs/ws/rest/v1` | OpenMRS REST base |
| `OPENMRS_USER` / `OPENMRS_PASS` | `admin` / `Admin123` | server-to-server basic auth |
| `JWT_SECRET` | `dev-myhealthsg-demo-secret-change-me` | HS256 signing secret |
| `JWT_ALG` | `HS256` | signing + verify algorithm |
| `JWT_ISSUER` | `myhealthsg-bff` | `iss` claim |
| `JWT_EXPIRES_IN` | `1h` | token lifetime |
| `DEMO_PASSWORD` | `Password123` | shared demo password for all citizens |

> If OpenMRS is not ready when the BFF boots, discovery logs a warning and
> `/login` will 401 until you restart the BFF once OpenMRS is healthy.

## Demo credentials

Every seeded **adult** citizen logs in with the shared password
`Password123`. The username is either their **Legacy ID** or their
**NRIC-like SSN**:

| citizen | Legacy ID (username) | SSN (username) | password |
|---|---|---|---|
| Tan Wei Ming | `MHSG-CIT-01` | `S-1000001` | `Password123` |
| (citizen 2) | `MHSG-CIT-02` | `S-1000002` | `Password123` |
| (citizen 3) | `MHSG-CIT-03` | `S-1000003` | `Password123` |

Children (`MHSG-CHILD-0x`) are **dependents** and cannot log in; their
records are reached through their parent's linked-profile view.

## API

### `POST /login`

```bash
curl -s -X POST http://localhost:3000/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"MHSG-CIT-01","password":"Password123"}'
```

```jsonc
{
  "token": "<JWT>",
  "tokenType": "Bearer",
  "citizen": { "legacyId": "MHSG-CIT-01", "uuid": "<patient-uuid>", "name": "Tan Wei Ming" }
}
```

JWT claims identify the citizen: `sub`/`legacyId` = Legacy ID, `uuid` =
OpenMRS patient/person UUID, `name`, plus `iss`/`iat`/`exp`.

### `GET /me` (Bearer)
The caller's own profile.

### `GET /me/records` (Bearer)
The caller's OWN records via OpenMRS (Immunizations / Lab Results / Vitals).

```bash
TOKEN=... # from /login
curl -s http://localhost:3000/me/records -H "Authorization: Bearer $TOKEN"
```

### `GET /me/children` (Bearer)
The caller's linked children (dependents) — feeds ticket 06.

### `GET /patients/{id}/records` (Bearer)
Records for an arbitrary patient UUID. **Authz enforced now:** the caller
may only read their own record or a linked child's, else `403`. This is the
object-addressable route ticket 09 will exploit (see seams below).

### Appointments (ticket 07, Bearer) — the caller's OWN appointments only

All routes key off `req.citizen.uuid` from the verified JWT, so a caller can
only ever touch their own appointments; `:id` operations resolve within the
caller's own set (another citizen's id simply `404`s).

- `GET  /me/appointments?status=upcoming|missed|open` → `{ status, appointments:[…] }`
- `GET  /me/appointments/services` → `{ services:[{uuid,name,color}], institutions:[…] }`
  (services are pulled from OpenMRS `GET /appointmentService/all/default`).
- `POST /me/appointments` body `{serviceUuid, institution, startDateTime(ISO, omit for "open"), durationMins?}` → `201 {appointment}`
- `POST /me/appointments/:id/cancel` → `{appointment}` (status → `Cancelled`)
- `POST /me/appointments/:id/reschedule` body `{startDateTime(ISO), durationMins?}` → `{appointment}`

Each appointment carries BFF-derived `dateChip` / `dateTimeLabel` so the app and
the home dashboard card render identically. Statuses: `Scheduled` / `Missed` /
`Requested` (open referral) / `Cancelled`.

```bash
TOKEN=... # from /login
curl -s "http://localhost:3000/me/appointments?status=upcoming" -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:3000/me/appointments -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"serviceUuid":"<svc>","institution":"National University Hospital","startDateTime":"2026-11-05T02:00:00.000Z"}'
```

**Data source — why a BFF-side store, not OpenMRS as source of truth.**
The Bahmni "Bahmni Appointment Scheduling" module IS installed and its **write**
and **metadata** paths work on this box: `POST /appointment` creates a real
appointment and `GET /appointmentService/all/default` lists the seeded services.
But **every appointment READ path** (`GET /appointment?uuid=`, `GET
/appointments?patient=`, `POST /appointments/search`, `GET /appointment/all`)
fails with `SQLGrammarException: Table 'openmrs.patient_appointment_occurrence'
doesn't exist` — the module's recurring-appointments Liquibase changeset never
ran on this image, and we may not alter the OpenMRS image/schema. So appointments
cannot be listed back from OpenMRS reliably.

The BFF therefore holds the **authoritative** appointment store
(`src/appointments.js`), seeded per citizen at startup (idempotent: two upcoming,
one missed, one open per adult citizen). To still honour *prefer OpenMRS*, the
BFF (a) pulls the bookable **services from OpenMRS**, and (b) **best-effort
mirrors** every created appointment into OpenMRS via `POST /appointment` (the
returned `openmrsUuid` is surfaced on the created appointment; failures are
non-fatal). The store is in-memory, so it re-seeds on restart.

### `GET /health`
Liveness — `{"status":"ok"}`.

## Seams left for later tickets

Everything a later ticket needs to touch lives in ONE place, so the planted
bug is a clean, minimal diff.

- **JWT handling — `src/auth.js` (+ `src/config.js`).** All signing/verify
  goes through `signToken` / `verifyToken`. Verify uses an explicit
  algorithm allow-list (`algorithms: [JWT_ALG]`), a real secret, enforced
  `exp` and `iss`. **Ticket 10 (jwt-authbypass)** plants its bug here:
  accept `alg=none`, drop `exp`, or trust a weak/empty secret — one-file
  change. `JWT_SECRET` / `JWT_ALG` are also env-overridable.

- **Linked-profile helper — `src/citizens.js`.**
  `getLinkedPatientUuids(citizenUuid)` resolves the caller's own UUID plus
  every child linked via an OpenMRS `Parent/Child` relationship;
  `canAccessPatient(caller, target)` is the guard built on it.

- **`/patients/{id}/records` routing — `src/routes/patients.js`.** The
  route calls `canAccessPatient()` and returns `403` when not linked.
  **Ticket 09 (BOLA)** plants its bug here by removing/short-circuiting
  that single guard block, so an unlinked patient's records leak. Emit the
  `FLAG{bola-records}` oracle line at that point.

- **Citizen discovery — `src/citizens.js` `discoverCitizens()`.** Resolves
  Legacy IDs -> UUIDs at boot; add/remove seeded ids in `config.js`.

## Notes for ticket 04 (Android login client)

- Base URL / port: `http://<host>:3000` (emulator: `http://10.0.2.2:3000`).
- `POST /login` body: `{"username","password"}`; response carries `token`
  (send as `Authorization: Bearer <token>`) + `citizen`.
- `GET /me/records` returns `{ patient, records:[{id,type,date,observations[]}] }`.
- **CORS** is wide open (`*`) and there is **no TLS** — the app must allow
  cleartext HTTP to this host (`usesCleartextTraffic` / network-security
  config) for the local target.
