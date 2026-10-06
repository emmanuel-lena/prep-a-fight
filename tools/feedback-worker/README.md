# Feedback relay

The app's **Send feedback** posts `{title, body, version}` here; this Cloudflare Worker (free plan) creates the GitHub
issue with its own token, so no token ships in the installer.

1. GitHub > Settings > Developer settings > Fine-grained tokens: repository `prep-a-fight` only,
   permission **Issues: Read and write**, nothing else.
2. In this folder: `npx wrangler login`, `npx wrangler secret put GITHUB_TOKEN` (paste the token), `npx wrangler deploy`.
3. Give the app the Worker's URL: `gh secret set PAF_FEEDBACK_URL` with `https://prep-a-fight-feedback.<you>.workers.dev`.
   The next release build bakes it into the installer (`paf/feedback_url.txt`).

To stop it: `npx wrangler delete`, or revoke the token. Feedback then falls back to a pre-filled GitHub issue.
