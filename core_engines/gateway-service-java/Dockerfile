FROM eclipse-temurin:17-jre-jammy

# Install Python 3 so the Java gateway can execute orchestration scripts
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Extract the production compiled JAR target directly into the image path layout context
COPY target/*.jar app.jar

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]