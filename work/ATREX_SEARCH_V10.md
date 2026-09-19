# V10 structural layout search

V10 tested the exact prepacking family requested after V9 rather than another
constant sweep. Each candidate preserved every FP4 code and scale and used a
reversible upload/download conversion. The evaluator remained the authority;
candidate code did not alter correctness, route or timing parsers.

## Search lineage

1. **Padded block:** aligned code and scale words, +17.65% bytes on selected
   gate/up weights. It won 1.227% locally but has only ~0.36% predicted mixed
   leverage and high implementation/memory cost.
2. **Global planar:** removed padding while preserving aligned code words. It
   regressed 43.15%, identifying remote scale locality as a critical cost.
3. **Grouped-four:** kept scales adjacent to groups of four blocks with zero
   byte overhead. It regressed 3.85%; local grouping did not overcome added
   address/extraction work.

The result is convergence, not an absence of signal: aligned direct loads can
help, but the gain is too small once memory cost and locality are accounted for.
Do not repeat this layout family by changing group size without a new ISA/cache
mechanism.

## Independent V8 composition

V10 also tested the two independent archived candidates together:

- gate/up BK3 exact-shape: -1.316% local in V8;
- down exact-shape: -2.161% local in V8.

Three exploratory Profile-B pairs measured +0.549% aggregate input/output
throughput, bootstrap range [+0.402%, +0.688%], TTFT p95 -0.581% and E2E p95
-0.549%. Only 2/3 pairs had all four output hashes identical; one request in
pair 1 diverged. The gain is below the 0.75% promotion threshold and the output
divergence remains unexplained. Decision: **ARCHIVE COMPOSABLE / do not
promote**. No mixed-service or quality expansion is justified.

## Decision

- Production remains fixed chunk128 + R0 + selective gate/up BK3.
- Padded layout: COMPOSABLE evidence, not production.
- Global planar and grouped-four: REJECT.
- V8 exact gate+down composition: ARCHIVE COMPOSABLE, not production.
- Next work must leave this MMQ layout/control-flow family.
