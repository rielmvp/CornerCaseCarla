/**
 * Stable front door for the live demo (optional).
 *
 * scripts/demo.sh with TUNNEL=quick opens a Cloudflare quick tunnel, whose
 * hostname is random and changes whenever cloudflared restarts. This Worker has
 * a permanent workers.dev URL and forwards everything to the current tunnel, so
 * viewers keep one link across restarts.
 *
 * Setup, on your own Cloudflare account (free plan is enough):
 *   1. Create a KV namespace, then copy wrangler.toml.example to wrangler.toml
 *      and put its id in.
 *   2. `npx wrangler deploy` from this directory.
 *   3. In demo.sh's environment set CF_ACCOUNT_ID, CF_KV_NAMESPACE_ID and CF_KV_TOKEN (an API
 *      token with Workers KV Storage:Edit only). demo.sh then writes each new
 *      tunnel URL into KV under "tunnel_url" (KV takes up to ~60s to spread).
 *   Optionally set a plain-text variable TUNNEL_URL as a fallback.
 *
 * Basic auth is NOT handled here: the request's Authorization header is passed
 * straight through, so the password check still happens on your own server and
 * the Worker never sees or stores a credential.
 */
export default {
  async fetch(request, env) {
    // The pod writes the live tunnel hostname into KV every time cloudflared
    // starts, so a tunnel restart needs no dashboard visit. TUNNEL_URL stays as
    // a fallback for when KV is empty or the binding is missing.
    let target = "";
    try { target = (await env.STATE?.get("tunnel_url")) || ""; } catch (e) { /* no binding */ }
    target = (target || env.TUNNEL_URL || "").replace(/\/+$/, "");
    if (!target) {
      return new Response("TUNNEL_URL is not set on this Worker.", {
        status: 503, headers: { "content-type": "text/plain" },
      });
    }

    const incoming = new URL(request.url);
    const upstream = new URL(target);
    // The demo starts at live.html, so send bare "/" straight there.
    upstream.pathname = incoming.pathname === "/" ? "/live.html" : incoming.pathname;
    upstream.search = incoming.search;

    // Forward the method, body and headers as-is. Range matters: without it the
    // <video> elements cannot seek. Authorization matters: the origin does auth.
    const headers = new Headers(request.headers);
    headers.set("Host", upstream.host);
    headers.delete("cf-connecting-ip");

    let res;
    try {
      res = await fetch(upstream.toString(), {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        redirect: "manual",
      });
    } catch (e) {
      return new Response(
        "The demo backend is not reachable right now. The tunnel may have " +
        "restarted; TUNNEL_URL probably needs updating.",
        { status: 502, headers: { "content-type": "text/plain" } });
    }

    // Stream the response through untouched so 206 Partial Content, the
    // WWW-Authenticate challenge and the video bytes all survive the hop.
    const out = new Headers(res.headers);
    out.set("Cache-Control", "no-store");
    return new Response(res.body, { status: res.status, headers: out });
  },
};
