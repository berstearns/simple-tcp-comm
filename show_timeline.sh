#!/bin/bash
# Show reading timeline from an archive or worker DB
# Usage: ./show_timeline.sh /path/to/db
DB="${1:?Usage: show_timeline.sh /path/to/db}"

echo "══════════════════════════════════════════════════════════════"
echo "  READING TIMELINE   $(date +%H:%M:%S)"
echo "  $DB"
echo "══════════════════════════════════════════════════════════════"
echo
echo "── All Activity (most recent first) ──"
sqlite3 -header -column "$DB" "
SELECT * FROM (
  SELECT datetime(timestamp/1000, 'unixepoch', 'localtime') AS time,
         'PAGE' AS type,
         comic_id, device_id,
         chapter_name || ' / ' || page_title AS detail
  FROM session_events
  WHERE event_type = 'PAGE_ENTER'
  GROUP BY timestamp, comic_id, page_id

  UNION ALL

  SELECT datetime(timestamp/1000, 'unixepoch', 'localtime') AS time,
         interaction_type AS type,
         comic_id, device_id,
         COALESCE(chapter_name,'') || ' / ' || COALESCE(page_id,'') || CASE WHEN hit_result IS NOT NULL THEN ' [' || hit_result || ']' ELSE '' END AS detail
  FROM page_interactions

  UNION ALL

  SELECT datetime(timestamp/1000, 'unixepoch', 'localtime') AS time,
         'ANNOTATE' AS type,
         comic_id, device_id,
         label || ' ' || region_type || ' ' || image_id AS detail
  FROM annotation_records
)
ORDER BY time DESC
LIMIT 60;"
echo
echo "── Totals ──"
sqlite3 "$DB" "
SELECT COUNT(*) || ' page enters' FROM session_events WHERE event_type='PAGE_ENTER'
UNION ALL
SELECT COUNT(*) || ' interactions' FROM page_interactions
UNION ALL
SELECT COUNT(*) || ' annotations' FROM annotation_records;"
