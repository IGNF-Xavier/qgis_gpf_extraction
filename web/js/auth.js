// Authentification : jeton Bearer collé à la main (fonctionne dès aujourd'hui) et
// OAuth2 Authorization Code + PKCE (inactif tant qu'aucun client dédié n'est configuré,
// cf. `config.js`).

import { OIDC } from "./config.js";

const SESSION_KEY = "gpf_web_token";

const b64urlToBytes = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
};

export function base64url(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Lit les revendications d'un JWT (sans vérifier la signature : sert uniquement à
// afficher l'expiration, le serveur reste seul juge de la validité).
export function decodeJwt(token) {
  try {
    const [, payload] = String(token).split(".");
    return JSON.parse(new TextDecoder().decode(b64urlToBytes(payload)));
  } catch {
    return null;
  }
}

export class AuthState {
  constructor(storage = globalThis.sessionStorage) {
    this._token = "";
    this._storage = storage;
    this.onChange = () => {};
    try {
      const saved = storage && storage.getItem(SESSION_KEY);
      if (saved) this._token = saved;
    } catch {
      /* sessionStorage indisponible : jeton en mémoire seulement */
    }
  }

  get token() {
    return this._token;
  }

  get authenticated() {
    return Boolean(this._token) && !this.isExpired;
  }

  get claims() {
    return this._token ? decodeJwt(this._token) : null;
  }

  // Secondes avant expiration (null si inconnue ; négatif si expiré).
  get secondsLeft() {
    const exp = this.claims && this.claims.exp;
    return typeof exp === "number" ? Math.round(exp - Date.now() / 1000) : null;
  }

  get isExpired() {
    const left = this.secondsLeft;
    return left !== null && left <= 0;
  }

  // `remember` : conserve le jeton pour cet onglet seulement (sessionStorage, jamais localStorage).
  setToken(raw, remember = false) {
    this._token = String(raw || "").trim().replace(/^Bearer\s+/i, "");
    try {
      if (remember && this._token) this._storage.setItem(SESSION_KEY, this._token);
      else this._storage.removeItem(SESSION_KEY);
    } catch {
      /* ignoré */
    }
    this.onChange();
  }

  clear() {
    this.setToken("");
  }
}

// ---------------------------------------------------------------- PKCE (RFC 7636)
export function generateVerifier() {
  const bytes = new Uint8Array(48);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

export async function challengeS256(verifier) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

export const oidcConfigured = () => Boolean(OIDC.clientId);
const redirectUri = () => location.origin + location.pathname;

export async function startLogin() {
  const verifier = generateVerifier();
  const state = generateVerifier().slice(0, 24);
  sessionStorage.setItem("gpf_web_pkce", JSON.stringify({ verifier, state }));
  const params = new URLSearchParams({
    client_id: OIDC.clientId,
    response_type: "code",
    redirect_uri: redirectUri(),
    scope: OIDC.scope,
    state,
    code_challenge: await challengeS256(verifier),
    code_challenge_method: "S256",
  });
  location.assign(`${OIDC.authorizeUrl}?${params}`);
}

// À appeler au chargement : termine l'échange si la page revient de l'authentification.
// Renvoie le jeton d'accès, ou null s'il n'y a rien à faire.
export async function handleRedirect() {
  if (!oidcConfigured()) return null;
  const query = new URLSearchParams(location.search);
  const code = query.get("code");
  if (!code) return null;
  const saved = JSON.parse(sessionStorage.getItem("gpf_web_pkce") || "null");
  sessionStorage.removeItem("gpf_web_pkce");
  history.replaceState(null, "", redirectUri());
  if (!saved || saved.state !== query.get("state")) throw new Error("Réponse d'authentification inattendue (state).");
  const response = await fetch(OIDC.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: OIDC.clientId,
      code,
      redirect_uri: redirectUri(),
      code_verifier: saved.verifier,
    }),
  });
  if (!response.ok) throw new Error(`Échange du code refusé (HTTP ${response.status}).`);
  return (await response.json()).access_token || null;
}
