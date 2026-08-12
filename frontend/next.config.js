/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    return [
      {
        // Serve compact GIS payload from the local Next route (~9 MB) instead
        // of proxying the pretty-printed backend file (~30 MB).
        source: '/api/((?!dev/gis/complete-result).*)',
        destination: `${apiUrl}/api/$1`,
      },
    ]
  },
}

module.exports = nextConfig
