import type { NextConfig } from "next";
import path from "path";

// Next.js's workspace-root inference picks C:\Projects because a stray
// package-lock.json (unrelated Cursor tooling) lives above this repo, which
// breaks CSS @import resolution for Tailwind. Pin the root explicitly.
//
// IMPORTANT: this must NOT equal the web/ directory itself. Next.js 16
// Turbopack has a bug where turbopack.root === the app directory makes CSS
// @import resolution start one level too high (path.relative(root, dir)
// returns "" and gets coerced to "." internally, which Turbopack's Rust side
// then resolves from dirname(root) instead of the file's own directory).
// https://github.com/vercel/next.js/issues/90307
// Pointing root at the repo root (one level above web/) avoids the bug while
// still pinning inference so the "multiple lockfiles" warning goes away.
const repoRoot = path.resolve(__dirname, "..");

const nextConfig: NextConfig = {
  outputFileTracingRoot: repoRoot,
  turbopack: {
    root: repoRoot,
  },
  images: {
    // Allow sprite images from Realmeye and UmiEnjoyers
    remotePatterns: [
      { protocol: "https", hostname: "www.realmeye.com" },
      { protocol: "https", hostname: "realmeye.com" },
      { protocol: "https", hostname: "www.umienjoyers.com" },
      { protocol: "https", hostname: "umienjoyers.com" },
    ],
    // Sprites are pixel art | disable default blur/optimization
    unoptimized: false,
  },
  // Proxy /api/sprite to backend sprite resolver
  async rewrites() {
    const apiUrl = process.env.API_URL ?? "http://localhost:8001";
    return [
      {
        source: "/api/sprite",
        destination: `${apiUrl}/sprite`,
      },
    ];
  },
};

export default nextConfig;
