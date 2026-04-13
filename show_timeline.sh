#!/bin/bash
# Show reading timeline from an archive or worker DB
# Usage: ./show_timeline.sh /path/to/db
DB="${1:?Usage: show_timeline.sh /path/to/db}"

echo "══════════════════════════════════════════════════════════════"
echo "  READING TIMELINE   $(date +%H:%M:%S)"
echo "  $DB"
echo "══════════════════════════════════════════════════════════════"
echo
echo "── Pages Entered ──"
sqlite3 -header -column "$DB" "
SELECT datetime(timestamp/1000, 'unixepoch', 'localtime') AS time,
       comic_id, chapter_name, page_title
FROM session_events
WHERE event_type = 'PAGE_ENTER'
GROUP BY timestamp, comic_id, page_id
ORDER BY timestamp;"
echo
echo "── Page Interactions ──"
sqlite3 -header -column "$DB" "
SELECT datetime(timestamp/1000, 'unixepoch', 'localtime') AS time,
       interaction_type, comic_id, chapter_name, page_id
FROM page_interactions
ORDER BY timestamp;"
echo
echo "── Bubble Taps ──"
sqlite3 -header -column "$DB" "
SELECT datetime(timestamp/1000, 'unixepoch', 'localtime') AS time,
       label, region_type, image_id
FROM annotation_records
ORDER BY timestamp;"
echo
echo "── Totals ──"
sqlite3 "$DB" "
SELECT COUNT(*) || ' page enters' FROM session_events WHERE event_type='PAGE_ENTER'
UNION ALL
SELECT COUNT(*) || ' interactions' FROM page_interactions
UNION ALL
SELECT COUNT(*) || ' bubble taps' FROM annotation_records;"
