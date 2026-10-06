// prep-a-fight relay (Cloudflare Worker, free plan). Deploy: see README.md next to this file.
//
// POST /                 the app's "Send feedback": {title, body, version} -> a GitHub issue of the repository.
// GET  /packs/<key>      a shared prep pack (issue #6), key = "<class>-<spec>/<encounter>-<difficulty>".
// PUT  /packs/<key>      publish a prep pack: checked, then stored (the previous one is kept as <key>:prev).
//
// Secrets / vars: GITHUB_TOKEN (fine-grained, this repository only, Issues: read and write), REPO ("owner/name").
// KV: PACKS.

const MAX_BODY = 60000;
const MAX_PACK = 3_000_000;
const KEY_RE = /^[a-z]+-[a-z]+\/\d+-\d+$/;

function fromApp(request) {
  return (request.headers.get("User-Agent") || "").startsWith("prep-a-fight/");
}

async function feedback(request, env) {
  let data;
  try {
    data = await request.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }
  const title = String(data.title || "").trim().slice(0, 120);
  const body = String(data.body || "").slice(0, MAX_BODY);
  if (!title || !body) return new Response("empty", { status: 400 });
  const res = await fetch(`https://api.github.com/repos/${env.REPO}/issues`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${String(env.GITHUB_TOKEN || "").trim()}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "prep-a-fight-feedback-relay",
    },
    body: JSON.stringify({
      title: `[app] ${title}`,
      body: `${body}\n\n_Sent from the app (prep-a-fight ${String(data.version || "?").slice(0, 20)})._`,
      labels: ["beta", "from-app"],
    }),
  });
  if (!res.ok) return new Response(`github: ${res.status}`, { status: 502 });
  const issue = await res.json();
  return Response.json({ url: issue.html_url, number: issue.number });
}

// Why a pack is refused, or "" when it can be stored over `old` (the current one, or null).
export function checkPack(key, text, pack, old) {
  if (text.length > MAX_PACK) return "too big";
  if (/"report"\s*:/.test(text)) return "packs never carry report codes";
  if (pack.version !== 1) return "unknown pack version";
  const own = `${pack.class_name}-${pack.spec}/${pack.encounter_id}-${pack.difficulty}`.toLowerCase();
  if (own !== key) return "the pack does not match its key";
  if (!(pack.kills >= 20)) return "fewer than 20 kills";
  const dur = pack.fight && pack.fight.duration;
  if (!(dur >= 60 && dur <= 1500)) return "implausible fight duration";
  const val = pack.validation ? pack.validation[1] : null;
  if (val === null || !(val >= 0.75 && val <= 1.25)) return "missing or implausible validation";
  const made = Date.parse(pack.created);
  if (!(made <= Date.now() + 300_000)) return "bad creation date";
  if (old) {
    const oldMade = Date.parse(old.created);
    if (!(made > oldMade)) return "not newer than the current pack";
    const oldVal = old.validation ? old.validation[1] : null;
    const recent = Date.now() - oldMade < 30 * 3600_000; // an old pack can always be replaced
    if (recent && oldVal !== null && Math.abs(val - 1) > Math.abs(oldVal - 1) + 0.03) {
      return "worse validation than the current pack";
    }
    if (recent && Math.abs(dur - old.fight.duration) > 0.3 * old.fight.duration) return "fight duration drifts too much";
  }
  return "";
}

async function packs(request, env, key) {
  if (!KEY_RE.test(key)) return new Response("bad key", { status: 400 });
  if (request.method === "GET") {
    const text = await env.PACKS.get(key);
    return text ? new Response(text, { headers: { "Content-Type": "application/json" } })
                : new Response("no pack", { status: 404 });
  }
  if (request.method !== "PUT") return new Response("method", { status: 405 });
  const text = await request.text();
  let pack;
  try {
    pack = JSON.parse(text);
  } catch {
    return new Response("bad json", { status: 400 });
  }
  const current = await env.PACKS.get(key);
  const old = current ? JSON.parse(current) : null;
  const why = checkPack(key, text, pack, old);
  if (why) return new Response(why, { status: 409 });
  if (current) await env.PACKS.put(`${key}:prev`, current);
  await env.PACKS.put(key, text);
  return Response.json({ stored: key, created: pack.created });
}

// Shared prep sheets: a raid lead publishes a sheet, the guild opens the link in a browser. The page may only run
// its own inline scripts and Wowhead's tooltips, load fonts and images, and never post anything anywhere.
const MAX_SHEET = 3_000_000;
const SHARE_DAYS = 30;
const SHEET_CSP = [
  "default-src 'none'", "script-src 'unsafe-inline' https://wow.zamimg.com https://nether.wowhead.com",
  "style-src 'unsafe-inline' https://fonts.googleapis.com https://wow.zamimg.com", "font-src https://fonts.gstatic.com",
  "img-src https: data:", "connect-src https://nether.wowhead.com", "form-action 'none'", "base-uri 'none'",
  "frame-ancestors 'none'",
].join("; ");

function newId(n) {
  const abc = "abcdefghijkmnpqrstuvwxyz23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return Array.from(bytes, (b) => abc[b % abc.length]).join("");
}

async function share(request, env, url) {
  const id = url.pathname.slice("/s/".length);
  if (request.method === "GET") {
    if (!/^[a-z0-9]{10}$/.test(id)) return new Response("not found", { status: 404 });
    const html = await env.PACKS.get(`share:${id}`);
    if (!html) return new Response("This prep sheet is no longer shared.", { status: 404 });
    return new Response(html, {
      headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": SHEET_CSP,
                 "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Cache-Control": "public, max-age=300" },
    });
  }
  if (!fromApp(request)) return new Response("forbidden", { status: 403 });
  if (request.method === "POST" && url.pathname === "/s") {
    const html = await request.text();
    if (!html || html.length > MAX_SHEET || !html.includes("prep-a-fight")) return new Response("not a prep sheet", { status: 400 });
    const sid = newId(10), token = newId(24);
    await env.PACKS.put(`share:${sid}`, html, { expirationTtl: SHARE_DAYS * 86400 });
    await env.PACKS.put(`share-token:${sid}`, token, { expirationTtl: SHARE_DAYS * 86400 });
    return Response.json({ id: sid, url: `${url.origin}/s/${sid}`, token, days: SHARE_DAYS });
  }
  if (request.method === "DELETE") {
    const token = await env.PACKS.get(`share-token:${id}`);
    if (!token || token !== request.headers.get("X-Share-Token")) return new Response("forbidden", { status: 403 });
    await env.PACKS.delete(`share:${id}`);
    await env.PACKS.delete(`share-token:${id}`);
    return new Response(null, { status: 204 });
  }
  return new Response("method", { status: 405 });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return new Response("prep-a-fight relay");
    if (url.pathname === "/s" || url.pathname.startsWith("/s/")) return share(request, env, url);
    if (!fromApp(request)) return new Response("forbidden", { status: 403 });
    if (url.pathname.startsWith("/packs/")) return packs(request, env, url.pathname.slice("/packs/".length));
    if (request.method === "POST" && url.pathname === "/") return feedback(request, env);
    return new Response("not found", { status: 404 });
  },
};
