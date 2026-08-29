import { redirect } from 'next/navigation'

// Entry routing (upgrade plan task 15, compatibility window):
// - The consumer creation workspace lives at /app (still gated behind the
//   Phase 5 compatibility decision; the default entry stays on BrandFlow).
// - /brandflow is the B-end approval workspace, deprecated for C-end use
//   but fully retained for at least one release cycle. Route removal needs
//   separate user authorization.
export default function HomePage() {
  redirect('/brandflow')
}
