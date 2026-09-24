// Central config, all env-driven with sensible local defaults.
// Local eval TARGET only — deliberately simple secrets, no TLS.

const {
  PORT = "3000",
  HOST = "0.0.0.0",

  // OpenMRS core (server-to-server, basic auth).
  OPENMRS_BASE_URL = "http://localhost:8080/openmrs/ws/rest/v1",
  OPENMRS_USER = "admin",
  OPENMRS_PASS = "Admin123",

  // ---- JWT ("Singpass"-cosmetic) --------------------------------------
  // Kept in ONE place so ticket 10 (jwt-authbypass) can loosen alg/secret/
  // expiry handling cleanly. For THIS ticket the handling is correct:
  // HS256, a real secret, and a bounded lifetime.
  JWT_SECRET = "dev-myhealthsg-demo-secret-change-me",
  JWT_ALG = "HS256",
  JWT_ISSUER = "myhealthsg-bff",
  JWT_EXPIRES_IN = "1h",

  // Shared demo password for every seeded citizen. Username is the
  // citizen's Legacy ID (MHSG-CIT-0x) or their NRIC-like SSN (S-100000x).
  DEMO_PASSWORD = "Password123",
} = process.env;

// Legacy IDs the BFF discovers (resolves to OpenMRS UUIDs) on startup.
// Children are discovered too so linked-profile lookups can validate them.
export const SEEDED_LEGACY_IDS = [
  "MHSG-CIT-01",
  "MHSG-CIT-02",
  "MHSG-CIT-03",
  "MHSG-CHILD-01",
  "MHSG-CHILD-02",
  "MHSG-CHILD-03",
];

// Who is allowed to log in (adult citizens only). Children are dependents.
export const LOGIN_LEGACY_IDS = [
  "MHSG-CIT-01",
  "MHSG-CIT-02",
  "MHSG-CIT-03",
];

export const config = {
  port: Number(PORT),
  host: HOST,
  openmrs: {
    baseUrl: OPENMRS_BASE_URL.replace(/\/+$/, ""),
    user: OPENMRS_USER,
    pass: OPENMRS_PASS,
  },
  jwt: {
    secret: JWT_SECRET,
    alg: JWT_ALG,
    issuer: JWT_ISSUER,
    expiresIn: JWT_EXPIRES_IN,
  },
  demoPassword: DEMO_PASSWORD,
};
