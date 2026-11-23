#!/usr/bin/env bash
# Reports saved `python -m tracker refresh` output, and its
# "[failed] <company>: <error>" lines, for the Daily refresh workflow.
#
#   failed-reads.sh annotations FILE  one ::warning:: command per failed read
#   failed-reads.sh report FILE       Markdown block for the job summary and
#                                     pull request body; nothing if none failed
#   failed-reads.sh summary FILE      the report, or "No failed reads."
#   failed-reads.sh log FILE          the whole output inside <pre>
#
# Error text can come from job boards. The refresh command collapses each error
# onto one line, so every "[failed]" line is one company and no LF is left to
# escape. The rest is escaped for where it goes: % and CR for annotations
# (workflow-command escaping), HTML inside <pre> for the report and log (which
# also stops GitHub turning @names and #numbers into links).
set -euo pipefail

usage="usage: failed-reads.sh annotations|report|summary|log FILE"
command="${1:?${usage}}"
file="${2:?${usage}}"

escape_html() {
  sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

report() {
  local lines
  lines="$(grep '^\[failed\] ' "${file}" | tr -d '\r' || true)"
  [ -n "${lines}" ] || return 0
  echo "### Failed reads ($(printf '%s\n' "${lines}" | wc -l))"
  echo
  echo "<pre>"
  printf '%s\n' "${lines}" | escape_html
  echo "</pre>"
}

case "${command}" in
  annotations)
    sed -n 's/^\[failed\] //p' "${file}" \
      | sed -e 's/%/%25/g' -e 's/\r/%0D/g' -e 's/^/::warning title=Failed read::/'
    ;;
  report)
    report
    ;;
  summary)
    text="$(report)"
    echo "${text:-No failed reads.}"
    ;;
  log)
    echo "<pre>"
    escape_html < "${file}"
    echo "</pre>"
    ;;
  *)
    echo "unknown command: ${command}" >&2
    exit 2
    ;;
esac
