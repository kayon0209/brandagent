import { SignUp } from '@clerk/nextjs'

/**
 * Clerk App Router sign-up page (P0 fix companion).
 *
 * New C-end users need a working registration surface; Clerk's hosted
 * pages link here from the sign-in page's sign-up toggle. Same contract
 * as sign-in: path routing + back to /app.
 */

export default function SignUpPage() {
  return <SignUp path="/sign-up" routing="path" fallbackRedirectUrl="/app" />
}
