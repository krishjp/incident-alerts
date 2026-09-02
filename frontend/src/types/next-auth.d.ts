// Side-effect import (rather than a default import) so this file is treated as
// a module: `declare module` in a non-module file *replaces* next-auth's types
// instead of augmenting them, which breaks every getServerSession call site.
import "next-auth"

declare module "next-auth" {
    interface Session {
        user: {
            id: string
            name?: string | null
            email?: string | null
            image?: string | null
        }
    }
}
