#!/bin/bash

/etc/confluent/docker/run &

echo "Waiting for Kafka Connect to start..."
until curl -sf http://localhost:8083/connectors > /dev/null; do
  echo "Kafka Connect not ready yet, waiting..."
  sleep 3
done

echo "Kafka Connect started, deploying FileStreamSink connector..."

CONNECTOR_NAME="AasEventsFileStreamSink"
CONNECTOR_CONFIG_PATH="/etc/kafka-connect/config/file-sink-connector.json"
CONNECTOR_URL="http://localhost:8083/connectors/$CONNECTOR_NAME/config"

if curl -s -o /dev/null -w "%{http_code}" "$CONNECTOR_URL" | grep -q "200"; then
  echo "Updating existing connector: $CONNECTOR_NAME"
  RESPONSE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -H "Content-Type: application/json" --data @"$CONNECTOR_CONFIG_PATH" "$CONNECTOR_URL")
else
  echo "Creating new connector: $CONNECTOR_NAME"
  RESPONSE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" --data @"$CONNECTOR_CONFIG_PATH" http://localhost:8083/connectors)
fi

if [ "$RESPONSE_CODE" -lt 200 ] || [ "$RESPONSE_CODE" -ge 300 ]; then
  echo "Connector deployment failed with status code $RESPONSE_CODE."
  exit 1
fi

echo "Connector deployed successfully. Waiting for connector to start..."

# Poll connector status
MAX_STATUS_CHECKS=15
for i in $(seq 1 $MAX_STATUS_CHECKS); do
  sleep 2
  
  STATUS_RESPONSE=$(curl -s http://localhost:8083/connectors/$CONNECTOR_NAME/status)
  CONNECTOR_STATE=$(echo "$STATUS_RESPONSE" | grep -o '"state":"[^"]*"' | head -1 | cut -d'"' -f4)
  
  echo "Connector status check $i/$MAX_STATUS_CHECKS: $CONNECTOR_STATE"
  
  if [ "$CONNECTOR_STATE" = "RUNNING" ]; then
    echo "✓ Connector is RUNNING and ready to process events."
    break
  elif [ "$CONNECTOR_STATE" = "FAILED" ]; then
    echo "✗ Connector FAILED to start. Status details:"
    echo "$STATUS_RESPONSE"
    exit 1
  fi
  
  if [ $i -eq $MAX_STATUS_CHECKS ]; then
    echo "⚠ Connector did not reach RUNNING state after ${MAX_STATUS_CHECKS} checks."
    echo "Current status: $CONNECTOR_STATE"
    echo "Full status response:"
    echo "$STATUS_RESPONSE"
    exit 1
  fi
done

# Keep kafka-connect process running
wait
