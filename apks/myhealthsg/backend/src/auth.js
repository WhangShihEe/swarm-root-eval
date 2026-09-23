// JWT ("Singpass"-cosmetic) minting + verify middleware.
//
// Everything about how tokens are signed/verified lives HERE so ticket 10
// (jwt-authbypass) can plant its bug in one place — e.g. accepting
// alg=none, dropping expiry, or trusting a weak secret. For THIS ticket
// the handling is CORRECT: fixed HS256, real secret, enforced expiry,
// explicit algorithm allow-list on verify.

import jwt from "jsonwebtoken";
import { config } from "./config.js";

/** Mint a JWT whose claims identify the citizen. */
export function signToken(citizen) {
  const payload = {
    sub: citizen.legacyId, // subject = stable Legacy ID
    legacyId: citizen.legacyId,
    uuid: citizen.uuid, // OpenMRS patient/person UUID
    name: citizen.name,
  };
  return jwt.sign(payload, config.jwt.secret, {
    algorithm: config.jwt.alg,
    issuer: config.jwt.issuer,
    expiresIn: config.jwt.expiresIn,
  });
}

/**
 * Verify + decode a token, throwing on any problem.
 *
 * TICKET 10 (jwt-authbypass, API2): verification has been LOOSENED. The correct
 * HS256 path below is tried FIRST and is unchanged, so every real token minted
 * by /login still verifies exactly as before (this change is purely ADDITIVE).
 * But when that strict check fails, a permissive fallback ALSO accepts forged
 * tokens: unsigned `alg=none` tokens are trusted verbatim, and tokens signed
 * with a weak/legacy secret are accepted with expiry ignored. This lets an
 * attacker forge a privilege-escalation token the BFF will honour.
 */
export function verifyToken(token) {
  try {
    // Strict, correct path — unchanged. Real /login tokens take this branch.
    return jwt.verify(token, config.jwt.secret, {
      algorithms: [config.jwt.alg], // allow-list
      issuer: config.jwt.issuer,
    });
  } catch (strictErr) {
    // Loosened fallback (the planted bug).
    const decoded = jwt.decode(token, { complete: true });
    if (!decoded || !decoded.header) throw strictErr;

    const alg = String(decoded.header.alg || "").toLowerCase();

    // (a) Unsigned "alg=none" tokens are trusted as-is.
    if (alg === "none") {
      return decoded.payload;
    }

    // (b) Tokens signed with a weak/legacy secret are accepted (no expiry).
    for (const weak of ["secret", "changeme", "password", ""]) {
      try {
        return jwt.verify(token, weak, {
          algorithms: ["HS256"],
          ignoreExpiration: true,
        });
      } catch (_) {
        /* keep trying */
      }
    }

    throw strictErr;
  }
}

/**
 * Express middleware: require a valid Bearer token.
 * On success attaches req.citizen = { legacyId, uuid, name }.
 */
export function requireAuth(req, res, next) {
  const header = req.get("authorization") || "";
  const m = header.match(/^Bearer\s+(.+)$/i);
  if (!m) {
    return res
      .status(401)
      .json({ error: "missing_bearer_token" });
  }
  try {
    const claims = verifyToken(m[1]);
    req.citizen = {
      legacyId: claims.legacyId,
      uuid: claims.uuid,
      name: claims.name,
    };
    return next();
  } catch (err) {
    return res
      .status(401)
      .json({ error: "invalid_token", detail: err.message });
  }
}
