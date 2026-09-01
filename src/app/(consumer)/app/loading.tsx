/**
 * Consumer route-group loading shell: navigation between /app pages shows
 * a quiet placeholder instead of a layout flash.
 */

export default function ConsumerLoading() {
  return (
    <div className="consumer-app-root" style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <p style={{ color: '#6b6560', fontSize: 14 }}>正在打开工作台…</p>
    </div>
  )
}
