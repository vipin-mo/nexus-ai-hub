# --- Stage 1: Native Application Compilation ---
FROM maven:3.8.5-openjdk-17 AS builder

WORKDIR /build
COPY pom.xml .
# Cache maven dependencies layer independently
RUN mvn dependency:go-offline -B 2>/dev/null || true

COPY src ./src
RUN mvn clean package -DskipTests

# --- Stage 2: High-Performance Runtime Minimal Layer ---
FROM eclipse-temurin:17-jre-jammy

WORKDIR /app
# Extract the production compiled JAR target directly from the builder image context
COPY --from=builder /build/target/*.jar app.jar

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
