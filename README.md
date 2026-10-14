# PSE9 abstract review site

A static page for the PSE9 programme committee. Reviewers sign in with a
personal code, see one submission at a time (career stage, job type, history,
proposed format, abstract; no names or e-mail addresses), and fill in the
scoring form from `review_rubric.md`. Scores are kept on the reviewer's device
and, if configured, synced to a Google Sheet the chair owns.

The submissions file in `data/` is encrypted (AES-GCM; each reviewer code
unwraps the data key via PBKDF2), so the repository can be public and still
only the five code holders can read the abstracts. The codes themselves live in
`tools/codes.json`, which is git-ignored. Never commit it.

## One-time setup (chair)

1. **Repository and hosting.** Push this folder to a GitHub repository, then
   Settings > Pages > "Deploy from a branch", branch `main`, folder `/ (root)`.
   The site appears at `https://<org>.github.io/<repo>/` after a minute.

2. **Reviewer codes.**
   ```bash
   uv run tools/make_codes.py --names "Name1,Name2,Name3,Name4,Name5"
   ```
   Prints five codes and a `TOKENS` block. Send each reviewer their code
   privately together with the site URL. `--show` prints everything again.

3. **Score sheet (recommended).** Create an empty Google Sheet, open
   Extensions > Apps Script, replace the contents with `backend/Code.gs`, paste
   the `TOKENS` block from step 2, save. Deploy > New deployment > type "Web
   app", execute as "Me", access "Anyone". Copy the URL ending in `/exec` into
   `syncUrl` in `config.js` and push. Opening the URL in a browser should show
   `{"ok":true,"service":"pse9-review"}`.

   Without this step the site still works: scores stay in each reviewer's
   browser and they send you the CSV from "Download my scores".

4. **First data build.** Download the responses workbook from Microsoft Forms
   (Open in Excel, then File > Save as > Download a copy), then:
   ```bash
   uv run tools/build_data.py ~/Downloads/export.xlsx --list-columns
   ```
   Check that every `match` in `tools/columns.json` picks exactly one column
   (the script says so if not), adjust labels if you like, then:
   ```bash
   ./update.sh ~/Downloads/export.xlsx
   ```
   This builds `data/submissions.enc.json`, commits and pushes.

## Daily update

Download a fresh copy of the workbook and run `./update.sh <file>` again.
Submission IDs come from the Forms `ID` column, so they stay stable across
exports and existing scores keep pointing at the right abstract. Rows without
an abstract are skipped.

## Reading the scores

Export the `scores` tab of the Google Sheet as CSV (File > Download > CSV) and
run:
```bash
uv run tools/aggregate.py scores.csv > summary.csv
```
One row per submission: per-criterion means, overall mean, the recommendation
votes, conflict flags, and the reviewers' notes. CSV files that reviewers
downloaded from the site can be passed in as well; the newest record per
reviewer and submission wins.

## Trying it without real data

```bash
uv run tools/make_codes.py --names "Test1,Test2,Test3,Test4,Test5"
uv run tools/fake_export.py /tmp/fake_export.xlsx
uv run tools/build_data.py /tmp/fake_export.xlsx
python3 -m http.server 8765
```
Open http://localhost:8765 and sign in with one of the printed codes. Rebuild
with the real export before pushing.

## Notes

- Anyone with a code can read every submission, so treat the codes like
  passwords. To revoke: `make_codes.py --force`, rebuild, push, send new codes.
- The reviewer code is remembered in the browser until "Sign out".
- Only the fields listed in `tools/columns.json` leave the chair's computer.
- The form lives in `app.js` (`FORM`); the sheet columns in `backend/Code.gs`
  (`FIELDS`). Change both if you change the form.
