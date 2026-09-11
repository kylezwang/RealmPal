/**
 * Next.js route handler | proxies chat stream from FastAPI backend.
 * Passes the Authorization header through if present (paid users).
 */
import { NextRequest } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const authHeader = req.headers.get("Authorization");

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (authHeader) {
    headers["Authorization"] = authHeader;
  }

  const upstream = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers,
    body,
    // @ts-expect-error | Node fetch duplex required for streaming
    duplex: "half",
  });

  // Pass through 402 paywall response
  if (upstream.status === 402) {
    const data = await upstream.json();
    return Response.json(data, { status: 402 });
  }

  if (!upstream.ok) {
    return Response.json({ error: "Upstream error" }, { status: upstream.status });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
