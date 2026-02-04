#!/bin/bash
# Setup script for Canton data ingestion cron job
# Run this on your VM: bash scripts/setup_cron.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANTON_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/canton"
LOG_FILE="$LOG_DIR/ingestion.log"

echo "=== Canton Data Ingestion Cron Setup ==="
echo "Canton directory: $CANTON_DIR"

# Create log directory
if [ ! -d "$LOG_DIR" ]; then
    echo "Creating log directory: $LOG_DIR"
    sudo mkdir -p "$LOG_DIR"
    sudo chmod 755 "$LOG_DIR"
fi

# Ensure user can write to log
sudo touch "$LOG_FILE"
sudo chmod 666 "$LOG_FILE"

# Install Python dependencies if needed
echo "Checking Python dependencies..."
pip3 install --user google-cloud-bigquery requests 2>/dev/null || true

# Make the ingestion script executable
chmod +x "$SCRIPT_DIR/run_ingestion.py"

# Test the script first
echo "Testing ingestion script (status check)..."
cd "$CANTON_DIR"
python3 scripts/run_ingestion.py --status

# Create cron entry
CRON_CMD="*/15 * * * * cd $CANTON_DIR && /usr/bin/python3 scripts/run_ingestion.py >> $LOG_FILE 2>&1"

echo ""
echo "=== Cron Configuration ==="
echo "The following cron entry will run ingestion every 15 minutes:"
echo ""
echo "$CRON_CMD"
echo ""

read -p "Add this to crontab? (y/n): " confirm
if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
    # Check if entry already exists
    if crontab -l 2>/dev/null | grep -q "run_ingestion.py"; then
        echo "Cron entry already exists. Updating..."
        (crontab -l 2>/dev/null | grep -v "run_ingestion.py"; echo "$CRON_CMD") | crontab -
    else
        (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    fi
    echo "Cron job added successfully!"
    echo ""
    echo "Current crontab:"
    crontab -l
else
    echo "Skipped. To add manually, run:"
    echo "  crontab -e"
    echo "  # Add: $CRON_CMD"
fi

echo ""
echo "=== Setup Complete ==="
echo "Log file: $LOG_FILE"
echo "To run manually: cd $CANTON_DIR && python3 scripts/run_ingestion.py"
echo "To view logs: tail -f $LOG_FILE"
