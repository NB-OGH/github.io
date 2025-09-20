# Nima — GitHub Pages landing site (MVP)

This repository contains a lightweight static site for **nimaoghanian.com**.

## Quick start
1. Create a repo named `<your-username>.github.io` on GitHub.
2. Upload these files to the root of that repo:
   - `index.html`
   - `styles.css`
   - `CNAME` (contains your custom domain: `nimaoghanian.com`)
3. In the repo: **Settings → Pages → Source: Deploy from a branch**; pick `main` and `/ (root)`.
4. In the same **Pages** section, under **Custom domain**, enter `nimaoghanian.com` and click **Save**. This will also create a `CNAME` file if you didn't upload it already.
5. At your DNS provider, create the GitHub Pages records for the **apex** domain (example below). It may take time to propagate.
6. When the site is reachable, enable **Enforce HTTPS** in **Settings → Pages**.

### DNS records for apex (example.com)
A records (IPv4) → point `@` to:
- 185.199.108.153
- 185.199.109.153
- 185.199.110.153
- 185.199.111.153

AAAA records (IPv6) → point `@` to:
- 2606:50c0:8000::153
- 2606:50c0:8001::153
- 2606:50c0:8002::153
- 2606:50c0:8003::153

Optionally, create a `CNAME` for `www` pointing to `<your-username>.github.io`.

> Tip: Some DNS providers support `ALIAS`/`ANAME` for apex domains. You can point `@` to `<your-username>.github.io` with a single record if supported.

## Customize
- Edit text in `index.html`.
- Adjust colors/spacing in `styles.css`.
- Replace the favicon by changing the inline SVG in the `<link rel="icon">` tag, or add a `favicon.ico` in the root.

## Notes
- If you later migrate to WordPress, you can keep the same domain and retire this repo.
- To add more pages, create new `.html` files and link them from the nav.
