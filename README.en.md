<div align="center">

# 🧬 EVOL-AI

**AI-Driven Drug Discovery Pipeline**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-131%20passed-brightgreen.svg)](#-run-tests)
[![Dependencies](https://img.shields.io/badge/dependencies-zero-blue.svg)](#-quick-start)

[中文](README.md) | **English**

</div>

> A data pipeline that chains **cross-species mechanism discovery → vector sequence design → in-vivo validation** into an auditable, compounding loop — every wet-lab experiment becomes training data for the next prediction.

Sequence analysis, synonymous codon optimization, weighted target ranking, and a prediction–experiment closed-loop ledger are all real computation backed by real persistence.

---

## 🚀 Quick Start

```bash
cd evol-ai-platform
python app.py 8000        # Python 3.10+ only, zero third-party deps
# open http://127.0.0.1:8000
```

First launch auto-creates `data/evol.db` and seeds 18 demo ledger records.

### 🧪 Run tests

```bash
python -m unittest discover -s tests -v   # 131 unit tests, all green
node tools/e2e.js                          # 74 browser e2e checks (needs server + Playwright)
```

---

## 📁 Layout

```
app.py                  HTTP server + routing + SQLite (stdlib http.server)
engine/
  codon_table.py        Standard genetic code + Kazusa human codon usage + translate
  sequence.py           Sequence analysis (GC/skew/CpG/homopolymers/tandem repeats/
                        16 restriction sites/immunostimulatory motifs/Kozak/
                        cryptic splicing/polyA/E2F/Sp1/rare codons)
  optimize.py           Synonymous codon optimization (CSP: greedy + one-step backtrack)
  targets.py            Six-dimension weighted target ranking
  protein.py            Protein phys-chem (MW/pI/GRAVY/aliphatic index/ε280/
                        hydrophobic segments/N-glycosylation)
  metrics.py            MAE/R²/Spearman + bootstrap intervals + stratification + model card
  models.py             Candidate model scoring + license one-vote veto
  assets.py             Data asset catalog (search / sort / permission)
  inference.py          Pluggable inference task system (queue / persistence / provenance)
data/
  targets.json          6 indications × six-dimension scores + evidence chains
  demo_construct.txt    455 bp demo construct (6 risk sites injected)
  assets.json           Demo data asset catalog
web/                    Frontend: index.html / app.js / styles.css (all via fetch)
tests/                  131 unit tests
tools/e2e.js            Playwright end-to-end
```

---

## 📡 API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/targets?weights={...}` | Target ranking (recompute with given weights) |
| GET | `/api/records` | Full ledger + live metrics |
| GET | `/api/metrics` | Metrics only |
| GET | `/api/models` | Candidate model matrix (score + license veto + sort) |
| GET | `/api/model-card?cutoff=10-01` | Model card: stratified metrics / bootstrap / anomalies |
| GET | `/api/assets?q=&sort=` | Data asset catalog (search / sort) |
| GET | `/api/demo` | Demo construct sequence |
| GET | `/api/records/export.csv` | Ledger CSV export (UTF-8 BOM) |
| POST | `/api/analyze` | `{sequence}` → full analysis |
| POST | `/api/optimize` | `{sequence, options}` → optimized seq + diff + relaxation report |
| POST | `/api/protein` | `{sequence}` → phys-chem profile + sequence risks |
| POST | `/api/infer` | `{sequence}` → submit structure inference task (async) |
| POST | `/api/records` | `{id,pred,obs,model,note,outcome}` → write ledger |
| DELETE | `/api/records/<id>` | Delete and return new metrics |

### A real example

```bash
curl -s http://127.0.0.1:8000/api/demo \
  | python -c "import json,sys;print(json.load(sys.stdin)['sequence'])" > /tmp/s.txt
curl -s -X POST http://127.0.0.1:8000/api/optimize \
  -H 'Content-Type: application/json' \
  -d "{\"sequence\":\"$(cat /tmp/s.txt)\",\"options\":{\"cpg_free\":true,\"avoid_sites\":true}}"
```

Demo construct optimization result:

| Metric | Before | After |
|---|---|---|
| CpG / 100 bp | 7.9 | **0.0** |
| Risk items | 7 | **0** |
| Composite score | 70.8 | **86.2** |
| Protein sequence | — | **unchanged** (asserted in code) |
| Solver backtracks | — | 34 |

---

## 🎯 Three hard design choices

1. **Synonymous optimization is a constraint-satisfaction problem, not table lookup.** When the previous codon ends in C and every synonymous codon of the current amino acid starts with G (e.g. Glu only has GAA/GAG), the junction necessarily forms CpG. Instead of silently relaxing the constraint, the solver must **backtrack the previous codon**. The relaxation ladder is reordered too: CpG is defended last, tandem repeats sacrificed first. Relaxation and backtrack counts are reported honestly.

2. **Don't pretend to satisfy what can't be satisfied.** When CDS length isn't a multiple of 3, the trailing remainder can't form a full codon. The engine reports it in `changes.truncated_nt` instead of forcing or silently dropping it.

3. **No fabricated numbers for unimplemented parts.** Structure inference is a **pluggable async task system** (`engine/inference.py`): submit → queue → run → persist, with a mandatory reproducible provenance triple (image digest / weight hash / input hash). It currently runs a **deterministic mock backend** — same input → same output, different input → different output, pinned by unit tests. Swapping in a real GPU backend is a one-line change of `ACTIVE_BACKEND`. Protein phys-chem (MW / pI / GRAVY / aliphatic index / hydrophobic windows / N-glycosylation) are exact formulas; model scoring is heuristic and labeled as demo data in the UI.

   The hydrophobicity threshold is calibrated: it requires a **continuous ≥15 aa** stretch to flag transmembrane, avoiding a false positive on EGFP's β-barrel hydrophobic core. Both cases are pinned by tests.

---

## 📊 Metrics methodology

The classic small-sample mistake is reporting only a point estimate, so every headline metric **carries an interval**:

```
overall   n=18  MAE 0.58 [0.41, 0.85]   R² 0.58 [0.20, 0.89]   ρ 0.80
b2-0.6.1  n=11  R² 0.00 [0.00, 0.82]    ← auto-flagged as stratified anomaly
b2-0.5.4  n= 5  R² 0.72 [0.02, 1.00]
esm-lora  n= 2  R² 1.00 — (insufficient n, do not cite)
```

Five rules, all in `engine/metrics.py`:

1. **Fixed bootstrap seed** — identical results every run, so reports are reproducible.
2. **No interval when n < 5**, flagged "do not cite independently".
3. **Auto-detected stratified anomalies** — a group whose R² differs from the overall by ≥0.3 raises an alarm.
4. **Prospective vs retrospective separation** — cutoff should be the model-freeze date; post-freeze records count as blind.
5. **Audit the ledger before computing metrics** — pretty metrics on a success-only ledger are just "fit on the successes".

The model card exports Markdown in one click, with limitations as a **mandatory field**.

---

## ⚠️ The ledger itself may be a product of selective recording

No one likes recording failed experiments, so R² on a "success archive" is naturally inflated. Three things were done:

**1. Three outcomes — technical failures excluded from metrics.** `outcome` takes `hit` / `miss` (negative but has a reading) / `fail` (technical failure, no valid reading). `fail` records still persist (failure rate is itself a signal for construct design) but never enter metrics. The UI shows "18 in metrics" vs "19 records, 1 technical failure excluded" — mismatches are explained, never left for guessing.

**2. Positive-rate audit with an alarm.** The demo ledger marks all 18 as threshold-hit — 100% positive — so the tool immediately flags `suspected selective recording`: real screening hit rates are far lower, so the MAE / R² here are an **upper bound of optimistic bias**, not model capability.

**3. Tipping-point analysis.** `sensitivity_missing` assumes x% of negative samples were never recorded, recomputes metrics, and plots the curve. For the demo data the tipping point is **10%** — just one in ten missed negatives drops R² from 0.584 below the 0.55 target. The three assumptions are always shown alongside the curve.

---

## 🚧 Known limitations

- The structure-inference backend is currently a **deterministic mock**, not a real Boltz-2 forward pass — labeled in the UI; its numbers must not be cited as model capability. But the queue, persistence, and provenance triple are real engineering; swapping the real backend changes only `ACTIVE_BACKEND`.
- Omics analysis (Scanpy) and literature RAG (PaperQA2) are M2, not implemented.
- The data asset catalog is backend-backed (search / sort), with "train > evaluate > retrieve" one-way decreasing permission; unlabeled data defaults to non-trainable.
- Model-matrix scores are internal evaluation criteria (manual scoring), but sorting, composite score, and license veto are computed by the backend with testable rules.
- No auth; local use only. No patient-sample data included.

---

<div align="center">

[MIT](LICENSE) © [skywalkerqqq](https://github.com/skywalkerqqq)

</div>
