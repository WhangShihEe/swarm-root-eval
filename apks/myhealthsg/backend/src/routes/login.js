// POST /login — issue a JWT for a seeded citizen.
// Credentials: username = Legacy ID (MHSG-CIT-0x) OR NRIC-like SSN
// (S-100000x); password = the shared DEMO_PASSWORD (see config/README).

import { Router } from "express";
import { resolveLogin } from "../citizens.js";
import { signToken } from "../auth.js";
import { config } from "../config.js";

export const loginRouter = Router();

loginRouter.post("/login", (req, res) => {
  const { username, password } = req.body || {};

  if (!username || !password) {
    return res.status(400).json({ error: "username_and_password_required" });
  }
  if (password !== config.demoPassword) {
    return res.status(401).json({ error: "invalid_credentials" });
  }

  const citizen = resolveLogin(username);
  if (!citizen) {
    return res.status(401).json({ error: "invalid_credentials" });
  }

  const token = signToken(citizen);
  return res.json({
    token,
    tokenType: "Bearer",
    citizen: {
      legacyId: citizen.legacyId,
      uuid: citizen.uuid,
      name: citizen.name,
    },
  });
});
