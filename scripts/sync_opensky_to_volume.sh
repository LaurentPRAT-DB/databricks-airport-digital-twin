#!/bin/bash
# Chunked sync of collected OpenSky data to Databricks UC Volume.
#
# Uploads JSONL files in batches of N, then triggers the ingestion job.
# Moves uploaded files to synced/ to track progress. Safe to re-run
# after interruption — only unsynced files are uploaded.
#
# Usage:
#   ./scripts/sync_opensky_to_volume.sh                  # default: batch of 100
#   ./scripts/sync_opensky_to_volume.sh --batch 50       # smaller batches
#   ./scripts/sync_opensky_to_volume.sh --dry-run        # show what would be uploaded
#   ./scripts/sync_opensky_to_volume.sh --no-ingest      # upload only, skip job trigger

set -euo pipefail

BATCH_SIZE=100
DRY_RUN=false
RUN_INGEST=true
LOCAL_DIR="data/opensky_raw"
SYNCED_DIR="data/opensky_raw/synced"
VOLUME_PATH="dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/opensky_raw"

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --batch) BATCH_SIZE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --no-ingest) RUN_INGEST=false; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

cd "$(dirname "$0")/.."
mkdir -p "$SYNCED_DIR"

# Find pending JSONL files (not in synced/)
PENDING=($(find "$LOCAL_DIR" -maxdepth 1 -name "*.jsonl" -type f | sort))
TOTAL=${#PENDING[@]}

if [[ $TOTAL -eq 0 ]]; then
  echo "No pending JSONL files to sync."
  exit 0
fi

echo "=== OpenSky Data Sync ==="
echo "  Pending files: $TOTAL"
echo "  Batch size: $BATCH_SIZE"
echo "  Volume: $VOLUME_PATH"
echo ""

UPLOADED=0
BATCH_NUM=0

while [[ $UPLOADED -lt $TOTAL ]]; do
  # Get next batch
  BATCH_END=$((UPLOADED + BATCH_SIZE))
  if [[ $BATCH_END -gt $TOTAL ]]; then
    BATCH_END=$TOTAL
  fi
  BATCH_FILES=("${PENDING[@]:$UPLOADED:$BATCH_SIZE}")
  BATCH_COUNT=${#BATCH_FILES[@]}
  BATCH_NUM=$((BATCH_NUM + 1))

  echo "--- Batch $BATCH_NUM: $BATCH_COUNT files (${UPLOADED}/${TOTAL} done) ---"

  if $DRY_RUN; then
    for f in "${BATCH_FILES[@]}"; do
      echo "  [dry-run] would upload: $(basename "$f")"
    done
  else
    # Upload each file individually (databricks fs cp doesn't support file lists)
    BATCH_OK=0
    for f in "${BATCH_FILES[@]}"; do
      FNAME=$(basename "$f")
      if databricks fs cp "$f" "$VOLUME_PATH/$FNAME" 2>/dev/null; then
        # Move to synced
        mv "$f" "$SYNCED_DIR/$FNAME"
        BATCH_OK=$((BATCH_OK + 1))
      else
        echo "  ERROR uploading $FNAME — stopping batch"
        break
      fi
    done
    echo "  Uploaded $BATCH_OK/$BATCH_COUNT files"

    # Trigger ingestion after each batch if requested
    if $RUN_INGEST && [[ $BATCH_OK -gt 0 ]]; then
      echo "  Triggering ingestion job..."
      if databricks bundle run opensky_ingestion --target dev 2>/dev/null; then
        echo "  Ingestion job completed"
      else
        echo "  WARNING: Ingestion job failed (files are in Volume, retry manually)"
      fi
    fi
  fi

  UPLOADED=$((UPLOADED + BATCH_COUNT))
  echo ""
done

echo "=== Sync complete: $TOTAL files processed ==="
echo "  Synced files in: $SYNCED_DIR/"
SYNCED_COUNT=$(find "$SYNCED_DIR" -name "*.jsonl" -type f | wc -l)
echo "  Total synced: $SYNCED_COUNT"
