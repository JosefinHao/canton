#!/bin/bash
# Canton Pipeline - Cloud Monitoring Alert Setup
#
# Creates Cloud Monitoring resources for the PRIMARY pipeline (BigQuery Scheduled Queries):
#   1. Email notification channel
#   2. Log-based metric: canton_scheduled_query_errors  (BQ scheduled query failures)
#   3. Log-based metric: canton_monitor_critical        (monitor WARNING/CRITICAL)
#   4. Alert policy: Scheduled query failures -> email
#   5. Alert policy: Pipeline monitor critical -> email
#
# Optionally, if MONITOR_CLOUDRUN=true, also creates Cloud Run backup pipeline monitoring:
#   6. Log-based metric: canton_pipeline_errors  (Cloud Run ERROR logs)
#   7. Alert policy: Cloud Run pipeline errors -> email
#   8. Uptime check: Cloud Run health endpoint (every 5 min)
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Cloud Monitoring API enabled:
#       gcloud services enable monitoring.googleapis.com --project ${PROJECT_ID}
#
# Usage:
#   ALERT_EMAIL=your@email.com bash scripts/setup_monitoring_alerts.sh
#
#   # With Cloud Run backup monitoring (only if Cloud Run is deployed):
#   MONITOR_CLOUDRUN=true ALERT_EMAIL=ops@company.com bash scripts/setup_monitoring_alerts.sh

set -e

PROJECT_ID="${PROJECT_ID:-governence-483517}"
REGION="${REGION:-us-central1}"
ALERT_EMAIL="${ALERT_EMAIL:-}"
MONITOR_CLOUDRUN="${MONITOR_CLOUDRUN:-false}"

# Cloud Run URL (only used when MONITOR_CLOUDRUN=true)
CLOUD_RUN_URL="${CLOUD_RUN_URL:-https://canton-data-ingestion-224112423672.us-central1.run.app}"

echo "=============================================="
echo "Canton Pipeline - Cloud Monitoring Alert Setup"
echo "=============================================="
echo "Project:         ${PROJECT_ID}"
echo "Region:          ${REGION}"
echo "Alert email:     ${ALERT_EMAIL:-NOT SET (skipping notification channel)}"
echo "Monitor Cloud Run backup: ${MONITOR_CLOUDRUN}"
echo ""

# ── Enable Cloud Monitoring API ────────────────────────────────────────────────
echo "Enabling Cloud Monitoring API..."
gcloud services enable monitoring.googleapis.com \
    --project "${PROJECT_ID}" 2>/dev/null || echo "  (already enabled or insufficient permissions)"

# ── 1. Email Notification Channel ─────────────────────────────────────────────
NOTIFICATION_CHANNEL=""
if [ -n "${ALERT_EMAIL}" ]; then
    echo ""
    echo "--- Step 1: Creating email notification channel ---"
    CHANNEL_ID=$(gcloud alpha monitoring channels create \
        --display-name="Canton Pipeline Alerts" \
        --type=email \
        --channel-labels="email_address=${ALERT_EMAIL}" \
        --project="${PROJECT_ID}" \
        --format="value(name)" 2>/dev/null || echo "")

    if [ -n "${CHANNEL_ID}" ]; then
        NOTIFICATION_CHANNEL="${CHANNEL_ID}"
        echo "  [OK] Email notification channel created: ${CHANNEL_ID}"
    else
        echo "  [WARN] Could not create notification channel. Alerts will be created without notifications."
        echo "         Create manually: Cloud Console -> Monitoring -> Alerting -> Notification channels"
    fi
else
    echo ""
    echo "--- Step 1: Skipping notification channel (ALERT_EMAIL not set) ---"
    echo "  Set ALERT_EMAIL=your@email.com and re-run to add email notifications."
fi

# ── 2. Log-based Metric: BigQuery Scheduled Query Failures (PRIMARY pipeline) ──
echo ""
echo "--- Step 2: Creating log-based metric: canton_scheduled_query_errors ---"
echo "    (Monitors failures of the PRIMARY pipeline: BQ scheduled queries)"

METRIC_CONFIG_BQ=$(cat <<'EOF'
{
  "name": "canton_scheduled_query_errors",
  "description": "Count of failed BigQuery Data Transfer Service runs (Canton scheduled query failures)",
  "filter": "resource.type=\"bigquery.googleapis.com/DataTransferConfig\" AND severity>=\"ERROR\" AND protoPayload.resourceName=~\"canton\"",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1",
    "labels": []
  }
}
EOF
)

echo "${METRIC_CONFIG_BQ}" | gcloud logging metrics create canton_scheduled_query_errors \
    --config-from-file=- \
    --project="${PROJECT_ID}" 2>/dev/null \
    && echo "  [OK] Log-based metric 'canton_scheduled_query_errors' created." \
    || echo "  [INFO] Metric may already exist or creation requires additional permissions."

# ── 3. Log-based Metric: Pipeline Monitor Warnings ────────────────────────────
echo ""
echo "--- Step 3: Creating log-based metric: canton_monitor_critical ---"

METRIC_CONFIG_WARN=$(cat <<'EOF'
{
  "name": "canton_monitor_critical",
  "description": "Count of CRITICAL/ERROR log entries emitted by the canton pipeline monitor (--notify flag)",
  "filter": "jsonPayload.pipeline_monitor.overall_status=(\"CRITICAL\" OR \"WARNING\") AND severity>=\"WARNING\"",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1",
    "labels": []
  }
}
EOF
)

echo "${METRIC_CONFIG_WARN}" | gcloud logging metrics create canton_monitor_critical \
    --config-from-file=- \
    --project="${PROJECT_ID}" 2>/dev/null \
    && echo "  [OK] Log-based metric 'canton_monitor_critical' created." \
    || echo "  [INFO] Metric may already exist or creation requires additional permissions."

NOTIFICATIONS_JSON="[]"
if [ -n "${NOTIFICATION_CHANNEL}" ]; then
    NOTIFICATIONS_JSON="[\"${NOTIFICATION_CHANNEL}\"]"
fi

# ── 4. Alert Policy: BigQuery Scheduled Query Failures ────────────────────────
echo ""
echo "--- Step 4: Creating alert policy: Canton Scheduled Query Failures ---"

ALERT_POLICY_BQ=$(cat <<EOF
{
  "displayName": "Canton: Scheduled Query Failures",
  "documentation": {
    "content": "A Canton BigQuery scheduled query (ingest_events_from_gcs or transform_raw_events) has failed. Check scheduled query history: https://console.cloud.google.com/bigquery/scheduled-queries?project=${PROJECT_ID}\n\nDiagnose: gcloud logging read 'resource.type=\"bigquery.googleapis.com/DataTransferConfig\" AND severity>=ERROR' --project=${PROJECT_ID} --limit=20"
  },
  "conditions": [
    {
      "displayName": "Scheduled query error rate > 0",
      "conditionThreshold": {
        "filter": "metric.type=\"logging.googleapis.com/user/canton_scheduled_query_errors\" AND resource.type=\"global\"",
        "aggregations": [
          {
            "alignmentPeriod": "86400s",
            "perSeriesAligner": "ALIGN_SUM"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "0s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "alertStrategy": {
    "notificationRateLimit": {
      "period": "86400s"
    }
  },
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ${NOTIFICATIONS_JSON}
}
EOF
)

echo "${ALERT_POLICY_BQ}" | gcloud alpha monitoring policies create \
    --policy-from-file=- \
    --project="${PROJECT_ID}" 2>/dev/null \
    && echo "  [OK] Alert policy 'Canton: Scheduled Query Failures' created." \
    || echo "  [INFO] Policy may already exist or creation requires additional permissions."

# ── 5. Alert Policy: Pipeline Monitor Critical ────────────────────────────────
echo ""
echo "--- Step 5: Creating alert policy: Canton Monitor Critical ---"

ALERT_POLICY_MONITOR=$(cat <<EOF
{
  "displayName": "Canton: Pipeline Monitor Critical",
  "documentation": {
    "content": "The Canton pipeline health monitor has detected CRITICAL or WARNING conditions. Run: python scripts/monitor_pipeline.py --json to see details."
  },
  "conditions": [
    {
      "displayName": "Monitor critical/warning events > 0",
      "conditionThreshold": {
        "filter": "metric.type=\"logging.googleapis.com/user/canton_monitor_critical\" AND resource.type=\"global\"",
        "aggregations": [
          {
            "alignmentPeriod": "86400s",
            "perSeriesAligner": "ALIGN_SUM"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "0s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "alertStrategy": {
    "notificationRateLimit": {
      "period": "86400s"
    }
  },
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ${NOTIFICATIONS_JSON}
}
EOF
)

echo "${ALERT_POLICY_MONITOR}" | gcloud alpha monitoring policies create \
    --policy-from-file=- \
    --project="${PROJECT_ID}" 2>/dev/null \
    && echo "  [OK] Alert policy 'Canton: Pipeline Monitor Critical' created." \
    || echo "  [INFO] Policy may already exist or creation requires additional permissions."

# ── 6. Optional: Cloud Run Backup Pipeline Monitoring ─────────────────────────
if [ "${MONITOR_CLOUDRUN}" = "true" ]; then
    echo ""
    echo "--- Step 6 (optional): Creating Cloud Run backup pipeline monitoring ---"
    echo "    MONITOR_CLOUDRUN=true — adding Cloud Run error metric and uptime check."

    METRIC_CONFIG_CR=$(cat <<'EOF'
{
  "name": "canton_pipeline_errors",
  "description": "Count of ERROR-severity log entries from the Canton data ingestion Cloud Run service (backup pipeline)",
  "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"canton-data-ingestion\" AND severity>=ERROR",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1",
    "labels": []
  }
}
EOF
    )
    echo "${METRIC_CONFIG_CR}" | gcloud logging metrics create canton_pipeline_errors \
        --config-from-file=- \
        --project="${PROJECT_ID}" 2>/dev/null \
        && echo "  [OK] Log-based metric 'canton_pipeline_errors' created." \
        || echo "  [INFO] Metric may already exist or creation requires additional permissions."

    ALERT_POLICY_CR=$(cat <<EOF
{
  "displayName": "Canton: Pipeline Errors (Cloud Run backup)",
  "documentation": {
    "content": "The Canton data ingestion Cloud Run backup service has logged ERROR-severity entries. Check logs: gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=canton-data-ingestion AND severity>=ERROR' --project=${PROJECT_ID} --limit=20"
  },
  "conditions": [
    {
      "displayName": "Error log rate > 0",
      "conditionThreshold": {
        "filter": "metric.type=\"logging.googleapis.com/user/canton_pipeline_errors\" AND resource.type=\"global\"",
        "aggregations": [
          {
            "alignmentPeriod": "3600s",
            "perSeriesAligner": "ALIGN_RATE"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "0s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "alertStrategy": {
    "notificationRateLimit": {
      "period": "3600s"
    }
  },
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ${NOTIFICATIONS_JSON}
}
EOF
    )
    echo "${ALERT_POLICY_CR}" | gcloud alpha monitoring policies create \
        --policy-from-file=- \
        --project="${PROJECT_ID}" 2>/dev/null \
        && echo "  [OK] Alert policy 'Canton: Pipeline Errors (Cloud Run backup)' created." \
        || echo "  [INFO] Policy may already exist or creation requires additional permissions."

    CLOUD_RUN_HOST=$(echo "${CLOUD_RUN_URL}" | sed 's|https://||' | sed 's|/.*||')
    UPTIME_CHECK=$(cat <<EOF
{
  "displayName": "Canton Data Ingestion - Cloud Run Health Check",
  "monitoredResource": {
    "type": "uptime_url",
    "labels": {
      "project_id": "${PROJECT_ID}",
      "host": "${CLOUD_RUN_HOST}"
    }
  },
  "httpCheck": {
    "path": "/",
    "port": 443,
    "useSsl": true,
    "validateSsl": true
  },
  "period": "300s",
  "timeout": "10s",
  "contentMatchers": [
    {
      "content": "healthy",
      "matcher": "CONTAINS_STRING"
    }
  ]
}
EOF
    )
    echo "${UPTIME_CHECK}" | gcloud monitoring uptime create \
        --config-from-file=- \
        --project="${PROJECT_ID}" 2>/dev/null \
        && echo "  [OK] Uptime check created for ${CLOUD_RUN_URL}" \
        || echo "  [INFO] Uptime check may already exist or creation requires additional permissions."
else
    echo ""
    echo "--- Step 6 (optional): Skipping Cloud Run backup pipeline monitoring ---"
    echo "    Set MONITOR_CLOUDRUN=true to also create Cloud Run error metric and uptime check."
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "Setup Complete"
echo "=============================================="
echo ""
echo "Resources created (or already existed) — PRIMARY pipeline monitoring:"
echo "  - Log-based metric:  canton_scheduled_query_errors"
echo "  - Log-based metric:  canton_monitor_critical"
echo "  - Alert policy:      Canton: Scheduled Query Failures"
echo "  - Alert policy:      Canton: Pipeline Monitor Critical"
if [ "${MONITOR_CLOUDRUN}" = "true" ]; then
    echo ""
    echo "Resources created — BACKUP pipeline monitoring (MONITOR_CLOUDRUN=true):"
    echo "  - Log-based metric:  canton_pipeline_errors"
    echo "  - Alert policy:      Canton: Pipeline Errors (Cloud Run backup)"
    echo "  - Uptime check:      Canton Data Ingestion - Cloud Run Health Check"
fi
if [ -n "${ALERT_EMAIL}" ]; then
    echo ""
    echo "  - Notification:      Email -> ${ALERT_EMAIL}"
fi
echo ""
echo "View alerts:  https://console.cloud.google.com/monitoring/alerting?project=${PROJECT_ID}"
echo "View metrics: https://console.cloud.google.com/logs/metrics?project=${PROJECT_ID}"
echo ""
echo "--- Integration with monitor_pipeline.py ---"
echo ""
echo "To emit alerts via Cloud Logging (for log-based metric triggers):"
echo "  python scripts/monitor_pipeline.py --notify"
echo ""
echo "For continuous monitoring, add to cron (run once daily, e.g. after BQ scheduled queries):"
echo "  0 3 * * * cd /path/to/canton && python scripts/monitor_pipeline.py --notify >> /var/log/canton/monitor.log 2>&1"
echo ""
echo "--- Manual Alert Setup (if gcloud commands failed) ---"
echo ""
echo "1. Cloud Console -> Monitoring -> Alerting -> Create policy"
echo "2. Add condition: Logs-based metric 'canton_scheduled_query_errors', threshold > 0"
echo "3. Repeat for 'canton_monitor_critical' metric"
echo "4. Add notification channel (email: ${ALERT_EMAIL:-your@email.com})"
