import content from './content.json'
import '@/styles/consumer-tokens.css'
import '@/styles/landing.css'

export function BrandLanding({ signedIn = false }: { signedIn?: boolean }) {
  // Only checked-in markup and fixed strings are rendered; no user HTML.
  const html = content.html
    .replaceAll('__ENTRY_HREF__', '/app')
    .replaceAll('__ENTRY_LABEL__', signedIn ? '继续写作' : '开始写第一句')
    .replaceAll('__SURFACE_NOTE__', '当前是本地应用入口；登录后进入自己的工作区。')
  return <div className="v42-landing" dangerouslySetInnerHTML={{ __html: html }} />
}
