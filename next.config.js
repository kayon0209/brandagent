/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    serverComponentsExternalPackages: ['@anthropic-ai/sdk'],
  },
  async rewrites() {
    const agentApi = process.env.BRANDFLOW_AGENT_INTERNAL_URL || 'http://127.0.0.1:8000'
    return [{ source: '/brandflow-api/:path*', destination: `${agentApi}/:path*` }]
  },
}

module.exports = nextConfig
