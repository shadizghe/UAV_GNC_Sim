/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Three.js ships ESM; Next 15 handles it natively but transpilePackages helps
  // ensure Drei's helpers don't trip the prod build.
  transpilePackages: ["three", "@react-three/fiber", "@react-three/drei"],
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000",
  },
};

export default nextConfig;
