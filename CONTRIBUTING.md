# Contributing

This project reviews declassified UAP records with reproducible scripts, local database rows, and a static dashboard. Contributions are welcome when they improve traceability, evidence quality, or the review interface.

## Good Contributions

- Corrections to source metadata, dates, locations, or agency attribution.
- New citations to primary source files or official records.
- Reproducible analysis improvements with clear method limits.
- Frontend fixes that make records easier to inspect.
- Bug reports with case IDs, screenshots, and browser/OS details.

## Evidence Standard

- Prefer primary documents, official releases, or directly reproducible local outputs.
- Do not present heuristic scores as calibrated probabilities.
- Mark artifact, witness, environment, and object-identification claims as pending unless the supporting evidence is explicit.
- Include the case ID and file path when a change affects a record.

## Pull Requests

1. Keep changes focused.
2. Explain which records or scripts are affected.
3. Run the relevant local checks before opening the PR.
4. Do not commit local secrets, `.env`, raw downloaded media, or temporary extraction folders.

Useful checks:

```sh
python3 -m py_compile war_ufo_enrich_cases_db.py war_ufo_populate_image_env_classification.py war_ufo_advanced_video_analysis.py sync_frontend_master.py
```

For frontend-only changes, also verify that the inline JavaScript in `frontend/index.html` parses.
