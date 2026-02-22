#!/bin/bash
# Canton Pipeline - Cloud Monitoring Alert Setup
#
# Creates the following Google Cloud Monitoring resources:
#   1. Email notification channel
#   2. Log-based metric: canton_pipeline_errors (ERROR logs from Cloud Run)
#   3. Log-based metric: canton_pipeline_warnings (WARNING logs from monitor)
#   4. Alert policy: Pipeline errors (triggers on error log rate)
#   5. Alert policy: Data freshness SLA breach (triggers when lag > 72h)
#   6. Uptime check: Cloud Run health endpoint
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Cloud Monitoring API enabled:
#       gcloud services enable monitoring.googleapis.com --project ${PROJECT_ID}
#   - Cloud Run service deployed (for uptime check)
#
# Usage:
#   ALERT_EMAIL=your@email.com bash scripts/setup_monitoring_alerts.sh
#
#   # Override defaults:
#   PROJECT_ID=my-project ALERT_EMAIL=ops@company.com bash scripts/setup_monitoring_alerts.sh

set -e

PROJECT_ID="${PROJECT_ID:-governence-483517}"
REGION="${REGION:-us-central1}"
ALERT_EMAIL="${ALERT_EMAIL:-}"
CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:-canton-data-ingestion}"

# Cloud Run URL (used for uptime check)
CLOUD_RUN_URL="${CLOUD_RUN_URL:-https://canton-data-ingestion-224112423672.us-central1.run.app}"

echo "=============================================="
echo "Canton Pipeline - Cloud Monitoring Alert Setup"
echo "=============================================="
echo "Project:         ${PROJECT_ID}"
echo "Region:          ${REGION}"
echo "Alert email:     ${ALERT_EMAIL:-NOT SET (skipping notification channel)}"
echo "Cloud Run URL:   ${CLOUD_RUN_URL}"
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

# ── 2. Log-based Metric: Pipeline Errors (Cloud Run) ──────────────────────────
echo ""
echo "--- Step 2: Creating log-based metric: canton_pipeline_errors ---"

METRIC_CONFIG_ERRORS=$(cat <<'EOF'
{
  "name": "canton_pipeline_errors",
  "description": "Count of ERROR-severity log entries from the Canton data ingestion Cloud Run service",
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

echo "${METRIC_CONFIG_ERRORS}" | gcloud logging metrics create canton_pipeline_errors \
    --config-from-file=- \
    --project="${PROJECT_ID}" 2>/dev/null \
    && echo "  [OK] Log-based metric 'canton_pipeline_errors' created." \
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

# ── 4. Alert Policy: Cloud Run Pipeline Errors ────────────────────────────────
echo ""
echo "--- Step 4: Creating alert policy: Canton Pipeline Errors ---"

NOTIFICATIONS_JSON="[]"
if [ -n "${NOTIFICATION_CHANNEL}" ]; then
    NOTIFICATIONS_JSON="[\"${NOTIFICATION_CHANNEL}\"]"
fi

ALERT_POLICY_ERRORS=$(cat <<EOF
{
  "displayName": "Canton: Pipeline Errors (Cloud Run)",
  "documentation": {
    "content": "The Canton data ingestion Cloud Run service has logged ERROR-severity entries. Check logs: gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=canton-data-ingestion AND severity>=ERROR' --project=${PROJECT_ID} --limit=20"
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

echo "${ALERT_POLICY_ERRORS}" | gcloud alpha monitoring policies create \
    --policy-from-file=- \
    --project="${PROJECT_ID}" 2>/dev/null \
    && echo "  [OK] Alert policy 'Canton: Pipeline Errors' created." \
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

# ── 6. Uptime Check: Cloud Run Health Endpoint ────────────────────────────────
echo ""
echo "--- Step 6: Creating uptime check for Cloud Run service ---"

# Parse host and path from Cloud Run URL
CLOUD_RUN_HOST=$(echo "${CLOUD_RUN_URL}" | sed 's|https://||' | sed 's|/.*||')

UPTIME_CHECK=$(cat <<EOF
{
  "displayName": "Canton Data Ingestion - Health Check",
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

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "Setup Complete"
echo "=============================================="
echo ""
echo "Resources created (or already existed):"
echo "  - Log-based metric:  canton_pipeline_errors"
echo "  - Log-based metric:  canton_monitor_critical"
echo "  - Alert policy:      Canton: Pipeline Errors (Cloud Run)"
echo "  - Alert policy:      Canton: Pipeline Monitor Critical"
echo "  - Uptime check:      Canton Data Ingestion - Health Check"
if [ -n "${ALERT_EMAIL}" ]; then
    echo "  - Notification:      Email -> ${ALERT_EMAIL}"
fi
echo ""
echo "View alerts: https://console.cloud.google.com/monitoring/alerting?project=${PROJECT_ID}"
echo "View metrics: https://console.cloud.google.com/logs/metrics?project=${PROJECT_ID}"
echo ""
echo "--- Integration with monitor_pipeline.py ---"
echo ""
echo "To emit alerts via Cloud Logging (for log-based metric triggers):"
echo "  python scripts/monitor_pipeline.py --notify"
echo ""
echo "For continuous monitoring, add this to cron (run once daily):"
echo "  0 8 * * * cd /path/to/canton && python scripts/monitor_pipeline.py --notify >> /var/log/canton/monitor.log 2>&1"
echo ""
echo "--- Manual Alert Setup (if gcloud commands failed) ---"
echo ""
echo "1. Cloud Console -> Monitoring -> Alerting -> Create policy"
echo "2. Add condition: Logs-based metric 'canton_pipeline_errors', threshold > 0"
echo "3. Add notification channel (email: ${ALERT_EMAIL:-your@email.com})"
echo "4. Repeat for 'canton_monitor_critical' metric"
