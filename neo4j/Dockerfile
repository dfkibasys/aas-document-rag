FROM neo4j:5.26.8-community-bullseye

ADD https://github.com/neo4j/apoc/releases/download/5.26.8/apoc-5.26.8-core.jar /var/lib/neo4j/plugins/apoc.jar

ENV NEO4J_apoc_export_file_enabled=true \
    NEO4J_apoc_import_file_enabled=true \
    NEO4J_apoc_import_file_use__neo4j__config=true \
    NEO4J_dbms_security_procedures_unrestricted=apoc.*

