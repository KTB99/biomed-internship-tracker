# Accept submitted listings for companies the tracker can't read

The tracker can't read the seven companies that post internships only on Workday
([ADR 0001](0001-no-workday-jobs-api.md)): Alcon, Globus Medical, Insulet,
Medtronic, ResMed, Smith+Nephew and Tandem. So anyone may submit a posting at a
company already in `companies.toml` with the "Add internship" issue form
(`.github/ISSUE_TEMPLATE/add-internship.yml`). A maintainer accepts it with
`python -m tracker add --issue N`, which screens it like any read posting and
writes a **submitted listing**. `data/listings.json` is never hand-edited.
Decided in [#14](https://github.com/KTB99/biomed-internship-tracker/issues/14#issuecomment-7089813523)
on 2026-11-23.

- **Origin.** A submitted listing has `platform = "submitted"`. That is a record
  platform, not a reader, so it isn't in `PLATFORMS`. Its ID is
  `listing_id(company, "submitted", <Apply URL>, <Apply URL>)`, so
  `tracker/ids.py` is unchanged and submitting the same URL twice gives the same
  ID. It also records `submitted_in`, the issue number.
- **Checking the URL.** A company accepts submissions only when it lists its
  allowed Apply URL hosts in `companies.toml` (`submit_hosts`). The Apply URL
  must be https and its host must equal one entry exactly: no subdomains and no
  wildcard Workday hosts. The form's Company options are exactly these companies.
- **Checking the posting is open.** `tracker add` makes no network call. The
  maintainer opens the link by hand when reviewing the submission, since Workday
  rate-limits automated requests.
- **Closing.** A submitted listing gains no misses while its company doesn't
  read a job board (`careers_page` or `link`), because no read can ever return
  it. It closes by `python -m tracker close`, or on the first refresh after its
  optional `closes_on` date, with close reason `deadline`: even when that
  company's read failed, except a run where every read fails writes nothing, so
  its deadline close waits for the next run that writes.
- **Duplicates.** `tracker add` refuses a URL that an open listing of the same
  company already has. When a successful read later returns a posting whose URL
  matches a submitted listing of the same company, the read listing replaces it
  in that run and keeps its `first_seen` (and its manual close, if any). URLs
  match on scheme, lowercased host and path, ignoring userinfo, port, the query,
  fragment, a trailing `/` and a trailing `/apply` (`reconcile.apply_url_key`). Other submitted listings
  gain misses as usual once their company reads a job board.
- **Rendering.** Every submitted field is untrusted and is escaped exactly like
  job-board data.

## Considered options

- **Exempting submitted listings from miss counting for good.** A company that
  becomes readable would then keep stale submissions open forever, so the
  exemption lasts only while the company doesn't read a job board.
- **Re-checking the posting from `tracker add`.** A request to Workday from the
  maintainer's machine is often rate-limited (ADR 0001), and a failed check
  would block a real posting. A human opening the link is more reliable.
- **Allowing any `*.myworkdayjobs.com` host.** Any Workday tenant could then
  pose as the company, so each company's hosts are listed exactly.
