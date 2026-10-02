# Manix / مانیکس: multiple official Java runtimes: Mojang's metadata selects the right one.
FROM eclipse-temurin:8-jre-jammy AS java8
FROM eclipse-temurin:17-jre-jammy AS java17
FROM eclipse-temurin:21-jre-jammy AS java21
FROM eclipse-temurin:25-jre-jammy AS java25

FROM python:3.12-slim-bookworm
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates tzdata tini gosu libfontconfig1 libfreetype6 libasound2 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 panel && useradd -u 1000 -g panel -m -s /usr/sbin/nologin panel
COPY --from=java8 /opt/java/openjdk /opt/java/8
COPY --from=java17 /opt/java/openjdk /opt/java/17
COPY --from=java21 /opt/java/openjdk /opt/java/21
COPY --from=java25 /opt/java/openjdk /opt/java/25
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data PORT=8080 MC_PORT=25565 \
    JAVA_HOME=/opt/java/21 PATH="/opt/java/21/bin:${PATH}"
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY panel ./panel
COPY scripts/entrypoint.sh /usr/local/bin/manix-entrypoint
RUN chmod 755 /usr/local/bin/manix-entrypoint
EXPOSE 8080 25565
# The entrypoint only fixes mount ownership, then permanently drops privileges.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/manix-entrypoint"]
CMD ["python", "-m", "panel"]
