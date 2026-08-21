# Hypothesis Registry

| ID | Rule | Status | Historical note |
|---|---|---|---|
| H0 | All sessions, 30s extreme selloff, fixed 300s exit | FROZEN CONTROL | 3,655 trades; thin positive Net@2 |
| H1 | H0 restricted to 09:00–10:30 | POST-HOC | Stronger historical concentration; not OOS validated |
| H2 | H0 restricted to 09:00–10:30 AND causal high-vol >=80th percentile | POST-HOC | Historical N≈740, PF≈1.32, E≈+8.14pt; not OOS validated |
| H3 | Structural-stop family | RESEARCH ONLY | Must preserve right tail and use physical ticks |
| H4 | Post-entry 30–60s path-state management | RESEARCH ONLY | Management signal only; cannot retroactively change entry |

No hypothesis may be promoted by re-optimizing the already-seen 2024–2026 data and calling the result OOS.
