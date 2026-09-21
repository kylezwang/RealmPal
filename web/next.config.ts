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
  // Static export: every fetch already goes straight from the browser to
  // the FastAPI backend (`web/lib/api.ts`'s `API_URL`, including chat
  // streaming at `/chat/stream`), so there's no Next.js server-side work
  // left to justify hybrid/SSR hosting. `output: "export"` is the fully
  // stable Next.js feature (unlike Azure Static Web Apps' hybrid Next.js
  // support, still labeled preview), and removes any risk of the app's
  // most latency-sensitive feature (chat token streaming) running through
  // an unproven serverless layer for zero benefit.
  output: "export",
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
      { protocol: "https", hostname: "static-platform.aghanim.com" },
      { protocol: "https", hostname: "hub.realmofthemadgod.com" },
    ],
    // Next/Image's optimization API needs a live server, which a static
    // export doesn't have; `unoptimized` serves the original remote URL
    // as-is instead (these are small pixel-art wiki icons already sized
    // at the source, no visible difference).
    unoptimized: true,
  },
};

export default nextConfig;
