import { redirect } from 'next/navigation'

// Entry routing (upgrade plan task 15, compatibility window):
// - The consumer creation workspace at /app is the product's front door:
//   personal creators land on the two-field creation path, not the
//   enterprise eight-section brief.
// - Rollback switch: set NEXT_PUBLIC_DEFAULT_ENTRY=brandflow to send the
//   default entry back to the enterprise workspace (the compatibility
//   window keeps every /brandflow route fully working).
// - /brandflow is the B-end approval workspace, deprecated for C-end use
//   but fully retained for at least one release cycle. Route removal needs
//   separate user authorization.
export default function HomePage() {
  const entry = process.env.NEXT_PUBLIC_DEFAULT_ENTRY === 'brandflow' ? '/brandflow' : '/app'
  redirect(entry)
}
