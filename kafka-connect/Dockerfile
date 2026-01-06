FROM confluentinc/cp-kafka-connect:7.9.1 AS download

USER root

# Download FileStreamSink connector JAR from Maven Central
RUN curl -L -o /tmp/connect-file.jar \
    https://repo1.maven.org/maven2/org/apache/kafka/connect-file/3.6.0/connect-file-3.6.0.jar

FROM confluentinc/cp-kafka-connect:7.9.1

USER root

# Copy FileStreamSink connector JAR
COPY --from=download /tmp/connect-file.jar /tmp/connect-plugins/connect-file.jar

# Copy entrypoint script
COPY scripts/entrypoint.sh /etc/basyx/entrypoint.sh
RUN chmod +x /etc/basyx/entrypoint.sh

USER appuser

# Kafka Connect Worker Configuration
ENV CONNECT_GROUP_ID="file-sink-connector-group"
ENV CONNECT_CONFIG_STORAGE_TOPIC="file-sink-connector-config"
ENV CONNECT_OFFSET_STORAGE_TOPIC="file-sink-connector-offsets"
ENV CONNECT_STATUS_STORAGE_TOPIC="file-sink-connector-status"
ENV CONNECT_CONFIG_STORAGE_REPLICATION_FACTOR=1
ENV CONNECT_OFFSET_STORAGE_REPLICATION_FACTOR=1
ENV CONNECT_STATUS_STORAGE_REPLICATION_FACTOR=1
ENV CONNECT_REST_HEALTH_ENABLED="true"
ENV CONNECT_REST_PORT=8083
ENV CONNECT_PLUGIN_PATH="/usr/share/java,/usr/share/confluent-hub-components,/tmp/connect-plugins"

# Converter Configuration
ENV CONNECT_KEY_CONVERTER="org.apache.kafka.connect.storage.StringConverter"
ENV CONNECT_VALUE_CONVERTER="org.apache.kafka.connect.storage.StringConverter"
ENV CONNECT_INTERNAL_KEY_CONVERTER="org.apache.kafka.connect.storage.StringConverter"
ENV CONNECT_INTERNAL_VALUE_CONVERTER="org.apache.kafka.connect.json.JsonConverter"

HEALTHCHECK --start-period=5m --interval=1m --timeout=10s --retries=5 \
  CMD curl -f http://localhost:8083/ || exit 1

CMD ["/etc/basyx/entrypoint.sh"]
