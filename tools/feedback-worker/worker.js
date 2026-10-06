// Relay for the app's "Send feedback": turns a POST {title, body, version} into a GitHub issue of the repository.
// The GitHub token stays here (a Worker secret), never in the app. Deploy: see README.md next to this file.
//
// Secrets / vars: GITHUB_TOKEN (fine-grained, this repository only, Issues: read and write), REPO ("owner/name").

const MAX_BODY = 60000;

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("prep-a-fight feedback relay", { status: 200 });
    if (!(request.headers.get("User-Agent") || "").startsWith("prep-a-fight/")) {
      return new Response("forbidden", { status: 403 });
    }
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
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
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
  },
};
