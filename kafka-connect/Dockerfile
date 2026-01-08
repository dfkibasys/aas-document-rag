# FROM confluentinc/cp-kafka-connect:7.9.1 AS download

# USER root

# # Download FileStreamSink connector JAR from Maven Central
# RUN curl -L -o /tmp/connect-file.jar \
#     https://repo1.maven.org/maven2/org/apache/kafka/connect-file/3.6.0/connect-file-3.6.0.jar
# Stage 1: Download und Entpacken
FROM alpine:latest AS download
USER root
# Installiere curl und unzip
RUN apk add --no-cache curl unzip

# Download der spezifischen Version von GitHub
RUN curl -L -o /tmp/connector.zip \
    https://github.com/Aiven-Open/http-connector-for-apache-kafka/releases/download/v0.9.0/http-connector-for-apache-kafka-0.9.0.zip

# Entpacken in einen temporären Ordner
RUN unzip /tmp/connector.zip -d /tmp/connector-extracted

# Stage 2: Finales Image
FROM confluentinc/cp-kafka-connect:7.9.1

USER root

# Erstelle den Zielordner für das Plugin
RUN mkdir -p /usr/share/java/kafka-connect-http

# Kopiere den Inhalt des entpackten ZIPs (die Jars) in den Plugin-Ordner
# Das Release-Zip enthält meist einen Unterordner, daher nehmen wir den Inhalt daraus
COPY --from=download /tmp/connector-extracted/http-connector-for-apache-kafka-0.9.0/ /usr/share/java/kafka-connect-http/

# Copy entrypoint script
COPY scripts/entrypoint.sh /etc/basyx/entrypoint.sh
RUN chmod +x /etc/basyx/entrypoint.sh

USER appuser

# Kafka Connect Worker Configuration
ENV CONNECT_GROUP_ID="http-sink-connector-group"
ENV CONNECT_CONFIG_STORAGE_TOPIC="http-sink-connector-config"
ENV CONNECT_OFFSET_STORAGE_TOPIC="http-sink-connector-offsets"
ENV CONNECT_STATUS_STORAGE_TOPIC="http-sink-connector-status"
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
