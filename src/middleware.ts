import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'
import { NextResponse } from 'next/server'

/**
 * /app is the consumer workspace: it renders user data server-side and
 * must never show a logged-out shell (audit finding: bare clerkMiddleware
 * protects nothing by default). Unauthenticated visitors are redirected
 * to Clerk's sign-in with a return URL.
 */

// Both the public URL (/app) and the on-disk route (/workspace) must be
// guarded. The route segment cannot be named `app` (Next 15.5.x skips it
// during route discovery), so /app is a rewrite onto /workspace — guarding
// only /app would leave /workspace as an auth bypass.
const isConsumerAppRoute = createRouteMatcher(['/app(.*)', '/workspace(.*)'])

export default clerkMiddleware(async (auth, request) => {
  if (isConsumerAppRoute(request)) {
    await auth.protect()
    // Next 15.5 does not discover a literal `app` route segment below the
    // App Router's `src/app` root. Keep `/app` as the public, documented URL
    // while serving the real `/workspace` route internally; query strings
    // stay on the cloned URL unchanged.
    const { pathname } = request.nextUrl
    if (pathname === '/app' || pathname.startsWith('/app/')) {
      const destination = request.nextUrl.clone()
      destination.pathname = pathname.replace(/^\/app(?=\/|$)/, '/workspace')
      return NextResponse.rewrite(destination)
    }
  }
  return NextResponse.next()
})

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon\\.ico).*)'],
}
