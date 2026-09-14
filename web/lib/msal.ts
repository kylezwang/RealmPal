"use client";
/**
 * Entra External ID (CIAM) sign-in via MSAL, PKCE, no client secret (this
 * is a public SPA client, see docs/DEPLOYMENT_GUIDE.md PRIORITY 3 Step 3).
 *
 * This is entirely separate from the local email+password session system
 * in web/lib/api.ts (AUTH_TOKEN_KEY). The backend already accepts either:
 * api/dependencies.py's get_optional_user() tries Entra JWKS verification
 * first, then falls back to our own HS256 session JWT. So once an Entra
 * access token is stored under the same AUTH_TOKEN_KEY, every existing
 * authHeaders() call site keeps working unmodified.
 *
 * All NEXT_PUBLIC_ENTRA_* values are public identifiers (tenant ID, client
 * ID, API scope), never secrets - a SPA has no client secret to leak. If
 * they are unset, entraConfigured() is false and the "Continue with
 * Microsoft" button falls back to its old "not set up yet" error instead
 * of throwing at import time, so local dev without Entra env vars is
 * unaffected.
 */
import type { Configuration, PublicClientApplication as PublicClientApplicationType } from "@azure/msal-browser";

const TENANT_ID = process.env.NEXT_PUBLIC_ENTRA_TENANT_ID ?? "";
const CLIENT_ID = process.env.NEXT_PUBLIC_ENTRA_WEB_CLIENT_ID ?? "";
const USER_FLOW = process.env.NEXT_PUBLIC_ENTRA_USER_FLOW ?? "sign-up-sign-in";
/** `api://<api-client-id>/access_as_user`, see docs/DEPLOYMENT_GUIDE.md Step 2. */
export const ENTRA_API_SCOPE = process.env.NEXT_PUBLIC_ENTRA_API_SCOPE ?? "";

export function entraConfigured(): boolean {
  return Boolean(TENANT_ID && CLIENT_ID && ENTRA_API_SCOPE);
}

/**
 * CIAM authority shape: https://<tenant>.ciamlogin.com/<tenant>/<user-flow>
 * (not login.microsoftonline.com - that's the workforce-tenant authority
 * and does not know about this external tenant's user flow at all).
 */
function authority(): string {
  return `https://${TENANT_ID}.ciamlogin.com/${TENANT_ID}/${USER_FLOW}`;
}

function redirectUri(): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/auth/callback`;
}

const msalConfig: Configuration = {
  auth: {
    clientId: CLIENT_ID,
    authority: authority(),
    // CIAM tenants: the authority above already is the full path MSAL
    // should trust; without this MSAL tries to validate it against the
    // public Microsoft cloud's list of known authorities and rejects a
    // ciamlogin.com host it doesn't recognize.
    knownAuthorities: [`${TENANT_ID}.ciamlogin.com`],
    redirectUri: "", // set per-instance in getMsalInstance(), needs `window`
  },
  cache: {
    cacheLocation: "localStorage",
  },
};

let instance: PublicClientApplicationType | null = null;
let initPromise: Promise<PublicClientApplicationType> | null = null;

/**
 * Lazy singleton: importing @azure/msal-browser touches `window`, so this
 * must never run at module load time on the server (Next.js SSR/build).
 */
export async function getMsalInstance(): Promise<PublicClientApplicationType> {
  if (instance) return instance;
  if (!initPromise) {
    initPromise = (async () => {
      const { PublicClientApplication } = await import("@azure/msal-browser");
      const pca = new PublicClientApplication({
        ...msalConfig,
        auth: { ...msalConfig.auth, redirectUri: redirectUri() },
      });
      await pca.initialize();
      instance = pca;
      return pca;
    })();
  }
  return initPromise;
}

/** Redirects the browser to Entra's hosted sign-up/sign-in page. Never returns. */
export async function signInWithEntra(): Promise<void> {
  const pca = await getMsalInstance();
  await pca.loginRedirect({ scopes: [ENTRA_API_SCOPE] });
}

/**
 * Call once on /auth/callback after Entra redirects back. Resolves the API
 * access token (the one our backend's JWKS check can verify) on success,
 * or null if this load isn't actually a redirect return (e.g. direct nav).
 */
export async function completeEntraRedirect(): Promise<string | null> {
  const pca = await getMsalInstance();
  const result = await pca.handleRedirectPromise();
  if (!result) return null;
  return result.accessToken || null;
}

/**
 * MSAL keeps its own session separate from AUTH_TOKEN_KEY; call alongside
 * clearAuthToken() on sign-out. A no-op (does not redirect the browser)
 * unless MSAL actually has an active Entra account cached - most users are
 * on local email+password and have never touched Entra at all, and an
 * unconditional logoutRedirect() would otherwise bounce every sign-out
 * through Entra's logout endpoint for no reason.
 */
export async function signOutOfEntra(): Promise<void> {
  if (!entraConfigured()) return;
  const pca = await getMsalInstance();
  const account = pca.getActiveAccount() ?? pca.getAllAccounts()[0];
  if (!account) return;
  await pca.logoutRedirect({ account });
}
