// Fails fast on missing/weak required configuration instead of letting bad
// config surface later as a confusing runtime error (e.g. a decrypt failure
// deep in an API route, or silent auth cookie issues from a weak secret).
const REQUIRED_KEYS = [
    "DATABASE_URL",
    "NEXTAUTH_SECRET",
    "NEXTAUTH_URL",
    "PHONE_ENCRYPTION_KEY",
] as const;

const KNOWN_WEAK_SECRETS = new Set([
    "super-secret-key",
    "chp-app-secret-1234",
    "changeme",
    "secret",
]);

let validated = false;

export function assertValidEnv() {
    if (validated) return;

    const missing = REQUIRED_KEYS.filter((key) => !process.env[key]);
    if (missing.length > 0) {
        throw new Error(`Missing required environment variables: ${missing.join(", ")}`);
    }

    const secret = process.env.NEXTAUTH_SECRET!;
    if (secret.length < 32 || KNOWN_WEAK_SECRETS.has(secret)) {
        throw new Error(
            "NEXTAUTH_SECRET is missing or too weak for production use (need >=32 chars, not a known placeholder). " +
            "Generate one with: openssl rand -hex 32"
        );
    }

    const key = process.env.PHONE_ENCRYPTION_KEY!;
    if (!/^[0-9a-f]{64}$/i.test(key)) {
        throw new Error(
            "PHONE_ENCRYPTION_KEY must be a 64-character hex string (32 bytes). " +
            "Generate one with: openssl rand -hex 32 (must match the backend's PHONE_ENCRYPTION_KEY exactly)."
        );
    }

    validated = true;
}
