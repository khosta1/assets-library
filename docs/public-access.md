<!-- covers: server/** -->

# Opening the library beyond the mesh

*How readers who are not on ZeroTier get read-only access, what has to be
configured, and what has to change in the code. Written 2026-10-14.*

---

## Why

ZeroTier's free tier caps at **25 members**, and every one of them has to
install a client. That ceiling is reached. The requirement is more readers, the
**same permission level** — browse and download, nothing else — and **nothing
installed on their side**.

That is a *reachability* problem, not a permissions problem. The permission
level already exists and is not being widened.

---

## What is already true, and is therefore not the work

Three things that would otherwise be mistaken for tasks:

- **The API is read-only by construction.** Every route in `server/api.py` is a
  `GET`, every one of them passes through one `before_request` token gate, and
  there is no write path anywhere in the service. `derived/` is never listed
  and never served. Nothing about exposing it changes what it can do.
- **The client takes a URL in a text field.** `remote.Host.url` is just a
  string, so pointing a copy at `https://<domain>` instead of
  `http://10.209.73.177:8083` is one edit in Library ▸ *Remote libraries…*
  **No client code changes. None.**
- **The bundled runtime does TLS properly.** Checked 2026-10-14: OpenSSL
  3.0.13, 74 certificates loaded from the Windows store, `CERT_REQUIRED`,
  hostname checking on. Worth checking because every call the app makes today
  is `http://` — HTTPS had never been exercised from `runtime\python.exe`.

---

## What was measured

| | |
|---|---|
| Livebox WAN IPv4 | **public** (`90.105.x.x`), checked 2026-10-14 |
| CGNAT | **no** — CGNAT is `100.64.x` – `100.127.x`, this is not that |
| consequence | direct port forwarding works; **no tunnel, no relay, no third party** |

**Not measured, and load-bearing:** the actual upload throughput. The *"1–2
MB/s, so a 1 GB asset is ~17 minutes"* in `remote.py` describes **ZeroTier's
relay**, not the fibre. Nobody has timed a transfer over a direct path. Plans
that assume a bandwidth problem are assuming a number that measures something
else.

---

## The shape

```
reader → https://<domain>:443 → Livebox NAT → 192.168.1.13 → Caddy → gunicorn 127.0.0.1:8083
                                                                ↑
                               ZeroTier members keep hitting 10.209.73.177:8083 directly
```

**443 is the only port forwarded.** 22 and 445 stay inside the house, and that
is not a detail — Samba's `write list = felix` on 445 is the entire admin gate
on the master, and it was designed assuming the LAN (gotcha 19). SSH on 22 is
the re-index path. Neither has any business on the internet.

---

## 1. The Livebox

`Paramètres avancés → Réseau → NAT/PAT`

- forward **443/tcp → `192.168.1.13`**, and nothing else
- **DynDNS**: the Livebox has a client built in. Point the domain at it. Orange
  FTTH addresses change on renewal, and without this every change silently
  breaks every reader with nothing to explain why.
- leave **«Mon accès à distance»** at *inactivé* — it is a login page on the
  router exposed to the internet, and it buys nothing here.

---

## 2. The box

**Keep gunicorn where it is.** It stays on `0.0.0.0:8083` so the existing 25
ZeroTier members keep working unchanged through `10.209.73.177:8083`. Caddy
reaches it on loopback.

**firewalld.** 8083 is currently open in the `public` zone (`server/README.md`
step 6). Close it there and open 443 instead — the ZeroTier interface
`ztfl6jes34` is in the `trusted` zone whose target is `ACCEPT`, so mesh members
are unaffected:

```bash
sudo firewall-cmd --zone=public --remove-port=8083/tcp --permanent
sudo firewall-cmd --zone=public --add-port=443/tcp --permanent
sudo firewall-cmd --reload
```

**Caddy**, for TLS. The whole config:

```
<domain> {
    reverse_proxy 127.0.0.1:8083
}
```

Certificates are automatic. With only 443 forwarded, Caddy uses the
**TLS-ALPN-01** challenge, which runs over 443 alone — HTTP-01 would need port
80 open as well. *Untried here.* If it refuses, forwarding 80 as well is the
fallback and costs nothing.

**Why TLS is not optional.** Port 8083 serves plain HTTP and the bearer token
crosses in the clear. On a LAN, and inside ZeroTier's own encryption, that is
survivable. On the open internet it is handing out the key to anything on the
path.

**Watch:** gunicorn is set to `--timeout 3600` for 1 GB downloads. Caddy's
proxy defaults have not been checked against a transfer that long.

---

## 3. The one code change: per-person tokens — **built 2026-10-14, never run**

The only part that is code in this repository, and **required** rather than
optional before a public URL exists.

**Today** `server/api.py` holds one secret:

```python
TOKEN = os.environ.get("ASSETLIB_TOKEN", "")
...
if not hmac.compare_digest(sent, TOKEN):
    abort(401)
```

Among 25 friends on a private mesh that is proportionate. On a public URL it is
the real hole: **one leak is anonymous access to everything**, you cannot tell
who pulled what, and the only remedy — rotating the secret — logs out all fifty
people at once.

**What was built:**

- `/etc/assetlib/tokens.json`, `0600 felix:felix`, beside `api.env`:
  `{"label": "secret", ...}`. A file rather than an env var because adding or
  revoking a reader must not mean editing a unit's environment — the recipes
  are in `server/README.md` step 4b.
- `server/api.py` re-reads it when its mtime or size changes, so **revoking
  somebody needs no restart**. A restart is not free: `--timeout 3600` exists
  because a reader may be forty minutes into a 1 GB asset, and dropping that to
  remove one person punishes everyone else for their presence.
- **`ASSETLIB_TOKEN` is kept, and kept first**, so the existing 25 clients are
  not disturbed by any of this. The service now fails closed only when there is
  neither a shared token nor a token file.
- `_require_token()` compares every candidate **even after one matches** —
  stopping early would make the response time depend on *which* token was sent,
  a slower version of the leak `compare_digest` exists to close. The winning
  label lands on `g.reader`.
- A 401 is logged with the caller's address, because the first thing a public
  address buys is strangers, and *"someone is knocking"* has to be
  distinguishable from *"a reader pasted the wrong token"*.
- `after_request` logs **file transfers only**. gunicorn already logs every
  call and a client polls the catalogue on each launch, so a line per request
  would bury the one question this exists to answer: which reader pulled which
  asset.

**A broken `tokens.json` keeps the previous table** rather than emptying it.
Both directions are wrong somehow — keeping it means a revocation typed with a
trailing comma silently does not happen, emptying it means one typo locks out
every reader at once. The second is worse and happens more often, and the admin
still holds `ASSETLIB_TOKEN` regardless.

**`server/client-contract.md` does not change.** It still says
`Authorization: Bearer <token>`; what changes is how many values the server
accepts. No client, old or new, notices.

---

## 4. Each reader

One field, in Library ▸ *Remote libraries…*:

```
url     https://<domain>          ← the only thing that differs from a mesh member
token   <their own>               ← per person, once §3 lands
share   (blank)                   ← LAN only. A remote reader never pushes.
ssh     (blank)                   ← LAN only.
```

A reader with no `share` is one that is only ever browsed from — which the Push
window already handles, offering nothing (`_push_to_server` skips hosts with no
share). Nothing had to be built for that case; it was already correct.

**How a reader gets assets:** Shift+F5 syncs the catalogue, cloud tiles show
what is on the box, right-click ▸ *Import from the server…* downloads one asset,
resumable and hash-verified. **How a reader gets app updates:** GitHub, via
Library ▸ *Check for updates…* — a different master and a different path, and
neither touches the other.

---

## What must not change

- **The API stays read-only.** An upload route is a recorded, rejected decision
  (`decisions.md`, 2026-09-13): keeping it read-only is what stops a leaked
  token from being able to damage a master with no off-site copy.
- **SMB and SSH never leave the LAN.**
- **The token stays out of every tracked file.** The repository is public.
- **`derived/` is never served** — regenerable, and shipping it roughly doubles
  a transfer.

---

## Open, and honest about it

- **Throughput is unmeasured.** Time one large download over the new path
  before concluding anything about object storage, CDNs or where the bytes
  should live.
- **16 concurrent requests, total.** `--workers 2 --threads 8`. A hundred
  readers do not get a hundred downloads; they get a queue. This is a knob, not
  a wall, but it is set for 25 people.
- **No rate limiting and no fail2ban.** 443 open to the internet is found by
  scanners within hours. Every request is 401 without a token, which is the
  right answer, but nothing throttles someone asking a million times.
- **Your home IP becomes public** to everyone you share with. A tunnel would
  have hidden it; direct exposure is the trade for keeping the bytes and the
  control at home.
- **TLS-ALPN-01 on 443 alone is untried**, and so are Caddy's proxy timeouts
  against a 1 GB transfer.
