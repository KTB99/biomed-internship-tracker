# Don't read Workday's jobs API

Alcon, Globus Medical, Insulet, Medtronic, ResMed, Smith+Nephew and Tandem post
their internships only on Workday. The tracker doesn't read Workday's public jobs
API (`https://<tenant>.wdN.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs`).
Those companies stay on `careers_page`, and the README links to their program page.
A Workday-hosted company is read only when it has another public job board:
Phenom for Abbott, GE HealthCare, Philips and Siemens Healthineers, and Eightfold
for Boston Scientific. A posting's Apply link may still point at its Workday page.

The API sits behind Cloudflare and rate-limits the tracker's generic user agent.
One search from the maintainer's VPS on 2026-11-22 got HTTP 429. On 2026-11-23,
two dry runs from GitHub's runners tried all seven companies
([#6](https://github.com/KTB99/biomed-internship-tracker/issues/6)):

- The first run got 429 for six of the seven on their first search request.
- Insulet read in the first run, then got 429 in the second, ten minutes later.

Getting past bot protection (browser user agents, cookies, headless browsers) is
off the table. A reader that's blocked most days would add a failed read to every
refresh and almost no listings.

## Considered options

- **A `workday` reader for the jobs API.** It was built and tested, then left
  unmerged: branch `workday-reader`,
  [#12](https://github.com/KTB99/biomed-internship-tracker/pull/12). To re-check,
  switch one company to `workday` on that branch and dispatch a dry run. Reopen
  this decision only if Workday answers on several different days.
