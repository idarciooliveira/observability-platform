# syntax=docker/dockerfile:1
# Build stage with OTel javaagent
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app

# Copy only pom.xml first for better layer caching
COPY pom.xml ./
# Use BuildKit cache mount for Maven dependencies
RUN --mount=type=cache,target=/root/.m2 \
    mvn dependency:go-offline -B

# Now copy source code
COPY src ./src
# Build with cache mount to reuse dependencies
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests -B -q

# Download OTel Java agent (pinned to version in pom.xml)
FROM alpine:3.19 AS otel-downloader
ARG OTEL_VERSION=2.31.1
RUN wget -q -O /opentelemetry-javaagent.jar \
    https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v${OTEL_VERSION}/opentelemetry-javaagent.jar

# Runtime stage
FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S app && adduser -S app -G app
USER app
WORKDIR /app

# Copy application jar
COPY --from=build /app/target/*.jar app.jar
# Copy OTel agent
COPY --from=otel-downloader /opentelemetry-javaagent.jar ./opentelemetry-javaagent.jar

EXPOSE 8080

# Run with OTel agent
ENTRYPOINT ["java", \
    "-javaagent:/app/opentelemetry-javaagent.jar", \
    "-jar", \
    "/app/app.jar"]
