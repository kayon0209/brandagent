/** @type {import('next').NextConfig} */
const nextConfig = {
  // Next 15 renamed experimental.serverComponentsExternalPackages to
  // serverExternalPackages; the old key was silently ignored (startup warning)
  serverExternalPackages: ['@anthropic-ai/sdk'],

}

module.exports = nextConfig
