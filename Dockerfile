FROM python:3.13-slim AS build
WORKDIR /src
COPY . .
RUN pip install --no-cache-dir --disable-pip-version-check .

FROM python:3.13-slim
RUN useradd --create-home --shell /usr/sbin/nologin icloudpd
COPY --from=build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=build /usr/local/bin/icloudpd /usr/local/bin/icloudpd
COPY --from=build /usr/local/bin/icloud /usr/local/bin/icloud
USER icloudpd
WORKDIR /data
EXPOSE 8080
ENTRYPOINT ["icloudpd"]
