## ⚠️ #171 TRIGGER FIRED: stable-ts removed from upstream main

The weekly detector found that upstream `main` **no longer imports
`stable_whisper` and no longer declares the `stable-ts` dependency**. Both
signals gone at once means the `refactor/drop-stable-ts` work (faster-whisper
direct + Netflix-style segmenter) has **merged to upstream main**.

This is the event the standing watch in **subarr#171** was created for. It is
distinct from routine patch drift — it removes `CUSTOM_REGROUP` and
`WORD_LEVEL_HIGHLIGHT`, which is the base our entire regroup investment
(strongpad, the #168 arena, the Tuning Lab regroup axis) rides on.

### Do NOT auto-bump across this boundary

We are pinned at the SHA in `scripts/upstream.pin` and ship from it. Staying
pinned is safe. Crossing to the rewritten core is the A/B/C fork decision in
subarr#171 — make it deliberately, not by bumping the pin.

### Act on it

1. Read the current **migration-bill preview** in the `drop-stable-ts-preview`
   job summary (how many of our patches break against the new core).
2. Run the eval the #171 plan describes: transcribe the 4-lang arena set on
   the new base vs our pinned strongpad build, score on BOTH axes —
   segmentation CPS (deterministic) + translation faithfulness (qe_adequacy,
   the #123 judge).
3. Decide A (hold on our stable-ts fork) / B (follow, re-port ~17 patches) /
   C (contribute a CPS-padding pass to the Netflix segmenter upstream).
4. Whichever path: the just-shipped `CUSTOM_REGROUP` deploy default becomes a
   no-op on the new base — revert/replace it when we cross.

Full context, decision data, and the 17/20 patch-break analysis live in
**subarr#171**.
