FROM eclipse-temurin:21-jre-jammy

WORKDIR /app
# Build with the existing Maven/JDK toolchain before creating this image.
COPY backend-java/target/dataweb-production-1.1.0-SNAPSHOT.jar /app/production.jar
COPY ops/production-entrypoint.sh /app/entrypoint.sh
RUN chmod 0555 /app/entrypoint.sh && groupadd -g 10001 app && useradd -u 10001 -g app -M app
USER 10001:10001
ENTRYPOINT ["/app/entrypoint.sh"]
