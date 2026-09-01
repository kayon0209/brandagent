import { SignIn } from '@clerk/nextjs'

/**
 * Clerk App Router sign-in page (P0 fix).
 *
 * `src/middleware.ts` calls auth.protect() on /app(.*); Clerk redirects
 * anonymous visitors here with a redirect_url back to the workspace.
 * Without this route the redirect landed on a Next 404 and C-end users
 * (and the real E2E journey) could never sign in.
 */

export default function SignInPage() {
  return <SignIn path="/sign-in" routing="path" fallbackRedirectUrl="/app" />
}
