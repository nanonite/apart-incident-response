# P02 — Freeze next-family scope and artifact inventory

Task: Chainlink **#203** under **#201** under **#159**. Offline scope freeze
only — no provider call, no collection, no registration lock, no live run.
Protocol: [hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
Family: `hypothesis:low` (the next-family pilot identified in P01). This task
closes with evidence only; nothing here authorizes collection, registration
locking, or any successor execution.

Frozen scope record (machine-readable):
[`runs/next-phase/jev-p02-scope-freeze.json`](runs/next-phase/jev-p02-scope-freeze.json)
with self-recorded `content_hash`
`4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b`.
The record lives outside `runs/epic-126/` so the frozen #200 audit's
byte-reproducibility (which scans `runs/epic-126/**`) is preserved.

## 1. Candidate order and structural rule (frozen)

**Rule (declared before any live outcome, carried from the #200 frozen
audit):** among the non-planning families, take the
**alphabetically first (bytewise ascending) non-planning family** that passes
three offline structural preconditions — closed finite solution set,
A-finalizer structurally needs the peer clue, and at least one B-owned claim
that is informative for A.

**Recorded candidate order:** `hypothesis` (selected), then `legal`,
`lexicon`, `poetry`, `reference`, one at a time, subject to the plan's gates.
`planning` is excluded by requirement (this must be a new family). The rule
cannot encode a preference, so the choice carries no information about
favourability. **No outcome-based reordering or search for a winning family;
no family may be added to or removed from the recorded order after outcomes
are visible.**

The frozen #200 audit's `family_selection` records the structural evaluations
for all five candidates (each: closed finite solution set, finalizer needs
peer, informative B-owned claims; `hypothesis` selected). The full evaluation
table is preserved in
[`runs/epic-126/replication/jev-replication-form-audit-v1.json`](runs/epic-126/replication/jev-replication-form-audit-v1.json)
and is not repeated here.

Frozen input pins (recomputed for this task, matching the #200 artifacts):
`audit_content_hash`
**`5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83`** and
`preregistration_hash`
**`ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d`**.

## 2. Prior-manifest inventory (with hashes)

Every prior artifact that records communication instance ids or seeds, with
sha256 recomputed from disk at freeze time. The inventory covers the #200
`prior_sources` baseline (119 files) plus the two #200 owned files (the frozen
audit and draft registration, which the #200 module's scan skips as owned
paths) plus ten `runs/discovery-145/` files outside the #200 scan scope:
**131 files, 74 with instance ids**. Inaccessible and unaccounted manifests
are recorded explicitly, never as empty sets.

| file | sha256 | ids | seeds | role |
|---|---|---|---|---|
| `runs/container-isolation.json` | `inaccessible` | — | — | container isolation record |
| `runs/discovery-145/anchor_screen/rows.json` | `10b76d63782436d4bc43b6468a1ad0ba8fac29a8be94a55bd476bc11fddbaa8c` | 4 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/anchor_screen/runs.jsonl` | `080f638919d92689e5121ef285a829d908edd69d674493e4d1ec9d2e136c8401` | 4 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/comparison/analysis.json` | `f64e1ab02be06bfbc45e0741e7a01971ee37b1879d5ccf0df54d297c7d03c075` | 4 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/comparison/per_run_data.json` | `3299929ff7c2c996eb6933f68e77bcd0a34ea50d677034fe20e7bba1e83a49f0` | 4 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/extended_screen/rows.json` | `6811ff41c0bf5dc367f58c8e1607c0870462b6e7ed34412537740b0144deb267` | 8 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/extended_screen/runs.jsonl` | `12c3a5169ee39c1b94a4e86224c5abaa46fdad21d52c9bf18a50e8c6417489c1` | 8 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/six_family/analysis.json` | `e4e38a4154e278b6b35750f3736c43eab7ecc562990bbece383dae00bf023192` | 12 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/six_family/per_run_data.json` | `c8d040d0c3228d4f0939203fd979a3a1322f59586f4ac679d11e7e5df836bf42` | 12 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/transfer/rows.json` | `ab0be08218db49c0dbefa86619871270d3a621dc75edbf50da3b6103de35e961` | 4 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/discovery-145/transfer/runs.jsonl` | `8c624a38205a8e293eff109bd76a9c8a55bd900d6f96db2a47dbc978bef7da08` | 4 | 101–102 | discovery-145 invalidated one-turn protocol artifact |
| `runs/epic-126/channel-audit.json` | `781b0e6851f1aec3df630b0829eee64b027ceba59ce4a1ab30a46a3ca335e4f7` | 54 | 16000–17202 | channel audit |
| `runs/epic-126/cneed-fourfamilies-n9-diagnostic.json` | `012a6dbe160d99aef1a720fd5b586b94e67578569fd059e992a8dc2764f1d1a9` | 0 | — | C_need screen record |
| `runs/epic-126/cneed-fourfamilies-n9-report.json` | `c071a02ec80f7beeedfa959c378b7d5b60768f196b14b7e9209607a3f10adead` | 0 | — | C_need screen record |
| `runs/epic-126/cneed-fourfamilies-n9.jsonl` | `b9c230d6f3d970f9bee338480b429a38df79a962903e33019e8fd90696085335` | 72 | 16400–17108 | C_need screen record |
| `runs/epic-126/cneed-n20-diagnostic.json` | `e28b1e1aeaa1933e33df4e739bbe0ae995837f5e22e99ca85ee2c86fc718f990` | 0 | — | C_need screen record |
| `runs/epic-126/cneed-n20-report.json` | `c036e08e7b8b92e4c814ae7a7e07b230cccc5fbc2aea76f1493c6399c68e449e` | 0 | — | C_need screen record |
| `runs/epic-126/cneed-n20.jsonl` | `0f752f03a327457576cf659ee7ccdf0c234eef2cd76bdea4ef3ee26bd8b7a684` | 80 | 16000–16319 | C_need screen record |
| `runs/epic-126/cneed-n9-diagnostic.json` | `3f840539dccf3d4af93e7a080c9748e4d4d652feec24cc03adc49991a8fde2eb` | 0 | — | C_need screen record |
| `runs/epic-126/cneed-n9-report.json` | `0bd3f45be32be7216e14a8d607287abbe869ac6c71e975e35062f5fa7aa64f30` | 0 | — | C_need screen record |
| `runs/epic-126/cneed-n9.jsonl` | `85001f08f42e4d418e349296e1e3cb65b30578a3cabfedac4369e5f3cf7285bf` | 36 | 16000–16308 | C_need screen record |
| `runs/epic-126/comm-n20-diagnostic.json` | `a1b533cdda8d4095d0b3b328be05fa8e312ced7f9cbd067ca9be086a63b983fb` | 0 | — | communication screen record |
| `runs/epic-126/comm-n20-report.json` | `1e564c11d29f0939644210d7e37c18e2533dffdbb168276b9582757f442f8e66` | 0 | — | communication screen record |
| `runs/epic-126/comm-n20.jsonl` | `9d16660c036114f9bfc2c27c43b11fba11d93af48b0efa44cd3f4436896780aa` | 80 | 16000–16319 | communication screen record |
| `runs/epic-126/comm-planning-n9-diagnostic.json` | `b3c133e6fb241e7b2a02bb0cae900ce813bb3d67d1d9c2f8596d27cfa3464445` | 0 | — | communication screen record |
| `runs/epic-126/comm-planning-n9-report.json` | `92faddb4efb719b0e012b0fe5ea1021cf25cdd1c0c0a24f162b8058770743bc1` | 0 | — | communication screen record |
| `runs/epic-126/comm-planning-n9.jsonl` | `7a2d1f1afc428d6bc0719da889547a252832dd7ef0d05b0aa4d2e8629ac0d959` | 18 | 16400–16508 | communication screen record |
| `runs/epic-126/confirmatory-v3-diagnostic.json` | `ab83e6c7e324c651ffdd19cd81d2c289be7f21e9911591fdc5d84e8903bd3ebc` | 0 | — | confirmatory v3 record |
| `runs/epic-126/confirmatory-v3-report.json` | `d3a418b1128a16ef974fac8b43420161cbfe662ad2e46bfe0cafd9468cc562f5` | 0 | — | confirmatory v3 record |
| `runs/epic-126/confirmatory-v3.jsonl` | `1c1e93ed2979ec3be50be69d8f82c8c302cde0cfbad9d46d2ed7efb0868c585e` | 85 | 50000–72016 | confirmatory v3 record |
| `runs/epic-126/decisions/jev-v7-coverage-decision.json` | `3f45b8bf35ca87fe59d754c8426b256ed76aeab8e94a37881e7a768a1be5431b` | 18 | 75000–75037 | coverage decision |
| `runs/epic-126/diagnostics/jev-provider-diagnostics-preregistration-v1.json` | `ad150f7fcb5b1b502261e43d41d7a7a1d58c874133a28e519df99afd1be16e5b` | 0 | — | diagnostic/report record |
| `runs/epic-126/diagnostics/jev-transport-probe-v1.json` | `5dc85056ac9525e7303ef9491dc6758f4c12fd2ce03139fa29cb46abb668876e` | 0 | — | diagnostic/report record |
| `runs/epic-126/diagnostics/ling-transport-probe-v1.json` | `b82f09436f2272d6e392bb38efbcc999e7a2ef48eafbc179c9fde0e4b98eed95` | 0 | — | diagnostic/report record |
| `runs/epic-126/full-gate-1024-diagnostic.json` | `67683a62e55c60cbb196a35506a3db0eee522818991ff43ddadcd77e0bb9d39a` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-1024-report.json` | `22a7fc281c39781ee7ac2758e00d9973d1ce22f965d1967dfce96afa07fe32d8` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-1024.jsonl` | `caee03cae5f9d8f2e6d43535a670bc2ecde421f9e8a6a738d18dd4782eb2501a` | 8 | 15000–15007 | full-gate record |
| `runs/epic-126/full-gate-budget512-diagnostic.json` | `b82acf683657d4dd456e715bdf6f5259f78aebca042d03026cb9d221fe1b5f8a` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-budget512-report.json` | `380013b13b7ac3f49f1ffad889bf09f5f2b2d7d159559727103e792a649c30a8` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-budget512.jsonl` | `66342b132b89d132fb8ab712fc791e39b22a4b534a96d0dfb070f32a980c7b22` | 8 | 15000–15007 | full-gate record |
| `runs/epic-126/full-gate-diagnostic.json` | `847fd32e4e86979f253d9e4f703952201f790d4886f7cbfbb9fc5374cfb31074` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-hypmed-1024-diagnostic.json` | `4c6bd725ed02bf307d40d2aca53ff40dc18e1c9d10b30036f5d8c7493a6b5150` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-hypmed-1024-report.json` | `ecbad08d66475cc0651d0c51227c5f4b24116e940cf1f1792f2a49c631a92709` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-hypmed-1024.jsonl` | `ff743ca5f227c85e0e5b22809d38c7338b016a87e520848f31e6a39e9d452c4f` | 2 | 15002–15003 | full-gate record |
| `runs/epic-126/full-gate-repair-diagnostic.json` | `8fdbea825389fe4dee309298be7d0b36e9e9350b1ec33cfb25381d37de626cf2` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-repair-preflight.json` | `d87c988b79a4ea96406c33a641d1dd374651896995932d74c568a95db3454378` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-repair-report.json` | `a18227a9842107db37ea2f1ff3051c4682262f17379edc3ab6949f4ef963ce12` | 0 | — | full-gate record |
| `runs/epic-126/full-gate-repair.jsonl` | `a695f35de69ec3e960c0787d2f63e731c95fadc840ee9f20949344e3c55af42a` | 8 | 15000–15007 | full-gate record |
| `runs/epic-126/full-gate-report.json` | `1a4d12d9cc4a7f8e57bae043b38c6213a4fad62dd15b7d4cbda1c56130388a6a` | 0 | — | full-gate record |
| `runs/epic-126/full-gate.jsonl` | `cbfdfc9fa49350781c258adf6659f8661320bf8935bb210d031b0251193269b6` | 8 | 15000–15007 | full-gate record |
| `runs/epic-126/jev-board-necessity-selection.json` | `78dba91926c0134c772c85020ab1a503c8785ddbb34031528a0231297641627a` | 34 | 71000–72016 | board-necessity selection screen |
| `runs/epic-126/jev-cell-selection-v1.json` | `7cb2e5098445b45695b8c388aa8134048dd1a11afd1dbb7f1d6e752c30d614f0` | 17 | 72000–72016 | cell selection record |
| `runs/epic-126/jev-choice-adapter-fixture.json` | `a4e92cd5c81895a90b3eb75dd84012fd94e6a4ed139fc4e8564a5aa42b97d14b` | 1 | 70000–70000 | adapter fixture |
| `runs/epic-126/jev-choice-capability-preregistration.json` | `4248c1311ed665775a22fb7ca4c091ea2b7a5e9bbb57cbca90b8de5cefba0777` | 17 | 71000–71016 | choice capability record |
| `runs/epic-126/jev-choice-capability-report.json` | `a33310c743c20e474e6aef58e60b82faa54db9186b6f06047c91710d1aab5f7c` | 17 | 71000–71016 | choice capability record |
| `runs/epic-126/jev-choice-capability.jsonl` | `5f598997f0a8bd760d58cb73ae156757ed171905a7375722b749f06837163600` | 17 | 71000–71016 | choice capability record |
| `runs/epic-126/jev-choice-normalization-diagnostics-v2.json` | `5e5633db5b974b3f6d361860cbf90807158b66683fd24fca43f91b239c7bb652` | 0 | — | diagnostic/report record |
| `runs/epic-126/jev-choice-normalization-probe-report-v2.json` | `678a916e1b63346706694b550a5c08bdfed4b60028280a478fb9820e77fc507b` | 0 | — | diagnostic/report record |
| `runs/epic-126/jev-choice-normalization-probe-v2.json` | `c86ee96162e5691226156f141506e89c322e54c2629c5ae764edf3cc78e32d54` | 0 | 72000–72000 | diagnostic/report record |
| `runs/epic-126/jev-choice-normalization-probe-v2.jsonl` | `bcf15eb61294faebcccafc2ffd282166d6566daccecfeaf0eb3c591231aad8f9` | 0 | — | diagnostic/report record |
| `runs/epic-126/jev-choice-pilot-report-v2.json` | `95f3aa9e7f520d116203a9c5c267c69f2ab20e5a063f066d105516b7186a51f6` | 13 | 72000–72012 | choice pilot record |
| `runs/epic-126/jev-choice-pilot-report-v3.json` | `3db82c84ebffdc2d733b2c11076e39c9d33fd90549d5f30fb59e41865c9a5e57` | 17 | 72000–72016 | choice pilot record |
| `runs/epic-126/jev-choice-pilot-report.json` | `be9b944d08a9d27b98cb2b14e86f28cad5c10d4140aee82d743bf540bd1fc52a` | 1 | 72000–72000 | choice pilot record |
| `runs/epic-126/jev-choice-pilot-v2.jsonl` | `fdcb3b1eddc4afa351472b7abf29234bb08106f88b802885088152aebab5d5dc` | 13 | 72000–72012 | choice pilot record |
| `runs/epic-126/jev-choice-pilot-v3.jsonl` | `e8f93fc560e9fb6b55c85e3879df513c1a28fae564f3d79ae91eb51c83d43494` | 17 | 72000–72016 | choice pilot record |
| `runs/epic-126/jev-choice-pilot.jsonl` | `50c679672b69c969ffc3cc2d89b341dbe9d99d5deb2ebb1dbd1f7df4e0405933` | 1 | 72000–72000 | choice pilot record |
| `runs/epic-126/jev-choice-replay-preregistration-v2.json` | `f4e68dadcd570789e30b46f41282201f7b5a0377c941f9d717a0699ca8fa5ee0` | 17 | 72000–72016 | replay preregistration |
| `runs/epic-126/jev-choice-replay-preregistration-v3.json` | `fbb4eecc7c5765974bdbaaa4de46cc1006d456aafc70263899cd8c00114567c9` | 17 | 72000–72016 | replay preregistration |
| `runs/epic-126/jev-choice-replay-preregistration.json` | `241591d24acc38ada2b236270adac6dba91fc9c3b190cc7afecd9436fc08675d` | 17 | 72000–72016 | replay preregistration |
| `runs/epic-126/jev-choice-wire-smoke-golden.json` | `3ec021ba7c265a88d48018ecee4c744b6f4ac6f70050f7527dd9b8b3b1b22395` | 0 | — | wire smoke record |
| `runs/epic-126/jev-choice-wire-smoke-report.json` | `d969753506ab091706067bf0470f5cbba1163a0bb00d480f48b46ff49326e8e6` | 2 | 70000–70001 | wire smoke record |
| `runs/epic-126/jev-coverage-manifest-preregistration-v6.json` | `63be1ccbff954cd4c55be303d3a9569e592b336a976c6fcc824fb2fbcda1c9f5` | 36 | 75000–75056 | diagnostic/report record |
| `runs/epic-126/jev-coverage-manifest-preregistration-v7.json` | `289d83fee5c8fcdc3c1aaa29b104850d696a3d98c32cf291e300dbf89edd5e94` | 36 | 75000–75056 | diagnostic/report record |
| `runs/epic-126/jev-coverage-manifest-report-v6.json` | `a6f5253cbef7aa4534df3520aaa88a7e3918bb97903a3f2ff264013edb6b195c` | 36 | 75000–75056 | diagnostic/report record |
| `runs/epic-126/jev-coverage-manifest-report-v7.json` | `456515559c65faf976ce1063107a2d4036c7f6d06f0e9bf7e9b1f87b89b1088f` | 36 | 75000–75056 | diagnostic/report record |
| `runs/epic-126/jev-coverage-manifest-v6.jsonl` | `f5a7a0d8c1f54a0e65864ca3e2ba9589d22be3989639fa50b98202aaa1d6c364` | 1 | 75000–75000 | v6 coverage manifest |
| `runs/epic-126/jev-coverage-manifest-v7.jsonl` | `23ab961c8f4327a98af821d5457b94f278c1f0993bc027953a86bbc36081ebc5` | 32 | 75000–75037 | v7 coverage manifest |
| `runs/epic-126/jev-ling-transport-probe-v7.json` | `06d22e8741ee490b93c7c6f78535c480f4f67a8f53f3ac1ca589f3d639abb534` | 0 | — | diagnostic/report record |
| `runs/epic-126/jev-planning-low-manifest.json` | `e70c79e170c16ebd5298d2c5e1aa875d7bde50ef29ad19e6cc55a9b0af178432` | 17 | 70000–70016 | planning-low discovery manifest (frozen #198/#199 evidence) |
| `runs/epic-126/jev-six-form-coverage-audit-v1.json` | `73751bed24776e851f76e63dec427dafc1b458624bc56efdf96612fcfc568dcb` | 17 | 72000–72016 | six-form coverage audit |
| `runs/epic-126/jev-writer-exact-bridge-report-v5.json` | `325206d9c51a56c10195265e7f699e78b57b762b9d243160d52cdd63c58aef2d` | 17 | 72000–72016 | writer exact bridge record |
| `runs/epic-126/jev-writer-exact-bridge-v5.jsonl` | `4ea9f91decba5c504bb2726e178f36ed6cd845bba635876c822aa72d53c9a5de` | 17 | 72000–72016 | writer exact bridge record |
| `runs/epic-126/jev-writer-ladder-preregistration-v4.json` | `a3dd6e2c8e60e64132c76668f4f5b79881e32936a816353d667a1f4250db4255` | 17 | 72000–72016 | writer ladder record |
| `runs/epic-126/jev-writer-ladder-preregistration-v5.json` | `42ab5784ec0f536159aedf8f8e83763197425633117d9b0fc0a2d08ecf9b3993` | 17 | 72000–72016 | writer ladder record |
| `runs/epic-126/jev-writer-treatment-audit-v4.json` | `387981ba69c4f2c73a93945316080f0aaa36dd60bed1522c62710dd8ff568f55` | 0 | — | diagnostic/report record |
| `runs/epic-126/paired-analysis-n20.json` | `bb6993e4f6fd70226e94b28f32033c819f2084356ad2119aaecd5a2763674a6a` | 0 | — | paired analysis record |
| `runs/epic-126/paired-analysis-planning.json` | `05a4b076d4c4b84f210bccc49de4066b2f6ccdc226a58f565e6917b11a9f7928` | 0 | — | paired analysis record |
| `runs/epic-126/paired-screen-diagnostic.json` | `a8f966dc4552893361dc590d8ba3fbec9ffe9aef99504e36ee748ff91e9cb5ce` | 0 | — | paired screen record |
| `runs/epic-126/paired-screen-n5-diagnostic.json` | `4cb064b0e9be1c26c213cb13e4a5a006ad0b7dbd01db8d021ba99c3006d172a3` | 0 | — | paired screen record |
| `runs/epic-126/paired-screen-n5-leakfree-diagnostic.json` | `1250884e965c483c70ef928bd6de7775ef0300cac887c76528a2b7bf4ff6e008` | 0 | — | paired screen record |
| `runs/epic-126/paired-screen-n5-leakfree-report.json` | `09a885c5839ee987b2632a37ff99ae70bcaa417bfacbb26034feb949bc692a1e` | 0 | — | paired screen record |
| `runs/epic-126/paired-screen-n5-leakfree.jsonl` | `9840b2b21d165e8adb39b312e3e805da7536dad0a821cc3f509921235a6fa5dc` | 20 | 16000–16304 | paired screen record |
| `runs/epic-126/paired-screen-n5-report.json` | `b3826e24193388e34a64baebd017880f218d47c9713135acf4cdaa2f63669a2f` | 0 | — | paired screen record |
| `runs/epic-126/paired-screen-n5.jsonl` | `72d368583c0f4889ca4d86d95ed449cc0c419b1e693c8b0dc9b48d2ef08724a4` | 20 | 16000–16304 | paired screen record |
| `runs/epic-126/paired-screen-report.json` | `ed476578fea09ef42d8a74f8d2a744b38ad9d9c95001473f6fbed7402401c95b` | 0 | — | paired screen record |
| `runs/epic-126/paired-screen.jsonl` | `cf8aff0a0330410a15f713376376db6caaf1faa185a5e5901fcc26131cbeca74` | 8 | 15000–15007 | paired screen record |
| `runs/epic-126/planning-high-v4-diagnostic.json` | `26d37e8cec86f125ec403cd0d9ab45b9f48f870159cc365f05b6c734aae98d72` | 0 | — | planning-high v4 record |
| `runs/epic-126/planning-high-v4-report.json` | `cd50ced252394470e9849e4252a90ad7dfd79de75dd76c99f3d5b321cc8bc95e` | 0 | — | planning-high v4 record |
| `runs/epic-126/planning-high-v4.jsonl` | `328e2c7cf49af1d4728143ccec37a66b9e61653d30d62d28d2e5b0bd43889cd3` | 17 | 80000–80016 | planning-high v4 record |
| `runs/epic-126/preregistered-manifest.json` | `23a806407e6d1a84d8c0a824069f0c3c84c03fd4984909e6c76edaab71e14fa1` | 240 | 16000–17119 | preregistered six-family manifest |
| `runs/epic-126/preregistration-planning-high-v4.json` | `670a8ab1d42e8001a993b1d63576c18f89bcaa1d6e4c03ef2ae43a331d8ed112` | 27 | 19000–80016 | preregistration record |
| `runs/epic-126/preregistration-v1.json` | `12d94515fb7d2bd8c88ec8e64842218c2077c2f2e79bd1801962c8de55978abf` | 10 | 19000–41001 | preregistration record |
| `runs/epic-126/preregistration-v2.json` | `884bdabae076cc1e01605206cce085d0dbdb4f1fab7b36c7e5090ec9f034a4ec` | 10 | 19000–41001 | preregistration record |
| `runs/epic-126/preregistration-v3.json` | `16d11be0521fdfc41c03e4a7fae8afffe6730d235e971f6a8dda4e04dbfd4ada` | 95 | 19000–72016 | preregistration record |
| `runs/epic-126/replay-v4/jev-choice-replay-preregistration-v4.json` | `5ea64f8218ed1ddabb2cab5a081dea666e686683a2a67ea9a186a9409ea40ee2` | 17 | 75000–75036 | replay preregistration |
| `runs/epic-126/replay-v4/jev-choice-replay-report-v4.json` | `71a7f2c401bb67d5db5d0758188531361ae42cd6aedd4de92d3100c727f3a8a2` | 17 | 75000–75036 | diagnostic/report record |
| `runs/epic-126/replay-v4/jev-choice-replay-v4.jsonl` | `5a870d5f643f3716c70b8350ab19ff256834f9079e6364931661630587b24b62` | 1 | 75000–75000 | diagnostic/report record |
| `runs/epic-126/replay-v5/jev-choice-replay-inference-v5.json` | `b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce` | 17 | 75000–75036 | diagnostic/report record |
| `runs/epic-126/replay-v5/jev-choice-replay-preregistration-v5.json` | `3c02f8bb44c11d6edd050daf32950e3cf8365f79638e92d46181df764945ddd7` | 17 | 75000–75036 | replay preregistration |
| `runs/epic-126/replay-v5/jev-choice-replay-report-v5.json` | `0ec84446d697bca91c25e155b3cd61f43b4e7706e6df185ea08c3685a8f88310` | 17 | 75000–75036 | diagnostic/report record |
| `runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl` | `5e9f7322bdb29baf16b18f9b4f4181e9a88ad454e0394ea379e4cdea29b1fede` | 17 | 75000–75036 | diagnostic/report record |
| `runs/epic-126/replication/jev-replication-form-audit-v1.json` | `cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d` | 32 | 85000–87032 | #200 frozen form-capacity audit |
| `runs/epic-126/replication/jev-replication-preregistration-v1.json` | `bddf46ed5fd87ec4da99532d645580a65e250d64639de80477002ff73d278f3c` | 32 | 85000–87032 | #200 frozen draft registration |
| `runs/epic-126/stage2-attempt-state.json` | `5b70e6eb63b595cda28f2a65457f7ac9e4298f32396272cd9c929ff375f882c8` | 10 | 19000–41001 | stage2 smoke record |
| `runs/epic-126/stage2-smoke-combined-analysis.json` | `ddb2c75032dfa7ce7da313b47e6d9960ad477f1c51df68c77587adfac5283cb1` | 0 | — | stage2 smoke record |
| `runs/epic-126/stage2-smoke-diagnostic.json` | `386ba39fd99d1df3481271b12b70410b1b67761eee29865070a71b7e7fa2dfc0` | 0 | — | stage2 smoke record |
| `runs/epic-126/stage2-smoke-report.json` | `7823e3d8d385d148b122e7ac3672d3b997f30c1bbbd430e07eddba7bf8e9096a` | 0 | — | stage2 smoke record |
| `runs/epic-126/stage2-smoke-resume1-diagnostic.json` | `9cbc69b3e8a3490e17718021a9aaeecba394fe636db63790c93b306dbb52ebcf` | 0 | — | stage2 smoke record |
| `runs/epic-126/stage2-smoke-resume1-report.json` | `99a862514806631fd4e9ed73c410d42710a97138727493da465dd06b4530c9fd` | 0 | — | stage2 smoke record |
| `runs/epic-126/stage2-smoke-v2-diagnostic.json` | `b44d29057bc9ce7752dd79336a4029a45f267c9aa1a6bde05c1503281fa66e5c` | 0 | — | stage2 smoke record |
| `runs/epic-126/stage2-smoke-v2-report.json` | `f3221ba453ecf07b589b7f71dd4f0abb703a7294e72f70f7bb3c26df9f4a9e1c` | 0 | — | stage2 smoke record |
| `runs/epic-126/stage2-smoke-v2.jsonl` | `caf6d637d366f9b603f9a0fb9537321e7e63d71057e4402ebc133b5e2af1d518` | 10 | 19000–41001 | stage2 smoke record |
| `runs/epic-126/stage2-smoke.jsonl` | `651021dec97385d413f8131edbd56725a73f2cfc906adfb7c4d110533d125a0f` | 1 | 19000–19000 | stage2 smoke record |
| `runs/epic-126/t1-pressure-catalog.json` | `f720faf4a47c16d2dcae71aad57cde4e3d929f96864517fe8f5c102623b891af` | 0 | — | diagnostic/report record |
| `runs/epic-126/t1-retained-pilot-audit.json` | `7d6093210404c0ad16ad8eaaccc8289b1d6fe91ab36dce78bddfa2c24ab8b6fb` | 0 | — | diagnostic/report record |
| `runs/epic-126/t1-screen-report.json` | `10c7eb8eb85e30a98092ae38689a5dc2ee293a66bff2c4e6e2122965f3113f34` | 0 | — | t1 screen record |
| `runs/epic-126/t1-screen-retry-report.json` | `31a5b1176ecb15830122dae3a914db3afa254949086ea7a36cff9e4c2ddfdabc` | 0 | — | t1 screen record |
| `runs/epic-126/t1-screen-retry.jsonl` | `4a73aa464369cf8c8c9df960438266bd33053b864c71a313166792f6cefe10a0` | 24 | 13000–13111 | t1 screen record |
| `runs/epic-126/t1-screen.jsonl` | `dbd76e1fda1707134d5ad8f71cd29d0c663cf03969579641b47c58678b9117a0` | 36 | 12000–12171 | t1 screen record |
| `runs/epic-126/t2-capability-report.json` | `387ebce749320624f8b78cf3b851fe91d94877bb8a478adf3f8b6ba4661ae8a5` | 0 | — | t2 capability report |
| `runs/epic-126/treatment-schema.json` | `22dd4e92c0dfaad6bbcd7e00d5b25eb8b9c6166fc9cd5e7160450e03802666ab` | 0 | — | diagnostic/report record |

**Documented prior seed ranges** (all families, all recorded blocks, carried
from the #200 frozen audit): 16000–17104, 39000–39001, 41000–41001,
70000–70016, 71000–71016, 72000–72016, 73000–73016, 74000–74016,
75000–75255, 80000–80016.

**Prior instance-id set (verified):** the frozen #200 module logic
reproduces `prior_instance_id_count` **8945** and
`prior_instance_ids_sha256`
**`429e8c54720d1a472d9e191fedc0510ade291680514f2dae4dff8c2a747607f9`** from
the current disk state, matching the #200 pin exactly (fail closed on drift).
The set comprises 8802 documented seed-range ids (1467 seeds × 6 families)
plus 143 file-recorded ids outside those ranges.

**Inaccessible / unaccounted manifests (recorded, never empty):**

- `runs/container-isolation.json` — permission-denied at P02 freeze time; its
  prior-instance-id contribution is covered by the #200 frozen pin.
- Permission-denied directories, unaccounted at freeze time: `runs/codex-c0`,
  `runs/container-harness`, `runs/opencode-go-container`,
  `runs/opencode-go-container-retry`, `runs/opencode-qwen-container`,
  `runs/openrouter/pilot-container{,-2,-3,-4}`, `runs/t1-container`,
  `runs/t1-container-retry`.

**discovery-145 note:** the ten `runs/discovery-145/` files are invalidated
one-turn protocol artifacts per their own `PROVENANCE.md`; their instance ids
(seeds 65–66, 101–102) do not overlap the proposed windows, and they are
outside the #200 scan scope. They are inventoried here for completeness; P03
rechecks current manifest coverage.

## 3. Proposed discovery and held-out seed windows

Proposed windows, carried from the #200 frozen audit/registration and frozen
here. All three are disjoint from every documented prior seed range and from
each other (verified offline).

| stage label | window | seeds | role | #200 block |
|---|---|---|---|---|
| `discovery` | 85000–85511 | 512 | discovery-stage seed census and manifest selection (P05–P07) | `primary` |
| `closure_probe` | 86000–86511 | 512 | offline closure test only; **no seed may be selected from it** (P03 recheck) | `closure_probe` |
| `held_out` | 87000–87511 | 512 | fresh-seed held-out block manifest (P08–P13) | `confirmation` |

**Explicit stage labels:**

- **`discovery`** — P05 lock discovery design and record live authorization;
  P06 collect discovery communication data; P07 estimate discovery results
  and prospective feasibility. The #200 `primary` block (85000–85511) is the
  discovery-stage window.
- **`closure_probe`** — offline-only closure test (86000–86511). No seed may
  be selected from it; not a live stage.
- **`held_out`** — P08 draft fresh replay registration; P09 replay preflight;
  P10 lock replay registration and record separate live authorization; P11
  collect held-out messages and matched replay; P12 offline primary
  inference; P13 guards, sensitivity and information accounting. The #200
  `confirmation` block (87000–87511) is the held-out window.

**Selection rule (frozen):** first `INSTANCES_PER_FORM = 4` seeds per form in
ascending seed order within the window; fixed N = 16 per block; no
outcome-based stopping. **No live outcome is used to choose forms or seeds.**
Distinct seed ids are not independent forms; the experimental unit is the
prompt form.

## 4. Design consequence (frozen)

`k_max = 4` for the `hypothesis` family (closed form space, saturated by 32
seeds, 0 new forms in the disjoint closure probe). The attainable exact
two-sided sign-flip floor is 2/2⁴ = **0.125 > 0.05**, so no dichotomous
rejection at α = 0.05 is attainable at any effect size on this family. The
pilot is preregistered as an **estimation and descriptive study**; no
significance-style claim is made, including for its fresh-seed replication
block. H0: Delta = 0; H1: Delta < 0; Delta is the equal-weight form mean of
real-minus-placebo entropy. Guards never filter the estimate; all forms and
missingness are reported without imputation. No planning-low effect-size
prior is used anywhere.

## 5. Checks (all offline, zero provider calls)

- Recomputed every sha256 in §2 from disk; all match the frozen scope record
  (fail closed on drift).
- Recomputed the prior instance-id set via the frozen #200 module logic:
  8945 ids, sha256 `429e8c54…`, matching the #200 pin.
- Verified the 119 #200 `prior_sources` files against disk: all present and
  readable except `runs/container-isolation.json` (permission-denied,
  recorded as inaccessible).
- Verified the three proposed windows are disjoint from all ten documented
  prior seed ranges and pairwise disjoint.
- Verified the candidate order and structural rule match the #200 frozen
  audit's `family_selection` (outcome-blind, `consulted_prior_live_outcomes:
  []`).
- Ran the #200 offline preflight verification: **49/49** named checks pass,
  `provider_calls: 0`, registration status `draft_pending_review`,
  `live_collection_authorized: false`.
- Ran the task-relevant test suites: `tests/test_jev_replication_preregistration.py`
  (50 tests), `tests/test_jev_p01_evidence_index.py`, and the new
  `tests/test_jev_p02_scope_freeze.py` that pins this document and the frozen
  scope record against the frozen artifacts; every suite asserts the frozen
  inputs byte-for-byte unchanged after running.
- No live output path exists or was created; the #200 live paths remain
  absent.

## 6. Handoff

P02 is complete with evidence paths, hashes, checks and this handoff. The next
concrete offline step is **P03 (#204)** — audit form capacity and
independence: versioned census, closure evidence, pre-read hashes,
shared-template/dependence assessment, per-form capacity, seed/ID overlap
report; deterministic rebuild, no overlap, unknown closure stated; reuse the
#200 audit as evidence, rechecking current manifest coverage against this
inventory. #204 is blocked by this task until the plugin records its closure.
A predecessor closed as failed does not authorize successor execution; this
task closes with evidence, and nothing in it authorizes collection, any
provider call, or any registration lock.
