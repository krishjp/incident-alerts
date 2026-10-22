// Account field rules shared by the auth forms (inline feedback) and the
// server (enforcement), so the two can't drift apart. Each validator returns a
// user-facing message, or null when the value is acceptable.

export const MIN_PASSWORD_LENGTH = 8;
// bcrypt silently ignores everything past 72 bytes, so a longer password would
// "work" while only its prefix is actually checked.
export const MAX_PASSWORD_BYTES = 72;
export const MAX_NAME_LENGTH = 100;
const MAX_EMAIL_LENGTH = 254;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function validateEmail(email: unknown): string | null {
    if (typeof email !== "string" || email.trim().length === 0) return "Email is required.";
    if (email.trim().length > MAX_EMAIL_LENGTH || !EMAIL_PATTERN.test(email.trim())) {
        return "Enter a valid email address.";
    }
    return null;
}

/** Sign-in only checks shape; strength rules apply when the password is set. */
export function validateLoginPassword(password: unknown): string | null {
    if (typeof password !== "string" || password.length === 0) return "Password is required.";
    if (new TextEncoder().encode(password).length > MAX_PASSWORD_BYTES) {
        return "Password is too long.";
    }
    return null;
}

export function validateNewPassword(password: unknown): string | null {
    const basic = validateLoginPassword(password);
    if (basic) return basic;
    const value = password as string;
    if (value.length < MIN_PASSWORD_LENGTH) {
        return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    }
    if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
        return "Password must include at least one letter and one number.";
    }
    return null;
}

export function validateName(name: unknown): string | null {
    if (typeof name !== "string" || name.trim().length === 0) return "Name is required.";
    if (name.trim().length > MAX_NAME_LENGTH) {
        return `Name must be under ${MAX_NAME_LENGTH} characters.`;
    }
    return null;
}

/** Error code the credentials provider throws when sign-in is rate limited. */
export const LOGIN_RATE_LIMITED = "RateLimited";
