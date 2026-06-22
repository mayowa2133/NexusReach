# SearXNG on an Oracle Cloud "Always Free" VM

Run SearXNG for free, always-on, on Oracle Cloud's Always-Free tier, locked to
your backend with HTTPS + Basic Auth. ~30 minutes. Nothing here costs money.

**What you'll end up with**

```
NexusReach backend (Railway)
   └── https://nexus:<password>@<your-domain>          (Basic Auth over HTTPS)
          └── Caddy on the Oracle VM (TLS + auth, ports 80/443)
                 └── SearXNG container (port 8080, internal only)
```

The backend already sends Basic Auth from the URL (httpx reads the `user:pass@`
part), so **no app code change is needed** — you only set one env var.

---

## 0. Prerequisites

- An Oracle Cloud account (free; requires a card for identity verification but
  Always-Free resources are never charged). https://www.oracle.com/cloud/free/
- A domain pointing at the VM. A **free DuckDNS subdomain** works:
  https://www.duckdns.org → sign in → create e.g. `nexusreach.duckdns.org` and
  note your DuckDNS **token**. (Let's Encrypt won't issue a cert for a raw IP, so
  a hostname is required.)

---

## 1. Create the Always-Free VM

1. Oracle Cloud console → **Compute → Instances → Create instance**.
2. **Image:** Canonical Ubuntu 22.04.
3. **Shape:** *Change shape → Ampere → `VM.Standard.A1.Flex`*, set **1 OCPU / 6 GB**
   (well within the Always-Free 4 OCPU / 24 GB ARM allowance; SearXNG is light).
4. **SSH keys:** upload your public key (or let it generate one and download it).
5. **Create.** When it's running, copy the **public IP**.

> ⚠️ **ARM capacity errors are common.** If you get "Out of host capacity," try a
> different Availability Domain, retry later, or temporarily use the always-free
> AMD shape `VM.Standard.E2.1.Micro` (1 GB RAM — add a 2 GB swapfile; works but
> tighter). The A1 ARM shape is preferred.

---

## 2. Open the firewall (two layers)

Oracle has **both** a cloud firewall and a host firewall — you must open both.

**a) VCN security list** (cloud): Networking → your VCN → the public subnet →
its Security List → **Add Ingress Rules**, source `0.0.0.0/0`, for **TCP 80** and
**TCP 443**. (Access is locked by Basic Auth, not IP, because Railway egress IPs
aren't static.)

**b) Host firewall** (Ubuntu on Oracle ships with restrictive iptables that drop
everything but SSH). SSH in (`ssh ubuntu@<public-ip>`) and run:

```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo apt-get update && sudo apt-get install -y netfilter-persistent iptables-persistent
sudo netfilter-persistent save
```

---

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker     # or log out/in so your user can run docker without sudo
```

---

## 4. Point your domain at the VM

In DuckDNS, set your subdomain's IP to the VM's public IP (dashboard field, or):

```bash
curl "https://www.duckdns.org/update?domains=YOURNAME&token=YOUR_DUCKDNS_TOKEN&ip=<VM_PUBLIC_IP>"
```

Confirm it resolves: `dig +short YOURNAME.duckdns.org` → your VM IP.

---

## 5. Deploy SearXNG + Caddy

From your laptop, copy the committed config to the VM (this folder plus the
shared `settings.yml` one level up):

```bash
scp -r deploy/searxng ubuntu@<VM_PUBLIC_IP>:~/searxng
```

Back on the VM:

```bash
cd ~/searxng/oracle-vm
cp .env.example .env

# 1) secret for SearXNG
python3 -c "import secrets; print(secrets.token_hex(32))"      # -> SEARXNG_SECRET

# 2) bcrypt hash for the Basic Auth password (remember the PLAINTEXT too)
docker run --rm caddy caddy hash-password --plaintext 'CHOOSE_A_STRONG_PASSWORD'

nano .env   # fill SEARXNG_SECRET, SEARXNG_DOMAIN, SEARXNG_BASICAUTH_USER, SEARXNG_BASICAUTH_HASH

docker compose up -d
docker compose logs -f caddy    # watch it obtain the Let's Encrypt cert, then Ctrl-C
```

Caddy auto-fetches the TLS cert on first boot (needs port 80 reachable + DNS
pointing here, both done above).

---

## 6. Verify from the VM (and your laptop)

```bash
curl -s "https://nexus:CHOOSE_A_STRONG_PASSWORD@YOURNAME.duckdns.org/search?q=site:linkedin.com/in+engineer&format=json" | head -c 300
```

You should get JSON with a `results` array. If you get a 401, the user/password
don't match the hash; a 405 means `method` isn't GET in `settings.yml` (it is in
the committed file — make sure you copied that one).

---

## 7. Wire the NexusReach backend (Railway)

On the **api**, **worker**, and **beat** services, set the URL **with the
plaintext Basic Auth credentials**:

```env
NEXUSREACH_SEARXNG_BASE_URL=https://nexus:CHOOSE_A_STRONG_PASSWORD@YOURNAME.duckdns.org
```

And move `searxng` back to the front of the provider chains so it's used first
(paid providers stay as automatic fallbacks):

```env
NEXUSREACH_SEARCH_LINKEDIN_PROVIDER_ORDER=searxng,brave,google_cse,serper
NEXUSREACH_SEARCH_EXACT_LINKEDIN_PROVIDER_ORDER=searxng,brave,google_cse,serper
NEXUSREACH_SEARCH_HIRING_TEAM_PROVIDER_ORDER=searxng,brave,serper
NEXUSREACH_SEARCH_PUBLIC_PROVIDER_ORDER=searxng,brave,serper,tavily
NEXUSREACH_SEARCH_EMPLOYMENT_PROVIDER_ORDER=tavily,searxng,brave,serper
```

Redeploy the three services. Do a fresh people search (or **Refresh** on a job's
People panel) — LinkedIn links should appear, now served free via SearXNG.

---

## 8. Maintenance & troubleshooting

- **TLS renewal:** automatic (Caddy). The `caddy_data` volume persists the cert.
- **Updates:** `cd ~/searxng/oracle-vm && docker compose pull && docker compose up -d`.
- **429 / throttling:** if SearXNG starts returning `429` (you'll see the router
  fall through to paid providers), set `limiter: false` in `deploy/searxng/settings.yml`
  on the VM and `docker compose restart searxng` — safe because only your
  authenticated backend can reach it.
- **It's down → search still works:** the provider chain falls through to
  Brave/Google/Serper automatically, so a VM hiccup degrades to paid quota rather
  than breaking discovery.
- **Rotate the password:** regenerate the hash (step 5.2), update `.env` +
  `docker compose up -d`, and update `NEXUSREACH_SEARXNG_BASE_URL` on Railway.
