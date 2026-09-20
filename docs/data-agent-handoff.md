# CSV meaning and display labels

The data agent sends the finished CSV and its `brief` together to `POST /datasets/upload`.
The CSV contains the facts. The brief explains the fields and category codes. The visualization lead
chooses how to present them; it does not invent new definitions for source codes.

For coded columns, the data agent should include `column_descriptions` and `code_meanings` keyed by
the exact CSV column names and original codes. Supply `units` for measurements. If approved wording
is available in the target language, include `display_labels` keyed by `ar` or `en`:

```json
{
  "producer_agent": "data-agent",
  "raw_question": "قارن عدد الأشخاص حسب الجنس",
  "intent": "compare",
  "column_descriptions": {"sex": "Sex of the person", "count": "Number of people"},
  "code_meanings": {"sex": {"M": "Male", "F": "Female"}},
  "units": {"count": "شخص"},
  "display_labels": {
    "ar": {
      "column_labels": {"sex": "الجنس", "count": "عدد الأشخاص"},
      "value_labels": {"sex": {"M": "ذكر", "F": "أنثى"}}
    }
  }
}
```

Keep this object inside the existing multipart `brief` field, alongside the `file` field. With it saved
as `brief.json`, an upstream integration can send:

```bash
curl -F file=@result.csv -F 'brief=<brief.json' http://127.0.0.1:7932/datasets/upload
```

Use the returned dataset ID for the visualization request. `/requests` does not accept a second brief;
the saved upload is the shared source of meanings. Existing briefs without `display_labels` remain
valid and retain their existing fingerprints.

## Precedence and consistency

- The data agent's definitions establish meaning. `M` in `sex` and `M` in `marital_status` have separate
  definitions; there is no global abbreviation dictionary.
- Approved labels for the requested language are copied into the saved design. Designer labels fill
  uncovered entries; they cannot silently rename a supplied approved entry.
- When a translation is absent, the lead/designer can translate a meaning established by the brief or
  clear column context in the existing design call. Ambiguous codes stay visible as their original code.
  The visualization team does not ask for missing data or run analysis just to translate a label.
- Presentation mappings apply to headings, axes, legends, tooltips, mark labels, tables, and KPI context.
  The source CSV, saved result rows, numeric measurements, grouping identities, and time ordering stay
  intact. API artifact rows retain raw values and expose the separate `display_labels` mapping.
- Display mappings are saved with the chart spec. Updating an upload brief does not retroactively change
  an existing artifact. A new design/revision uses its own saved mapping and language.

Meanings are part of the data agent's output contract, not a mandatory new visualization pipeline step.
The lead remains responsible for delegation and completion; review is optional and returns findings
about inconsistent wording to the lead.
