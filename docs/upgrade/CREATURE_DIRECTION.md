# Creature fitting and reference-directed families

Use Vector Studio in Foundry or `vector_author` with profile
`vector-document-v2`. Template `trail_hopper` creates an editable articulated
creature. The independently pinned RAI compiler owns anatomy, fitting, joint
limits, deterministic poses and style admission; Workshop owns revisions,
provider execution, exact acceptance and frozen exports.

- `creature_inspect`: project id and expected revision; return seven proportion
  bounds, rest-pose measurements, joint limits and three attachment sockets.
- `creature_fit`: add `targets` (height/body_width/leg_length/head_diameter, each
  `{target,weight}`) and `free_parameters`. Return a candidate, signed residuals,
  operations and hashes. Infeasible targets remain explicit residuals.
- `creature_pose`: add `leg`, canvas ankle `target: [x,y]`, `clip`, `time`.
  Return a constrained two-joint candidate; unreachable targets never stretch.
- `accept_preview`: submit the observed revision, exact `candidate_sha256`,
  returned `operations` and unique `idempotency_key`. Hash authorization occurs
  inside the writer transaction and participates in retry identity.

`creature_set` patches retain named parts, artist appearance and existing clips.
`creature_detach` explicitly releases regeneration while keeping artwork/motion.
Protected parts and optimistic conflicts use the existing document checks.
Creature sprite-sheet timing is version 2 and adds exact per-frame left/right
foot and head sockets. Existing non-creature v1 sheets and frozen ZIPs remain
reproducible with their original versions.

For AI art direction, `ai_submit` optionally takes
`direction: {reference_project_id,expected_reference_revision,stroke_width}`.
Workshop freezes the reference palette/hash and creates three proposals from
the same source. Every candidate must pass typed style, protection, rig and
retained-part checks; duplicate rendered treatments reject. `ai_get` includes
the candidates, frozen reference provenance and consistency/editability metrics.
Choose one exact hash through the existing `ai_accept` command. Another editor's
write makes acceptance conflict. Later reference edits cannot change a frozen
proposal. Provider work shares one process/lock and an overall 180-second budget;
unaccepted jobs expire in memory. Artist review remains the usefulness gate.

The browser acceptance harness can inject an explicitly selected deterministic
family fixture. That verifies UI/transaction contracts and supplies no evidence
about real-model art quality. Real provider evaluation must record its own
model, source, prompt, admitted candidates and human review separately.
