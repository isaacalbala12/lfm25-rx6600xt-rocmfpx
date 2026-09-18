# Why the 6144x2048 projection reports N=1 at C4

## Finding

The apparent `6144x2048,N=1` operation is not four independent HTTP requests
being dispatched one by one. It is the short-convolution input projection in
LFM2's recurrent path. The model graph carries decode activations as
`[6144, n_seq_tokens, n_seqs]`; with four active users that is `[6144,1,4]`.
The matrix dimension exposed to the MMV shader is therefore N=1, while the
four users remain separate batch planes in `ne[2]`.

The C4 trace contains 22 calls per decode graph, one per recurrent layer, not
88 calls. Its element count is `6144 * 1 * 4`, independently confirming that
all four users are present in each call. Sequence identity and recurrent state
are indexed through that outer plane.

## Causal conclusion

N=1 is a consequence of tensor semantics and layout, not missed HTTP batching,
the scheduler, or a backend selector failure. Flattening the four sequence
planes into MMV N=4 would cross the recurrent-state layout and would require a
new graph representation plus explicit proof of state and stride equivalence;
it is not a safe selector-only optimization.

Decision: **REJECT the rebatching hypothesis**. If this family is revisited,
optimize the existing N=1 shader while preserving `ne[2]`, or first construct a
reference-checked graph transformation that preserves per-sequence recurrent
state. Do not describe this operation as unbatched service work.
