"""Gate eval — do the result gates refuse what is impossible and pass what is merely odd?
(PRJ-13 T08b)

`ResultValidation.evaluate` decides, for every SQL result on both execution paths,
`accept | warn | requery | block` (`docs/SYSTEM_ARCHITECTURE.md`, the shared gates). A
false BLOCK throws away a correct answer the user asked for; a missed block publishes an
impossible number. So the eval reports precision and recall per action, and the CI gate is
asymmetric on purpose: **block precision must be 100%** — every case the corpus labels as
legitimate-but-odd (a negative balance, a refund-driven negative revenue, 180% growth)
must pass — and total accuracy may not drop against the baseline.

The labels come from the gate's CONTRACT (the decision table in `result_validation.py`,
the token rules in `data_gate.py`), never from running it: a label copied from output
passes by construction (retro S-05).
"""
