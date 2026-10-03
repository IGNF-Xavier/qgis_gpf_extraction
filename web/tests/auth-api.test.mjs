import test from "node:test";
import assert from "node:assert/strict";
import { AuthState, base64url, challengeS256, decodeJwt, generateVerifier } from "../js/auth.js";
import { ApiError, ExtractionApi, describeApiError } from "../js/api.js";

const memoryStorage = () => {
  const data = new Map();
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: (k) => data.delete(k) };
};

const jwt = (claims) => `x.${base64url(new TextEncoder().encode(JSON.stringify(claims)))}.y`;

test("PKCE : vecteur de test de la RFC 7636 (annexe B)", async () => {
  assert.equal(
    await challengeS256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
  );
  const verifier = generateVerifier();
  assert.match(verifier, /^[A-Za-z0-9_-]{43,128}$/);
});

test("jeton : préfixe Bearer retiré, expiration lue sans vérifier la signature", () => {
  const auth = new AuthState(memoryStorage());
  assert.equal(auth.authenticated, false);
  const future = Math.floor(Date.now() / 1000) + 600;
  auth.setToken(`Bearer ${jwt({ exp: future })}`);
  assert.equal(auth.authenticated, true);
  assert.ok(auth.secondsLeft > 500 && auth.secondsLeft <= 600);
  auth.setToken(jwt({ exp: Math.floor(Date.now() / 1000) - 5 }));
  assert.equal(auth.isExpired, true);
  assert.equal(auth.authenticated, false);
  assert.equal(decodeJwt("pas-un-jwt"), null);
});

test("jeton : mémorisé en sessionStorage seulement sur demande, jamais autrement", () => {
  const storage = memoryStorage();
  const auth = new AuthState(storage);
  auth.setToken("abc", false);
  assert.equal(storage.getItem("gpf_web_token"), null);
  auth.setToken("abc", true);
  assert.equal(storage.getItem("gpf_web_token"), "abc");
  assert.equal(new AuthState(storage).token, "abc");
  auth.clear();
  assert.equal(storage.getItem("gpf_web_token"), null);
});

const response = (status, body) => ({ ok: status < 400, status, text: async () => (typeof body === "string" ? body : JSON.stringify(body)), json: async () => body });

test("API : en-tête Authorization seulement quand un jeton existe, jamais pour les téléchargements", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return response(200, { processes: [{ id: "p", title: "P" }] }); };
  let token = "";
  const api = new ExtractionApi({ getToken: () => token, fetchImpl });
  await api.listProcesses();
  assert.equal(calls[0].init.headers.Authorization, undefined);
  token = "secret";
  await api.listProcesses();
  assert.equal(calls[1].init.headers.Authorization, "Bearer secret");
  // Téléchargement (flux Atom des résultats) : jamais d'en-tête d'autorisation, même avec un jeton.
  const feedCalls = [];
  const feedApi = new ExtractionApi({
    getToken: () => "secret",
    fetchImpl: async (url, init) => { feedCalls.push({ url, init }); return response(200, "<feed/>"); },
  });
  await feedApi.resolveDownloadFiles("https://h/data");
  assert.equal(feedCalls[0].init.headers.Authorization, undefined);
  assert.equal(feedCalls[0].init.headers.Accept, "application/atom+xml");
});

test("ApiError : rapport copiable (requête + réponse), sans jeton", async () => {
  const api = new ExtractionApi({ getToken: () => "secret", fetchImpl: async () => response(400, { title: "Requête invalide" }) });
  await assert.rejects(
    () => api.execute("pid", { inputs: { a: 1 } }),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 400);
      const report = error.report();
      assert.match(report, /POST .*\/processes\/pid\/execution/);
      assert.match(report, /"a": 1/);
      assert.match(report, /Requête invalide/);
      assert.doesNotMatch(report, /secret/);
      return true;
    },
  );
});

test("erreur réseau/CORS : ApiError de statut 0", async () => {
  const api = new ExtractionApi({ fetchImpl: async () => { throw new TypeError("Failed to fetch"); } });
  await assert.rejects(() => api.getJob("j"), (e) => e instanceof ApiError && e.status === 0);
});

test("messages d'erreur : 401, 429, piste 500 avec fusion", () => {
  assert.match(describeApiError(new ApiError("GET", "u", 401, "")), /expiré/);
  assert.match(describeApiError(new ApiError("POST", "u", 429, "")), /Un seul job/);
  assert.match(describeApiError(new ApiError("POST", "u", 500, ""), { merge: true, tables: 59 }), /fusion/);
  assert.doesNotMatch(describeApiError(new ApiError("POST", "u", 500, ""), { merge: false, tables: 59 }), /fusion/);
});
