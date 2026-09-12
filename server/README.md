# `server/` — the library on the Rocky box

The read-only half of the cloud library: a catalogue API at
`http://10.209.73.177:8083` (ZeroTier) that lets a client browse every asset
and pull the ones it needs, without mounting anything.

**These files are deployed by hand.** Nothing in this repo copies them, the
same way the server panel's `server-side/` helpers are installed by hand — and
for the same reason it is written down there: a change here is not live until
someone re-installs it.

---

## What runs where

| | where |
|---|---|
| code | `/opt/assetlib` — this repo's `assetlib/`, `config/` and `server/` |
| venv | `/opt/assetlib/venv` — Flask + gunicorn, nothing else |
| assets | `/srv/data2/assets/library/` — the 2 TB disk |
| catalogue | `/var/lib/assetlib/index.db` — **the SSD**, never the NTFS mount |
| token | `/etc/assetlib/api.env`, `0600 felix:felix` |

The catalogue lives on the SSD because SQLite opens WAL, WAL needs a
shared-memory mapping, and ntfs-3g is FUSE. Filebrowser's BoltDB already cost
an evening to this in July — server panel gotcha **12**.

The library and state paths are set in the environment, not in
`config/library.json`, so the box's copy of that file stays byte-identical to
the repo's. A path that has to differ per machine is the one thing a deploy
must never be able to overwrite.

---

## Install

Steps marked ⚠ need Felix's password — they are outside the three `NOPASSWD`
exceptions.

The repo lives on **Windows**, at `H:\Code\Assets_library`. Steps 1, 3, 4, 5
and 6 run **on the box** over SSH; step 2 runs **on the PC**. Getting that
backwards is the easiest mistake here.

```bash
# 1. ON THE BOX — make the three directories felix can then write into
sudo mkdir -p /opt/assetlib /var/lib/assetlib /etc/assetlib          # ⚠
sudo chown felix:felix /opt/assetlib /var/lib/assetlib               # ⚠
```

```bat
REM 2. ON THE PC — from H:\Code\Assets_library
scp -r assetlib config server felix@192.168.1.13:/opt/assetlib/
```

Only those three directories. `library/`, `runtime/`, `.assetlib/`, `_inbox/`
and `_quarantine/` must NOT go: the library on the box is `/srv/data2/assets`,
the runtime is Windows binaries, and the state directory is built there.

```bash
# 3. ON THE BOX — venv. /usr/bin/python3 is 3.9 here; the core needs 3.11,
#    which is installed as /usr/bin/python3.11 (3.11.13, verified 2026-09-12).
/usr/bin/python3.11 -m venv /opt/assetlib/venv
/opt/assetlib/venv/bin/pip install flask gunicorn

# 4. the token
printf 'ASSETLIB_BASE=/opt/assetlib\nASSETLIB_LIBRARY=/srv/data2/assets/library\nASSETLIB_STATE=/var/lib/assetlib\nASSETLIB_TOKEN=%s\n' \
    "$(openssl rand -hex 32)" | sudo tee /etc/assetlib/api.env >/dev/null   # ⚠
sudo chown felix:felix /etc/assetlib/api.env                         # ⚠
sudo chmod 600 /etc/assetlib/api.env                                 # ⚠
sudo grep ASSETLIB_TOKEN /etc/assetlib/api.env       # copy this into the client ⚠

# 5. units — from /opt/assetlib, where step 2 put them
cd /opt/assetlib
sudo install -m644 server/assetlib-api.service      /etc/systemd/system/   # ⚠
sudo install -m644 server/assetlib-reindex.service  /etc/systemd/system/   # ⚠
sudo install -m644 server/assetlib-reindex.timer    /etc/systemd/system/   # ⚠
sudo systemctl daemon-reload
sudo systemctl start assetlib-reindex          # first catalogue - watch it
journalctl -u assetlib-reindex -n 20           # expect: indexed 75 assets
sudo systemctl enable --now assetlib-api assetlib-reindex.timer

# 6. the port — the LAN only. ZeroTier needs NOTHING: ztfl6jes34 is in the
#    trusted zone, whose target is ACCEPT, so 8083 is already reachable at
#    10.209.73.177 the moment the service listens. enp0s31f6 is in `public`,
#    which is why the fast path from the PC at home needs this one rule.
sudo firewall-cmd --zone=public --add-port=8083/tcp --permanent          # ⚠
sudo firewall-cmd --reload                                               # ⚠
```

⚠ **Never put this behind the Tailscale Funnel.** Panel invariant 10: nothing
on this box is exposed to the internet except through Tailscale, and this
service is exposed to nothing at all beyond the mesh.

---

## Operating it

```bash
systemctl status assetlib-api
journalctl -u assetlib-api -f
sudo systemctl start assetlib-reindex        # after importing over SMB
systemctl list-timers assetlib-reindex.timer
```

`GET /api/health` reports `indexed_at`, so a catalogue that looks wrong can be
checked for staleness before anything else is suspected.

Both units are in the panel's `config.json` service list, which means the
status card and the *restart* button come for free — and `assetlib-reindex` is
a unit precisely so that "refresh the catalogue" is a button the panel already
knows how to press.

---

## The API

Every route requires `Authorization: Bearer <token>` and answers JSON on error.
Everything is `GET`; there is no write path at all.

| route | returns |
|---|---|
| `/api/health` | asset count, `indexed_at`, free bytes on the disk |
| `/api/catalog` | every index row, behind an ETag — send `If-None-Match` |
| `/api/asset/<uuid>` | `asset.json` + the file manifest + total bytes |
| `/api/thumb/<uuid>` | `preview/thumb.jpg` |
| `/api/file/<uuid>/<relpath>` | one file from the package, Range-capable |

`derived/` is never listed and never served: it is regenerable by definition
(`library.json`, `derived_is_disposable`), and shipping it would roughly double
every transfer.

`<relpath>` is checked structurally and then by containment of the **resolved**
path inside the package — whitelist, not escape, the rule the panel's root
helpers follow. Resolving first is what makes it symlink-safe: `..` and a
symlink pointing out of the package both land outside and are refused.

Not by membership of the manifest, which is the obvious way to write it and is
quadratic — the manifest is an rglob, so a 200-file import would rglob the
package 200 times, and on ntfs-3g that is tens of thousands of stat calls to
learn what containment answers in one.

`/api/catalog` gzips itself above 8 KB when the client offers it. There is no
reverse proxy here and Flask does not compress, so a catalogue that arrives
five times smaller has to do it itself.

---

## Getting assets in

There is no upload route, by decision. New assets reach the library from the PC
over SMB on the LAN, using the app itself:

1. mount `\\192.168.1.13\data2`
2. point the app's library root at `…/assets/library`, and **leave
   `roots.state` local** — an `index.db` on an SMB share is the WAL problem
   again, from the other side
3. import as usual
4. `sudo systemctl start assetlib-reindex` on the box, or wait for 04:00

---

## If reads fail

SELinux is Enforcing and `/srv/data2` carries an `samba_share_t` context. The
panel and Filebrowser both read that disk as `felix` without a policy module,
so this should too — but if the API 404s on files that plainly exist, check
`ausearch -m avc -ts recent` before suspecting the code.
