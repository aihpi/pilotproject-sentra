# Security notes

Scope of the prototype login, the exposures it leaves in place, and the work
required before SENTRA is used outside a pilot.

Recorded 2026-09-18 during the design of the auth layer, and revised as items
have closed. The prototype takes the simple login; everything under Deferred is
accepted risk rather than an oversight. Nothing described here is a live
incident.

## Threat model

The corpus is published Bundestag material. Document confidentiality is close
to a non-issue, and treating the system as though it held secret data leads to
protecting the wrong things. The assets that matter:

| Asset | Why | Exposed by |
|---|---|---|
| AI Hub key | It is money. Roughly 180 generation calls per eval round | Any caller of `/explorer/*` |
| Index integrity | WD staff read the answers as authoritative. Poisoning the index changes what a Wissenschaftlicher Dienst tells a Bundestag member | `POST /api/ingest` |
| Eval record integrity | The round is what the system gets signed off on, and a verdict is a claim someone owns | `Verdict.tester` is typed, not verified |
| Feedback file | User-typed questions are personal data under DSGVO, and we are the controller | `GET /api/feedback` |

Write paths and the feedback read path come first. Document read paths come
last.

## Current state

Verified in code and against the deployed instance.

| Fact | Consequence |
|---|---|
| TLS terminates at a Caddy reverse proxy upstream of the cluster, with an HPI certificate | Browser traffic is encrypted. There is no Ingress and no cert-manager in `k8s/`, deliberately, because nothing in the cluster terminates TLS |
| Caddy answers HTTP Basic before any request reaches SENTRA | The pilot is not open to the internet. It is open to everyone holding one shared password |
| `sentra-frontend` is a `LoadBalancer` on an internal address | Reachable only through the proxy above |
| No NetworkPolicy anywhere in `k8s/` | ClusterIP is not a boundary. Any pod reaches any service |
| `POST /api/ingest` requires the admin role, which is unenforced while no login is configured | With no users configured, anyone past the shared password can re-index the corpus |
| `GET /api/feedback` requires the reviewer role, under the same condition | Personal data, readable by anyone past the shared password |
| `SENTRA_USERS` and `SESSION_SECRET` are unset on the cluster | No login is possible, so the two rows above are open in practice |
| Qdrant runs with no API key | Anything inside the cluster can read the corpus and its embeddings, or drop collections |
| `Verdict.tester` is a free string | The model comment already says why: there is nothing to derive identity from |

Worth not breaking: the path-traversal guard in `serve_document` rejects `/`,
`\`, `..` and anything that is not a PDF, and Starlette percent-decodes before
it runs, so `%2e%2e` is caught. Backend and Qdrant are ClusterIP rather than
published. Secrets go through sealed-secrets rather than git.

Symlinks under `documents_dir` are followed by `is_file()`. A filename cannot
contain `/`, so the target must be a direct child, so only an operator can
place one. Noted rather than ranked.

## Scope of the prototype login

Identity for the people using the UI, an Administration tab that is not offered
to everyone, and an author recorded on eval verdicts and feedback. That is the
whole of it, and it is the right scope for a pilot.

## What it does not do

A hidden tab is not access control. Gating a tab in React hides the button, not
the endpoint. `POST /api/ingest` stays reachable with curl from anywhere that
can route to the service. Where the backend does not enforce, the tab is
decoration.

Edge auth is not backend auth. A proxy guards the path through the proxy. The
backend listens on port 8000 as a ClusterIP service with no NetworkPolicy, so
anything inside the cluster talks to it directly. A backend that trusts a
forwarded header such as `X-Forwarded-Email` therefore trusts anything in the
namespace to name itself. Where the prototype does that, it is a placeholder
for signature verification rather than a lighter version of it.

Login answers who, not how much. An authenticated user spends the hub key as
freely as an anonymous one. Quota is a separate control.

Roles are only as good as the claims behind them. If the identity provider has
no maintained group for this application, everyone lands on the fallback role,
and the fallback becomes the actual policy.

## Deferred

Severity is measured against "before this is a service", not "before the
pilot".

| # | Item | Severity |
|---|---|---|
| 1 | Verify token signatures in the backend via JWKS rather than trusting the edge | High |
| 2 | NetworkPolicy, so that only the frontend reaches the backend and only the backend reaches Qdrant | High |
| 3 | Configure `SENTRA_USERS` and `SESSION_SECRET`, which is what makes the role guards take effect at all | High |
| 4 | Qdrant API key, and stop relying on the namespace as a boundary | Medium |
| 5 | Per-user rate limit or quota on `/explorer/*` | Medium |
| 6 | Audit log covering who triggered a re-index and who filed or changed a verdict | Medium |
| 7 | A retention rule and a documented DSGVO basis for feedback, not only an author field | Medium |
| 8 | `Verdict.tester` becomes the authenticated subject, keeping the typed name for rounds already recorded | Low in effort, though it is the point of the exercise |

### Closed

| Item | Closed by |
|---|---|
| TLS in front of the login, so that no session cookie travels in clear text | Caddy terminates TLS upstream. `session_cookie_secure` defaults to on and is correct as it stands |
| `system_prompt` restricted to reviewer and admin | #191. The field is gated rather than the endpoint, so the harness keeps working |
| The eval harness reachable in the cluster | #216. It inherits every row above, and its Postgres password is sealed rather than `sentra:sentra` |

## Open questions

Which identity provider: AISC/HPI Keycloak, Entra, or Keycloak in the cluster.
It decides what `login()` redirects to and what `/api/me` verifies. The
prototype login is deliberately shaped not to depend on the answer.

Whether Auswertung is gated to a reviewer role or stays open alongside
Administration.

Who may add or withdraw documents. `SOURCE_MANAGEMENT_NOTES.md` parks the same
question under its own open list.

Whether WD's own security review has requirements not yet heard. Cheaper to ask
before item 1 than after item 2.

Someone other than the author of the auth code should read it before WD staff
use it.

## Order

```text
0  prototype login, Administration tab, backend enforcement
1  JWKS verification in the backend, retiring the trusted header
2  NetworkPolicy, which makes 1 hold inside the cluster as well
3  Qdrant key, rate limits
4  audit log and feedback retention
```

Step 0 is not on the path to step 1. It is a pilot affordance that steps 1 and
2 replace.
