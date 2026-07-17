FROM python:3.13-slim AS build
WORKDIR /src
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY . .
RUN scripts/patch_version
RUN pip install --no-cache-dir --disable-pip-version-check .

FROM python:3.13-slim
RUN useradd --create-home --shell /usr/sbin/nologin icloudpd \
    && mkdir -p /home/icloudpd/.pyicloud \
    && chown icloudpd:icloudpd /home/icloudpd/.pyicloud
COPY --from=build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=build /usr/local/bin/icloudpd /usr/local/bin/icloudpd
COPY --from=build /usr/local/bin/icloud /usr/local/bin/icloud
# A generic stdin-JSON-to-URL forwarder for --notification-script, baked in
# so deployments don't need to bind-mount it themselves. Its only dependency
# (requests) is already part of the icloudpd package installed above.
COPY integrations/telegram-bot/notification_script.py /usr/local/bin/notification_script.py
RUN chmod +x /usr/local/bin/notification_script.py
USER icloudpd
WORKDIR /data
EXPOSE 8080
ENTRYPOINT ["icloudpd"]
