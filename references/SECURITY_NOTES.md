# Security notes

What the prototype login does, what it does not do, and what has to change
before SENTRA is used outside a pilot.

Written 2026-09-18, while specifying the auth layer. The decision on the
record: **the prototype gets the simple login, and everything in "Deferred" is
accepted risk rather than an oversight.** This file exists so that the
distinction survives the people who made it.

Nothing here is a live incident. It is all "this is fine for a pilot and is not
fine for a service".

## Threat model, because it changes the order

The corpus is published Bundestag material. Confidentiality of the documents is
close to a non-issue, and reasoning about this system as though it were secret
data leads to protecting the wrong things. The assets that actually matter:

| asset | why | exposed by |
|---|---|---|
| AI Hub key | it is money. ~180 generation calls per eval round | any caller of `/explorer/*` |
| index integrity | WD staff read the answers as authoritative. Poisoning the index changes what a Wissenschaftlicher Dienst tells a Bundestag member | `POST /api/ingest`, unauthenticated |
| eval record integrity | the round is what the system gets signed off on. A verdict is a claim someone owns | `Verdict.tester` is typed, not verified |
| feedback file | user-typed questions = **personal data under DSGVO**, and we are the controller | `GET /api/feedback`, unauthenticated |

Write paths and the feedback read path first. Document read paths last.

## Today, before any login (verified in code)

| fact | consequence |
|---|---|
| no Ingress, no TLS, no cert-manager anywhere in `k8s/` | everything crosses the network in clear text |
| `sentra-frontend` is a bare `LoadBalancer` on :80 | the pilot is on the open internet |
| no NetworkPolicy anywhere in `k8s/` | ClusterIP is not a boundary. Any pod reaches any service |
| `POST /api/ingest` unauthenticated, `routes.py:70` | anyone can re-index the corpus |
| `GET /api/feedback` unauthenticated, `routes.py:212` | personal data, world-readable |
| ~~`system_prompt` client-supplied~~ **closed** (#191) | was: any caller replaces the system prompt on any generation call. Now at least `pruefer`, and the gate is on the field rather than the endpoint — see below |
| Qdrant has no API key, `k8s/qdrant/deployment.yaml`, default is open | read the corpus and its embeddings, or drop collections |
| `Verdict.tester` is a free string, `sentra_eval/models.py:475` | the comment in the model already says why: there is no auth to derive it from |

Sound, and worth not breaking: the path-traversal guard in `serve_document`
(`routes.py:157`) rejects `/`, `\`, `..` and non-`.pdf`, and Starlette
percent-decodes before it runs, so `%2e%2e` is caught too. Backend and Qdrant
are ClusterIP rather than published. Secrets go through sealed-secrets, not git.

## What the prototype login fixes

Identity for the people using the UI, an Admin tab that is not visible to
everyone, and an author on eval verdicts and feedback. That is the whole of it,
and it is the right scope for a pilot.

## What it does not fix, and must not be described as fixing

**A hidden tab is not access control.** Gating the Admin tab in React hides the
button, not the endpoint. `POST /api/ingest` stays reachable with curl from
anywhere that can route to the service. If the backend does not enforce, the
tab is decoration.

**Edge auth is not backend auth.** nginx and any proxy in front of it guard the
path through nginx. The backend listens on :8000 as a ClusterIP service with no
NetworkPolicy, so anything inside the cluster talks to it directly and skips
the edge entirely. Specifically: **a backend that trusts a forwarded header
like `X-Forwarded-Email` trusts anything in the namespace to name itself.** If
the prototype does that — and for a pilot it reasonably might — it is a
placeholder for signature verification, not a lighter version of it.

**Login answers who, not how much.** An authenticated user spends the hub key
exactly as freely as an anonymous one. Quota is a separate control.

**Roles are only as good as the claims.** If the IdP has no maintained group
for this app, everyone lands on the fallback role, and the fallback is then the
actual policy.

## Deferred

Severity is "before this is a service", not "before the pilot".

| # | item | severity |
|---|---|---|
| 1 | TLS. Ingress + cert-manager. **Prerequisite for login, not a follow-up:** today there is no session cookie to steal, after login there is one and it is in clear text | high |
| 2 | Verify the token signature in the backend (JWKS), rather than trusting the edge | high |
| 3 | NetworkPolicy: only the frontend pod reaches the backend, only the backend reaches Qdrant | high |
| 4 | Qdrant API key, and stop relying on the namespace being a boundary | medium |
| 5 | Per-user rate limit / quota on `/explorer/*` | medium |
| ~~6~~ | ~~`system_prompt` restricted to reviewer and admin~~ **done** (#191). The note that the harness needs it turned out to be wrong: it never sets one, and that is what made the fix safe | ~~medium~~ |
| 7 | Audit log: who triggered a re-index, who filed or changed a verdict | medium |
| 8 | Feedback gets a retention rule and a DSGVO basis, not just an author field | medium |
| 9 | `Verdict.tester` becomes the authenticated subject; keep the typed name for rounds already recorded | low, but it is the point of the whole exercise |
| 10 | The eval harness is not in `k8s/kustomization.yaml`, so `/api/eval` 502s in the cluster and this is compose-only today. When it is deployed it inherits every row above, and its Postgres is `sentra:sentra` in `docker-compose.yml` | blocks deployment, not the pilot |

Symlinks under `documents_dir` are followed by `is_file()`. `filename` cannot
contain `/`, so it must be a direct child, so only an operator can place one.
Noted rather than ranked.

## Open

- which IdP. AISC/HPI Keycloak or Entra, or Keycloak in the cluster. Decides
  what `login()` redirects to and what `/api/me` verifies. Not decided as of
  writing, and the prototype login is deliberately shaped to not depend on it
- does Auswertung get gated to a reviewer role, or stay open alongside Admin
- who may add / withdraw documents — the same unresolved question
  `SOURCE_MANAGEMENT_NOTES.md` already parks under its own Open
- whether WD's own security review has requirements we have not heard yet.
  Cheaper to ask before item 1 than after item 3
- someone other than the author of the auth code should read it before WD staff
  use it

## Order

```
0  prototype login + Admin tab + backend enforcement   ← the pilot, now
1  TLS                                                  prerequisite for anything real
2  JWKS verification in the backend                     retires the trusted header
3  NetworkPolicy                                        makes 2 hold even inside the cluster
4  Qdrant key, rate limits                             (system_prompt gating done, #191)
5  audit log + feedback retention
6  eval harness into k8s, with its own credentials
```

0 is not on the path to 1. It is a pilot affordance that 1–3 replace, and
keeping that visible is the reason this file exists.

## What the `system_prompt` fix taught, since it is the one that is done

**Gate the field, not the endpoint.** The obvious implementation puts
`require_role` on `/explorer/answer` and is wrong: the evaluation harness posts
there with no credential at all — `runner.py` builds its client with a base URL
and a timeout and nothing else — so it would answer 401 to every round the
moment a login was configured. The harness would report that as SENTRA being
unreachable, which is a day spent looking in the wrong place.

So the endpoint stayed open and one field closed. Everything that does not set
`system_prompt` is untouched, which is every reader and every call a round
makes, and that is what the larger half of the tests pins.

**The harness never needed it.** This file said "the harness needs it, end
users do not". The first half was wrong — nothing in `sentra_eval` sets a
system prompt; it reads the one SENTRA echoes back, for provenance. The
assumption was plausible and would have made the fix look much more expensive
than it was, which is an argument for checking a claim like that before
planning around it.

**The second harm is the one specific to this project.** A caller-supplied
prompt is the ordinary prompt-injection concern, but it also makes the system
unmeasurable: a round measures the answers SENTRA gives, and an answer produced
under somebody else's instructions is not one. No check in the harness could
have told — the prompt is echoed back, so it was recorded faithfully, and
nothing refused.

**Blank is not an override; whitespace is.** `explorer._generate` computes
`system_prompt or default`, so `""` changes nothing while `"   "` reaches the
model *as* the system prompt — an empty instruction, which is the one worth
sending if the goal were to strip the guardrails. The guard agrees with what
the service does rather than with what the field looks like.
