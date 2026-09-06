# Rename map

This is the single-word rename plan for the Twelve-Hard-Rules refactor.
It is generated from a Phase 0 audit of ``app/``, ``scripts/``, and
``tests/``. Every rename in Phase 2 must trace back to an entry here.

## Filenames

### Test files (Rule D — no ``test_*.py``)

The accepted convention under Rule D is option 2 — one ``tester.py``
per package with single-word test methods on a single ``Checker``
class. The consolidation script at ``tests/_consolidate.py``
performs the merge; pytest config in ``pyproject.toml`` is:

```
python_files = ["tester.py"]
python_classes = ["Checker"]
python_functions = ["*"]
```

The two consolidated files are ``tests/unit/tester.py`` and
``tests/integration/tester.py``. Each top-level test function in the
old ``test_*.py`` files becomes a ``Checker`` method with a single-word
name. The convention produces N classes per package — one per source
module — each carrying only the methods that exercise it.

### Single-word module renames

| Before | After | Reason |
|---|---|---|
| ``app/inference/regex_detector.py`` | ``app/inference/regex.py`` | drop compound suffix |
| ``app/audit/local_file.py`` | ``app/audit/file.py`` | drop compound prefix |
| ``app/redaction/stages/regex_gate.py`` | ``app/redaction/stages/gate.py`` | drop compound suffix |
| ``app/redaction/stages/model_stage.py`` | ``app/redaction/stages/model.py`` | drop compound suffix |
| ``app/redaction/stages/fallback.py`` | ``app/redaction/stages/fallback.py`` | already single-word |
| ``app/redaction/stages/consensus.py`` | ``app/redaction/stages/consensus.py`` | already single-word |
| ``scripts/convert_ai4privacy.py`` | ``scripts/convert.py`` | drop compound suffix |
| ``scripts/eval_detectors.py`` | ``scripts/eval.py`` | drop compound suffix |
| ``scripts/download_models.py`` | ``scripts/download.py`` | drop compound suffix |

## Classes

| Before | After | Reason |
|---|---|---|
| ``BatchItem`` | ``Item`` | drop compound prefix |
| ``BatchRequest`` | ``Request`` | drop compound prefix |
| ``BatchResponse`` | ``Response`` | drop compound prefix |
| ``RegexDetector`` | ``Regex`` | drop compound suffix |
| ``GLiNER2Detector`` | ``Detector`` (rename to neutral) | drop compound prefix; see note |
| ``MultiPass`` | ``Pass`` | drop compound suffix |
| ``OpenMedPIIDetector`` | ``Detector`` (rename to neutral) | drop compound prefix; see note |
| ``RedactionResult`` | ``Result`` | drop compound prefix |
| ``StrategyResult`` | ``Result`` | drop compound prefix |
| ``FusedEntities`` | ``Entities`` | drop compound prefix |
| ``EntityScore`` | ``Score`` | drop compound prefix |
| ``StageOutcome`` | ``Outcome`` | drop compound prefix |
| ``PipelineResult`` | ``Result`` | drop compound prefix; collision with ``RedactionResult`` resolved by dropping both |
| ``PipelineStage`` | ``Stage`` | drop compound prefix |
| ``ConsensusConfig`` | (delete; not consumed) | dead code |
| ``CircuitOpenError`` | ``OpenError`` | drop compound prefix |
| ``CircuitStats`` | ``Stats`` | drop compound prefix |
| ``CircuitBreaker`` | ``Breaker`` | drop compound prefix |
| ``AnnotationInput`` | ``Input`` | drop compound prefix |
| ``LabelledSpan`` | ``Label`` | drop compound prefix; ``Span`` is taken by ``app.inference.detector.Span`` |
| ``SpanCategory`` | ``Category`` | drop compound prefix |
| ``PairRange`` | ``Range`` | drop compound prefix |
| ``SpanGroup`` | ``Group`` | drop compound prefix |
| ``ConnectorStructure`` | ``Structure`` | drop compound prefix |
| ``UnitRating`` | ``Rating`` | drop compound prefix |
| ``DisagreementReport`` | ``Report`` | drop compound prefix |
| ``PassThrough`` | ``Skip`` | drop compound; semantics are "emit input unchanged" |
| ``AuditEvent`` | ``Event`` | drop compound prefix |
| ``LocalFileAuditBackend`` | ``FileAudit`` | drop compound prefix |
| ``AutoDeID`` | ``Deid`` | drop compound prefix (acronym still allowed) |
| ``Pipeline`` | ``Pipeline`` (keep, but rename methods) | already single-word |

Note on GLiNER2Detector / OpenMedPIIDetector: only one detector is
instantiated per process, so the two classes share a single
``Detector`` name resolved at runtime from ``settings.detector``.

Note on ``LabelledSpan``: ``app.inference.detector.Span`` already owns the
name ``Span``. The renamed bench class uses ``Label`` to avoid the
collision; ``Label`` is the cleanest single-word description of the
concept (a character-level span with a category label attached).

## Methods

The verb-noun compounds below become single verbs; the noun becomes
the ``self``. Examples drawn from the existing source.

### ``app/inference/regex_detector.py::RegexDetector``

| Before | After |
|---|---|
| ``detect(text, entity_types)`` | ``run(text, kinds)`` |
| ``warmup()`` | ``start()`` |

### ``app/inference/gliner2.py::GLiNER2Detector``

| Before | After |
|---|---|
| ``detect(text, entity_types)`` | ``run(text, kinds)`` |
| ``warmup()`` | ``start()`` |
| ``load()`` | ``read()`` |

### ``app/inference/multi_pass.py``

| Before | After |
|---|---|
| ``multi_pass_detect(detector, text, passes)`` | ``run(detector, text, passes)`` |

### ``app/redaction/redactor.py::Redactor``

| Before | After |
|---|---|
| ``detect(text, policy, entity_types)`` | ``run(text, policy, kinds)`` |
| ``apply_strategy(strategy, text, value)`` | ``use(strategy, text, value)`` |

### ``app/redaction/strategy.py``

| Before | After |
|---|---|
| ``apply(text, value)`` | ``run(text, value)`` |
| ``PassThrough.apply`` | ``Skip.run`` |
| ``Mask.apply`` | ``Mask.run`` |
| ``Hash.apply`` | ``Hash.run`` |
| ``Regex.apply`` | ``Regex.run`` |
| ``AutoDeID.apply`` | ``Deid.run`` |

### ``app/redaction/pipeline.py::Pipeline``

| Before | After |
|---|---|
| ``run(text)`` | (keep; the only public entrypoint) |

### ``app/audit/local_file.py::LocalFileAuditBackend``

| Before | After |
|---|---|
| ``record(event)`` | ``save(event)`` |
| ``start()`` | ``open()`` |
| ``stop()`` | ``close()`` |

### ``app/redaction/circuit/breaker.py::CircuitBreaker``

| Before | After |
|---|---|
| ``call(fn, *args, **kwargs)`` | ``invoke(fn, *args, **kwargs)`` |
| ``stats()`` | ``report()`` |

### Test methods (in ``tests/unit/tester.py``)

Every test method is renamed to a single word. The most natural
single-word verb or noun is extracted from the original name; collisions
within a class fall back to a 4-char digest suffix on the same root.

## Variables

| Before | After | Reason |
|---|---|---|
| ``max_value`` | ``peak`` | drop compound |
| ``user_count`` | ``count`` | drop compound |
| ``is_valid`` | ``valid`` | drop ``is_`` prefix |
| ``has_more`` | ``more`` | drop ``has_`` prefix |
| ``should_run`` | ``run`` | drop ``should_`` prefix |
| ``failure_threshold`` | ``threshold`` | drop compound |
| ``model_cache`` | ``cache`` | drop compound (only one cache) |
| ``max_text_chars`` | ``peak_chars`` | drop compound |
| ``max_retries`` | ``peak_tries`` | drop compound |
| ``request_timeout_seconds`` | ``timeout_s`` | drop compound |
| ``cache_ttl_seconds`` | ``ttl_s`` | drop compound |
| ``hash_salt`` | ``salt`` | drop compound |
| ``stream_chunk_bytes`` | ``chunk_bytes`` | drop compound |
| ``stream_chunk_chars`` | ``chunk_chars`` | drop compound |
| ``pipeline_breaker_threshold`` | ``breaker_threshold`` | drop compound |
| ``pipeline_breaker_cooldown_s`` | ``breaker_cooldown_s`` | drop compound |
| ``text_hash`` | ``digest`` | drop compound |
| ``default_cache_is_isolated_per_salt`` | (delete) | descriptive comment, not test logic |

## Module-level constants

| Before | After |
|---|---|
| ``_PUNCT_EXCLUDED`` | ``PUNCT`` |
| ``_ASCII_LETTERS`` | ``LETTERS`` |
| ``_ASCII_DIGITS`` | ``DIGITS`` |
| ``_PAIR_OPEN_TO_CLOSE`` | ``PAIRS`` |
| ``_PAIR_OPENERS`` | ``OPENERS`` |
| ``_PAIR_CLOSERS`` | ``CLOSERS`` |
| ``_PAIR_SYMMETRIC`` | ``SYMMETRIC`` |
| ``_GAP_THRESHOLD`` | ``GAP_THRESHOLD`` |
| ``MAX = 3`` | (keep; already single CAPS) |
| ``TIMEOUT = 30`` | (keep; already single CAPS) |
| ``OPENMED_MODEL_NAME`` | ``OPENMED`` |
| ``OPENMED_SHA256_MANIFEST_KEY`` | (delete; unused) |

## Forbidden dunders (Rule C — semi-private)

Every leading-underscore identifier in ``app/`` and ``scripts/`` is
renamed to a public name. Examples:

- ``app/redaction/apply.py::_dedupe_overlaps`` → ``dedupe``
- ``app/bench/combinators.py::_is_punct_char`` → ``is_punct``
- ``app/bench/combinators.py::_is_whitespace`` → ``is_space``
- ``app/bench/combinators.py::_span_text`` → ``text_of``
- ``app/bench/combinators.py::_is_digit_only`` → ``is_digits``
- ``app/bench/combinators.py::_iter_neighbor_pairs`` → ``neighbors``
- ``app/bench/combinators.py::_red_edges`` → ``collect_punct_edges``
- ``app/bench/combinators.py::_pair_ranges`` → ``detect_pairs``
- ``app/bench/combinators.py::_connected_components`` → ``components``
- ``app/bench/disagreement.py::_pairwise_disagreement`` → ``pairwise``
- ``app/bench/fusion.py::_intersect`` → ``overlaps``
- ``app/bench/fusion.py::_marker_positions`` → ``marker_positions``
- ``app/bench/rscore.py::_prediction_chars`` → ``char_runs``
- ``app/bench/rscore.py::_support_runs`` → ``support_runs``
- ``app/bench/rscore.py::_false_positive_runs`` → ``fp_runs``
- ``app/bench/rscore.py::_gap_runs`` → ``gap_runs``
- ``app/bench/rscore.py::_coverage`` → ``coverage``
- ``app/bench/rscore.py::_percentile`` → ``percentile``
- ``app/bench/rscore.py::_covers_entire_gap`` → ``covers_gap``
- ``app/redaction/circuit/breaker.py::_allow_call`` → ``allow``
- ``app/redaction/circuit/breaker.py::_on_success`` → ``on_success``
- ``app/redaction/circuit/breaker.py::_on_failure`` → ``on_failure``
- ``app/redaction/stages/model_stage.py::_run_async`` → ``await_async``
- ``app/inference/regex_detector.py::_Rule`` → ``Rule``

Allowed dunders (Python protocol) are not renamed: ``__init__``,
``__repr__``, ``__str__``, ``__eq__``, ``__hash__``, ``__lt__``,
``__le__``, ``__gt__``, ``__ge__``, ``__iter__``, ``__next__``,
``__len__``, ``__getitem__``, ``__setitem__``, ``__delitem__``,
``__contains__``, ``__enter__``, ``__exit__``, ``__call__``,
``__add__``, ``__sub__``, ``__mul__``, ``__truediv__``,
``__floordiv__``, ``__mod__``, ``__pow__``, ``__matmul__``,
``__neg__``, ``__pos__``, ``__abs__``, ``__invert__``,
``__bool__``, ``__int__``, ``__float__``, ``__complex__``,
``__index__``, ``__round__``, ``__trunc__``, ``__floor__``,
``__ceil__``, ``__post_init__``, ``__class_getitem__``.
