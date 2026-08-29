import crypto from "crypto";

// AES-256-GCM encryption for PII (phone numbers) at rest.
// Format: base64(iv):base64(authTag):base64(ciphertext)
// Must stay byte-for-byte compatible with backend/crypto_utils.py, which
// decrypts phone numbers read out of the same Postgres row by the worker.
const ALGO = "aes-256-gcm";

function getKey(): Buffer {
    const hex = process.env.PHONE_ENCRYPTION_KEY;
    if (!hex || hex.length !== 64) {
        throw new Error(
            "PHONE_ENCRYPTION_KEY must be set to a 64-character hex string (32 bytes). " +
            "Generate one with: openssl rand -hex 32"
        );
    }
    return Buffer.from(hex, "hex");
}

export function encryptPhone(phone: string): string {
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv(ALGO, getKey(), iv);
    const ciphertext = Buffer.concat([cipher.update(phone, "utf8"), cipher.final()]);
    const tag = cipher.getAuthTag();
    return [iv, tag, ciphertext].map((b) => b.toString("base64")).join(":");
}

/**
 * Decrypts a phone number encrypted by encryptPhone. Returns the input
 * unchanged if it doesn't look like ciphertext (e.g. legacy plaintext rows
 * written before encryption was introduced), so existing data doesn't break.
 */
export function decryptPhone(value: string): string {
    const parts = value.split(":");
    if (parts.length !== 3) return value;

    try {
        const [ivB64, tagB64, ctB64] = parts;
        const iv = Buffer.from(ivB64, "base64");
        const tag = Buffer.from(tagB64, "base64");
        const ciphertext = Buffer.from(ctB64, "base64");
        const decipher = crypto.createDecipheriv(ALGO, getKey(), iv);
        decipher.setAuthTag(tag);
        return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
    } catch {
        return value;
    }
}
