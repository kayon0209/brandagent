import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'
import { NextResponse } from 'next/server'

/**
 * /app is the consumer workspace: it renders user data server-side and
 * must never show a logged-out shell (audit finding: bare clerkMiddleware
 * protects nothing by default). Unauthenticated visitors are redirected
 * to Clerk's sign-in with a return URL.
 */

const isConsumerAppRoute = createRouteMatcher(['/app(.*)'])

export default clerkMiddleware(async (auth, request) => {
  if (isConsumerAppRoute(request)) {
    await auth.protect()
  }
  return NextResponse.next()
})

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon\\.ico).*)'],
}
